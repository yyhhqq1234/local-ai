#!/usr/bin/env bash
# run_after_expand.sh —— 训练完成后「扩容 → 一键产出两个交付物」
#
# 前置：数据盘已扩到 200 G，full 3 epoch 已结束，out/adapter 存在
# 用法：
#   bash cloud/run_after_expand.sh check      # 只体检，不动任何东西
#   bash cloud/run_after_expand.sh all        # 全链路（每步失败即停）
#   bash cloud/run_after_expand.sh merge|gguf|quant|ninfer|act|layers|pack   # 单步
#
# 产出：
#   merged/Qwen3.8-27B-kittyrev/           HF 合并模型 ≈52 G（base 51.8 实测）
#   gguf/qwen38_27b_kittyrev_bf16.gguf     GGUF bf16 ≈51.5 G（quant 后立刻删）
#   gguf/qwen38_27b_kittyrev_iq2s.gguf     GGUF IQ2_S ≈10 G
#   ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer  ★交付物① ≈10 G
#   merged-layers/layer_48..63 + head      ★交付物② 的一部分 ≈15.3 G
#   act-cache/                              ★交付物② 的一部分 9.11 G（4028 行实测）
#   kittyrev-local-pack.tar                ★交付物② ≈24.4 G（layers + act-cache）
# 峰值：merge/gguf/quant 三份同时在 165 GiB；七步全程不再超过它。
set -euo pipefail

ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
PY=${PY:-/root/miniconda3/bin/python}
# 代码与数据在 $KV（kitty-rev/），产物在 $ROOT —— 两者不是同一层，别再写成 $ROOT/scripts/
KV=${KV:-$ROOT/kitty-rev}
# v4 的基座是 abliterated 版；merge.py 的 BASE 字典里写死的是 v3 的 base/Qwen3.8-27B，
# 所以这里必须显式给 --base，且默认值指向 v4（改回 v3 时用 BASE=... 覆盖）
BASE=${BASE:-$ROOT/base/Huihui}
# v4 的输出目录是 out-v4（train_kitty --out out-v4）；v3 是 out/adapter
ADAPTER=${ADAPTER:-$KV/out-v4/adapter}
# v4：merge 用哪个 adapter 由选优结论决定（logs/v4/pick.md 里的 `[PICK] adapter=` 行，
# 由 cloud/v4_pick.sh 生成）。没有 pick.md 就退回默认路径 —— 但默认路径不存在时
# merge 自己会 FATAL，不会静默用错一个。
PICK_MD=${PICK_MD:-$ROOT/logs/v4/pick.md}
if [ -f "$PICK_MD" ]; then
  _pk=$(awk -F'adapter=' '/^\[PICK\] adapter=/{print $2}' "$PICK_MD" | tail -1)
  if [ -n "${_pk:-}" ]; then
    ADAPTER=$_pk
    echo "[pick] adapter ← pick.md: $ADAPTER"
  else
    echo "[pick][WARN] $PICK_MD 里没有 [PICK] adapter= 行 → 退回 $ADAPTER"
  fi
else
  echo "[pick][WARN] 没有 $PICK_MD（没跑 v4_pick.sh）→ merge 用默认 $ADAPTER"
fi
MERGED=${MERGED:-$ROOT/merged/Qwen3.8-27B-kittyrev-v4}
LC=${LC:-/tmp/lc}
GGUF=$ROOT/gguf
NINFER=$ROOT/ninfer
LAYERS=$ROOT/merged-layers
# v4 的 act-cache 目录叫 act-cache-v4；本地 local_train.ps1 硬编码 act-cache。
# 所以 ACT 必须可覆盖，打包时把实际名字写进 .act-cache-dir-name（gate 7 校验这个契约）。
ACT=${ACT:-$ROOT/act-cache}
IMX=${IMX:-$ROOT/imatrix.dat}
CALIB=${CALIB:-$ROOT/calib.txt}
DATA=$ROOT/kitty-rev/data/large-mix/train.jsonl
# 判据闸门：每一步都要落到「可数的产物特征」，不能只看 exit code（见 verify_expand.py 头注释）
VERIFY=$ROOT/kitty-rev/scripts/verify_expand.py
PIN=$ROOT/kitty-rev/scripts/pin_arch.py
EXPECT=${EXPECT:-$ROOT/kitty-rev/scripts/verify-expect.json}
gate() {  # gate <step> [额外参数...] —— 不合格即停整条链路
  local st=$1; shift
  if [ ! -f "$VERIFY" ]; then echo "[FATAL] 缺判据脚本 $VERIFY"; exit 1; fi
  local ex=()
  [ -f "$EXPECT" ] && ex=(--expect-file "$EXPECT")
  $PY "$VERIFY" --root "$ROOT" --step "$st" "${ex[@]}" "$@" || {
    echo "[FATAL] 步骤 $st 的产物特征不合格（exit code 为 0 不代表内容对）"; exit 1; }
}
LOG=$ROOT/logs/after-expand.log
mkdir -p "$ROOT/logs"
say() { echo; echo "===== [$(date +%H:%M:%S)] $* =====" | tee -a "$LOG"; }
dfv() { df -h "$ROOT" | tail -1 | awk '{print $4}'; }
need_g() {  # need_g <GB> <说明>
  local free_k; free_k=$(df -k "$ROOT" | tail -1 | awk '{print $4}')
  local need_k=$(( $1 * 1024 * 1024 ))
  local free_g=$(( free_k / 1024 / 1024 ))
  echo "[disk] 需要 ${1}G，当前可用 ${free_g}G"
  if [ "$free_k" -lt "$need_k" ]; then echo "[FATAL] 磁盘不足：$2"; return 1; fi
}

case "${1:-check}" in

check)
  say "体检"
  echo "root      = $ROOT"
  df -h "$ROOT" | tail -2
  echo "base      = $([ -d "$BASE" ] && du -sh "$BASE" | cut -f1 || echo MISSING)"
  echo "adapter   = $([ -f "$ADAPTER/adapter_config.json" ] && du -sh "$ADAPTER" | cut -f1 || echo MISSING)"
  echo "merged    = $([ -d "$MERGED" ] && du -sh "$MERGED" | cut -f1 || echo MISSING)"
  echo "llama.cpp = $([ -f "$LC/convert_hf_to_gguf.py" ] && echo OK || echo MISSING)"
  echo "cmake     = $(cmake --version 2>/dev/null | head -1 || echo MISSING)"
  echo "gcc       = $(gcc --version 2>/dev/null | head -1 || echo MISSING)"
  echo "train_kitty 进程 = $(pgrep -c -f train_kitty 2>/dev/null || echo 0)（必须为 0）"
  echo "GPU = $(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null || echo n/a)"
  ;;

merge)
  say "① merge（base + adapter → merged）"
  [ -f "$ADAPTER/adapter_config.json" ] || { echo "[FATAL] adapter 缺失"; exit 1; }
  need_g 56 "merge 需 merged 54G"
  # 幂等判据 = 产物特征（shard 数 + index + config），不是「config.json 在不在」。
  # 旧写法只要 config 在就 skip：上一轮 merge 中断（shard 少几个）会被当成已完成，
  # 接着 convert 出来「张量数不对但能加载」的 GGUF —— exit 0，全链绿灯。
  nshard=0
  [ -d "$MERGED" ] && nshard=$(ls "$MERGED"/*.safetensors 2>/dev/null | grep -vc index || true)
  if [ -f "$MERGED/config.json" ] && [ -f "$MERGED/model.safetensors.index.json" ] && [ "${nshard:-0}" -ge 18 ]; then
    echo "[skip] merged 已完整（shards=$nshard + index + config）"
  elif [ -f "$MERGED/config.json" ]; then
    echo "[FATAL] merged 目录不完整（shards=${nshard} < 18 或缺 index.json）——"
    echo "        上次 merge 中断的残留。删掉 $MERGED 重跑，别在残骸上 convert"
    exit 1
  else
    # 三处都曾错：① 路径少了 KV（$ROOT 下没有 scripts/）② 没传 --base（merge.py 的 BASE 字典
    # 写死 v3 的 base/Qwen3.8-27B）③ --size 保留 —— 它决定 merge.py 里的磁盘守卫档位
    # （27b → 需 54 GiB；缺省 8b 只查 16 GiB，等于把守卫调松）
    $PY "$KV/scripts/merge.py" --size 27b --base "$BASE" --adapter "$ADAPTER" --dest "$MERGED"
  fi
  du -sh "$MERGED"; echo "free=$(dfv)"
  gate 1 --merged "$MERGED" --base "$BASE"
  # v4 雷区 c：merged 只有 text 张量，但 architectures 仍是 ConditionalGeneration，
  # convert 会按架构选 VL 分支。merge 后、convert 前必须 pin（幂等/无 .bak/回读校验）
  if [ ! -f "$PIN" ]; then
    echo "[FATAL] 缺 $PIN —— 不 pin architectures 就 convert 是 v4 头号静默错（坑 c）"
    exit 1
  fi
  $PY "$PIN" --dir "$MERGED" --index || { echo "[FATAL] pin_arch 失败"; exit 1; }
  ;;

gguf)
  say "② convert_hf_to_gguf（merged → GGUF bf16 54G）"
  need_g 56 "GGUF bf16 需 54G"
  mkdir -p "$GGUF"
  OMP_NUM_THREADS=16 nice -n 10 $PY "$LC/convert_hf_to_gguf.py" "$MERGED" \
      --outfile "$GGUF/qwen38_27b_kittyrev_bf16.gguf" --outtype bf16
  ls -lh "$GGUF"/*.gguf; echo "free=$(dfv)"
  gate 2 --gguf "$GGUF/qwen38_27b_kittyrev_bf16.gguf" --base "$BASE"
  ;;

imatrix)
  say "②b imatrix（IQ2_S 的量化误差权重表）"
  # 逻辑只有一份：make_imatrix.sh（calib 生成 + 幂等 + 出处侧车 + gate 2b）。
  # 不在七步里再写第二份 —— 两处实现必然漂移（本项目 19 个静默错的共同来源）。
  ROOT="$ROOT" LC="$LC" PYTHON="$PY" CALIB="$CALIB" IMATRIX="$IMX" \
    bash "$(dirname "$0")/make_imatrix.sh" --gate
  ;;

quant)
  say "③ 编译 llama-quantize（若无）"
  if [ ! -x "$LC/build/bin/llama-quantize" ]; then
    cmake -S "$LC" -B "$LC/build" -DLLAMA_CURL=OFF -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release >/dev/null
    cmake --build "$LC/build" --target llama-quantize -j 16 2>&1 | tail -5
  fi
  ls -l "$LC/build/bin/llama-quantize"
  say "③ llama-quantize → IQ2_S"
  [ -f "$GGUF/qwen38_27b_kittyrev_bf16.gguf" ] || { echo "[FATAL] 缺 bf16 GGUF"; exit 1; }
  need_g 12 "IQ2_S 输出 10G"
  # IQ 系列**必须** imatrix，否则 llama.cpp 直接拒；ssm_alpha/beta 必须留 q8_0，
  # 否则 recipe 的 GDN_CONTROL_TYPES=(BF16,Q8_0) 拒绝。两条都用 --tensor-type 逐条给
  # （--tensor-type-file 实测会失败）。少了这两条 → rc=0 但产物被下游拒。
  # 缺就现场生成（幂等）：v4 的一键链不能假设「imatrix 已经在」—— v3 是手工跑的，
  # 脚本里只有一句 [ -f ] 检查，所以换到一键链就会在这里直接 FATAL。
  ROOT="$ROOT" LC="$LC" PYTHON="$PY" CALIB="$CALIB" IMATRIX="$IMX" \
    bash "$(dirname "$0")/make_imatrix.sh" --gate \
    || { echo "[FATAL] imatrix 缺失且自动生成失败（见上）"; exit 1; }
  tt=()
  i=0
  for i in $(seq 0 63); do
    tt+=(--tensor-type "blk.$i.ssm_alpha.weight=q8_0")
    tt+=(--tensor-type "blk.$i.ssm_beta.weight=q8_0")
  done
  "$LC/build/bin/llama-quantize" --imatrix "$ROOT/imatrix.dat" "${tt[@]}" \
      "$GGUF/qwen38_27b_kittyrev_bf16.gguf" \
      "$GGUF/qwen38_27b_kittyrev_iq2s.gguf" IQ2_S 16 2>&1 | tail -6
  ls -lh "$GGUF"/qwen38_27b_kittyrev_iq2s.gguf; echo "free=$(dfv)"
  gate 3 --quant "$GGUF/qwen38_27b_kittyrev_iq2s.gguf"
  ;;

ninfer)
  say "④ tools.convert（GGUF IQ2_S → .ninfer）★交付物①"
  [ -f "$GGUF/qwen38_27b_kittyrev_iq2s.gguf" ] || { echo "[FATAL] 缺 IQ2_S GGUF"; exit 1; }
  mkdir -p "$NINFER"
  need_g 14 ".ninfer 输出 10G"
  ( cd "$ROOT/ninfer-master" && $PY -m tools.convert \
      --recipe qwen3_8_27b_gguf \
      --source gguf="$GGUF/qwen38_27b_kittyrev_iq2s.gguf" \
      --components text \
      --name qwen3.8-27b-kittyrev-iq2s \
      --out "$NINFER/qwen3_8_27b_kittyrev_iq2s.ninfer" )
  ls -lh "$NINFER"/*.ninfer
  # 判据不能是 head -12 瞟一眼：落成 json/txt，按 objects/tensors/formats 硬判（step 5）
  ( cd "$ROOT/ninfer-master" && $PY -m tools.artifact.inspect \
      "$NINFER/qwen3_8_27b_kittyrev_iq2s.ninfer" ) > "$ROOT/logs/inspect-iq2s.txt" 2>&1
  head -12 "$ROOT/logs/inspect-iq2s.txt"
  gate 5 --ninfer "$NINFER/qwen3_8_27b_kittyrev_iq2s.ninfer" --inspect-json "$ROOT/logs/inspect-iq2s.txt"
  echo "free=$(dfv)"
  ;;

act)
  say "⑤ act-cache（前 48 层激活，按子集分目录）★交付物②"
  # 4028 行实测 9.11 GiB；留 ~1.9 GiB 缓冲（贴着实际值查等于没查）
  need_g 11 "act-cache 9.11G（4028 行）"
  # --split-by-subsets: 一次前向，按内容哈希把每条样本落到 re-train/re-val/
  # route-train/... /rest 子目录。train_partial_lora 的 --data-mix 每个源
  # 需要一个独立目录，平铺的单目录会让它启动即 FATAL。
  $PY "$ROOT/kitty-rev/scripts/precompute_activations.py" \
      --model "$MERGED" --cut 48 --data "$DATA" --ctx 512 \
      --split-by-subsets "$ROOT/kitty-rev/data/subsets" \
      --out "$ACT"
  du -sh "$ACT"
  for d in "$ACT"/*/; do
    [ -d "$d" ] && printf '  %-20s %6s .pt\n' "$(basename "$d")" "$(ls "$d"/*.pt 2>/dev/null | wc -l)"
  done
  gate 6 --actcache "$ACT"
  echo "free=$(dfv)"
  ;;

layers)
  say "⑥ 拆层（只要 layer_48..63 + head）★交付物②"
  need_g 16 "16 层 + head ≈ 15G"
  $PY "$ROOT/kitty-rev/scripts/split_model_layers.py" \
      --src "$MERGED" --out "$LAYERS"
  ls -lh "$LAYERS"/layer_4*.safetensors "$LAYERS"/layer_5*.safetensors "$LAYERS"/layer_6*.safetensors "$LAYERS"/head.safetensors | tail -20
  echo "free=$(dfv)"
  ;;

pack)
  say "⑦ 打包回传"
  # 实际要写 layers 15.3 + act-cache 9.11 ≈ 24.4 GiB（4028 行）。原来写 15 会在
  # tar 中途 ENOSPC，tar 断了还得重打。
  need_g 26 "tar ≈ 24.4G（16 层 15.3 + act 9.11）"
  # act-cache 目录名契约（**单一约定**，别两处都改）：
  #   包内永远叫 act-cache/ —— 本机 local_train.ps1 / verify_local_pack.py 都按这个名字硬编码。
  #   v4 的源目录叫 act-cache-v4，所以在 tar 时用 --transform 改名，而不是去改本机脚本。
  #   .act-cache-dir-name 同时写上「包内的名字」，gate 7 校验「声明的目录真的在包里」。
  ACT_SRC_NAME=$(basename "$ACT")
  ACTNAME=act-cache
  printf "%s" "$ACTNAME" > "$ROOT/.act-cache-dir-name"
  echo "[pack] 源目录 = $ACT_SRC_NAME → 包内 = $ACTNAME（已写 .act-cache-dir-name）"
  ( cd "$ROOT" && tar -cf kittyrev-local-pack.tar \
      --transform "s,^${ACT_SRC_NAME},${ACTNAME}," \
      merged-layers/layer_4[89].safetensors merged-layers/layer_5*.safetensors \
      merged-layers/layer_6*.safetensors merged-layers/head.safetensors \
      merged-layers/layers_index.json "$ACT_SRC_NAME" .act-cache-dir-name )
  ls -lh "$ROOT/kittyrev-local-pack.tar"
  echo "tar 内文件数（应为 16 层 + head + index + 3908 act）:"
  tar -tf "$ROOT/kittyrev-local-pack.tar" | wc -l
  gate 7 --pack "$ROOT/kittyrev-local-pack.tar"
  echo "free=$(dfv)"
  ;;

all)
  say "全链路开始"
  bash "$0" check
  bash "$0" merge
  bash "$0" gguf
  bash "$0" imatrix          # ②b：IQ2_S 必需，且必须比 bf16.gguf 新
  bash "$0" quant
  # bf16 GGUF 只有 quant 之前需要（ninfer 读的是 IQ2_S）。
  # 提前到这里删：峰值 175.0 → 165.0 GiB（merged + gguf_bf16 + iq2s 三份同时在的时段）。
  say "删除 bf16 GGUF 回收 51.5G"
  rm -f "$GGUF/qwen38_27b_kittyrev_bf16.gguf"
  echo "free=$(dfv)"
  bash "$0" ninfer
  bash "$0" act
  bash "$0" layers
  bash "$0" pack
  say "全链路完成"
  df -h "$ROOT" | tail -1
  ;;

*) echo "用法: bash cloud/run_after_expand.sh check|all|merge|gguf|imatrix|quant|ninfer|act|layers|pack"; exit 1 ;;
esac

#!/usr/bin/env bash
# =============================================================================
# make_imatrix.sh —— 生成 IQ2_S 量化必需的 imatrix.dat（+ 出处侧车 .meta.json）
#
# 为什么有这一步
#   IQ 系列量化强制要 imatrix，否则 llama-quantize 直接拒；七步脚本 ③ 里
#   `[ -f "$ROOT/imatrix.dat" ]` 是硬闸门，但全仓库**没有任何地方生成它**
#   （v3 是手工跑的 524 chunks / ~12 min，所以脚本当年能过；v4 走一键链会在 ③ 直接 FATAL）。
#
# calib.txt 从哪来（核实结果，不是猜）
#   `grep -rn "calib\|llama-imatrix" deploy/ scripts/ *.md` 在仓库里 **0 命中** ——
#   v3 那次手工 imatrix 用的 calib 文件没有留下、也没有生成命令。既然没有既有口径可抄，
#   本脚本把它**定义死**并写进侧车：imatrix.dat.meta.json
#       · 语料 = 本轮训练用的 data/large-mix-plus/train.jsonl（4388 行，单变量）
#       · 每条 = user 段 + assistant 段（多轮全拼），一行一条，UTF-8 纯文本
#       · 固定种子打散（seed 42）后整份喂给 llama-imatrix，用 --chunks 524 截取
#         → 524 × 512 tok ≈ 26.8 万 token ≈ 语料的 1/4，打散后仍覆盖全部子类
#   —— 以后要换 calib，用环境变量 CALIB=<path>（已有文件直接用）或 TRAIN_DATA=<jsonl> 换语料；
#      口径永远落在侧车 imatrix.dat.meta.json 里（calib 路径 + sha16 + chunks + llama commit），
#      verify_expand.py 的 gate 2b 会核这个侧车。
#
# 幂等
#   已存在 且 ≥ --min-mb 且 **不早于 bf16 GGUF**（旧 imatrix 配新模型 = 量化误差静默变大，
#   verify_expand.py 的 gate 2b 就是这么判的）→ 直接跳过，打印 SKIP 后 return 0。
#   --force 强制重算。
#
# 用法
#   bash cloud/make_imatrix.sh                 # 幂等：需要才算
#   bash cloud/make_imatrix.sh --force         # 强制重算
#   bash cloud/make_imatrix.sh --dry-run       # 只打印将执行的命令与判定，不动文件
#   bash cloud/make_imatrix.sh --gate          # 算完顺手跑 verify_expand --step 2b（gate 2b）
#   THREADS=32 CHUNKS=1024 bash cloud/make_imatrix.sh
# =============================================================================
set -eu

R=${ROOT:-/root/autodl-tmp/kitty-rev}
LC=${LC:-/tmp/lc}
PY=${PYTHON:-/root/miniconda3/bin/python}
DUMP=$R/gguf/qwen38_27b_kittyrev_bf16.gguf
CALIB=${CALIB:-$R/calib.txt}
IMAT=${IMATRIX:-$R/imatrix.dat}
META=$IMAT.meta.json
TRAIN=${TRAIN_DATA:-$R/kitty-rev/data/large-mix-plus/train.jsonl}
THREADS=${THREADS:-16}
CTX=${CTX:-512}
BATCH=${BATCH:-2048}
CHUNKS=${CHUNKS:-524}
MIN_MB=${MIN_MB:-1}
FORCE=0
DRY=0
GATE=0

for arg in "$@"; do
  case "$arg" in
    --force)   FORCE=1 ;;
    --dry-run) DRY=1 ;;
    --gate)    GATE=1 ;;
    -h|--help) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "[FATAL] 未知参数：$arg（--help 看用法）"; exit 2 ;;
  esac
done

say()  { printf '\n===== [%s] %s =====\n' "$(date +%H:%M:%S)" "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '\n[FATAL] %s\n' "$*" >&2; exit 2; }

need_mb() {  # 产物最小字节（MiB）
  local n
  n=$(stat -c%s "$1" 2>/dev/null || echo 0)
  echo $(( n / 1024 / 1024 ))
}

say "imatrix 前置判定"
note "bf16 gguf = $DUMP"
note "calib     = $CALIB"
note "imatrix   = $IMAT（下限 ${MIN_MB} MiB）"

# ---------- 0) 前置：bf16 GGUF 必须在（imatrix 必须针对这份权重算） ----------
if [ ! -f "$DUMP" ]; then
  if [ "$DRY" -eq 1 ]; then
    note "[dry] 缺 $DUMP —— 真跑会 FATAL（先跑 run_after_expand.sh gguf）"
  else
    die "缺 bf16 GGUF：$DUMP。imatrix 必须针对这份权重算 —— 先跑 run_after_expand.sh gguf"
  fi
fi

# ---------- 1) 幂等：够大且不早于 gguf → 跳过 ----------
if [ -f "$IMAT" ] && [ "$FORCE" -eq 0 ]; then
  sz_mb=$(need_mb "$IMAT")
  if [ "$sz_mb" -lt "$MIN_MB" ]; then
    note "已有 imatrix 只有 ${sz_mb} MiB < ${MIN_MB} MiB → 视为半写/无效，重算"
  elif [ -f "$DUMP" ] && [ "$IMAT" -ot "$DUMP" ]; then
    note "已有 imatrix 比 bf16 GGUF 旧（旧表配新权重 = 量化误差静默变大）→ 重算"
  else
    say "SKIP：imatrix 已就绪"
    note "大小 ${sz_mb} MiB · $(stat -c%y "$IMAT" 2>/dev/null | cut -d. -f1)"
    note "侧车 $([ -f "$META" ] && echo 在 || echo '缺（gate 2b 会给 WARN）')"
    printf '[VERDICT] imatrix: SKIP —— 已存在且有效（--force 可强制重算）\n'
    if [ "$GATE" -eq 1 ]; then
      VERIFY=$R/kitty-rev/scripts/verify_expand.py
      [ -f "$VERIFY" ] || die "缺判据脚本 $VERIFY"
      "$PY" "$VERIFY" --root "$R" --step 2b --imatrix "$IMAT" --gguf "$DUMP" \
        || die "gate 2b 不合格（见上）"
    fi
    exit 0
  fi
fi

# ---------- 2) calib.txt ----------
if [ -f "$CALIB" ] && [ -s "$CALIB" ]; then
  note "calib 已存在：$(stat -c%s "$CALIB") B"
else
  if [ "$DRY" -eq 1 ]; then
    note "[dry] 将把 $TRAIN 打散(seed42)拼接成 $CALIB（真跑时若缺语料直接 FATAL）"
  else
    [ -f "$TRAIN" ] || die "缺训练语料 $TRAIN（calib 就是它的打散拼接；用 TRAIN_DATA=<path> 换源）"
    note "生成 calib ← $TRAIN"
    "$PY" - "$TRAIN" "$CALIB" <<'PY' || die "calib 生成失败"
import json, sys, random
src, dst = sys.argv[1], sys.argv[2]
rows = []
with open(src, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))
out = []
for r in rows:
    parts = []
    for m in r.get("messages") or []:
        c = (m.get("content") or "").strip()
        if c:
            parts.append(c)
    if parts:
        out.append("\n".join(parts))
if not out:
    print("[FATAL] 语料里没有可用文本")
    sys.exit(2)
random.Random(42).shuffle(out)          # 固定种子：同一份语料永远得到同一个 calib
with open(dst, "w", encoding="utf-8") as f:
    f.write("\n\n".join(out) + "\n")
print(f"  [calib] rows={len(out)} chars={sum(len(x) for x in out)} → {dst}")
PY
  fi
fi

# ---------- 3) 编 llama-imatrix（缺才编） ----------
BIN=$LC/build/bin/llama-imatrix
if [ ! -x "$BIN" ]; then
  note "编译 llama-imatrix（$LC）"
  if [ "$DRY" -eq 1 ]; then
    note "[dry] cmake -S $LC -B $LC/build -DLLAMA_CURL=OFF -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release"
    note "[dry] cmake --build $LC/build --target llama-imatrix -j 16"
  else
    [ -f "$LC/CMakeLists.txt" ] || die "缺 llama.cpp 源码：$LC（convert_hf_to_gguf.py 之类应该都在）"
    cmake -S "$LC" -B "$LC/build" -DLLAMA_CURL=OFF -DGGML_NATIVE=ON \
          -DCMAKE_BUILD_TYPE=Release >/dev/null || die "cmake configure 失败（$LC）"
    cmake --build "$LC/build" --target llama-imatrix -j 16 2>&1 | tail -5 \
      || die "llama-imatrix 编译失败"
    [ -x "$BIN" ] || die "编译后仍没有 $BIN"
  fi
else
  note "llama-imatrix 已在：$BIN"
fi

# ---------- 4) 跑 imatrix ----------
LOG=$R/logs/imatrix.log
say "生成 imatrix（${CHUNKS} chunks · ctx ${CTX} · batch ${BATCH} · ${THREADS} 线程，约 8-12 min）"
CMD=("$BIN" -m "$DUMP" -f "$CALIB" -o "$IMAT"
     --chunks "$CHUNKS" -t "$THREADS" -c "$CTX" -b "$BATCH" --output-frequency 64)
if [ "$DRY" -eq 1 ]; then
  note "[dry] ${CMD[*]} 2>&1 | tee -a $LOG"
  printf '[VERDICT] imatrix: DRY-RUN —— 将按上面参数生成 %s\n' "$IMAT"
  exit 0
fi
mkdir -p "$R/logs"
# 先删旧产物：llama-imatrix 对已存在的 -o 是覆盖，但半写残留会让后面的"大小够"误判
rm -f "$IMAT"
"${CMD[@]}" 2>&1 | tee -a "$LOG" | tail -12
[ "${PIPESTATUS[0]:-0}" -eq 0 ] || die "llama-imatrix 退出码非 0（日志 $LOG）"

# ---------- 5) 校验 + 侧车 ----------
[ -f "$IMAT" ] || die "跑完却没有 $IMAT（llama-imatrix 静默失败？看 $LOG）"
SZ=$(stat -c%s "$IMAT")
SZ_MB=$(( SZ / 1024 / 1024 ))
note "产物：$IMAT  ${SZ} B（${SZ_MB} MiB）"
if [ "$SZ" -lt $(( MIN_MB * 1024 * 1024 )) ]; then
  die "imatrix 只有 ${SZ_MB} MiB < ${MIN_MB} MiB —— 半写或参数错，删掉重跑"
fi

# llama.cpp 版本：只有 $LC 自己就是 git 仓库时才敢读（否则 git 会向上找到无关仓库，
# 记下别人的 commit —— 出处造假比没出处更坏）
if [ -d "$LC/.git" ]; then
  COMMIT=$(git -C "$LC" rev-parse --short HEAD 2>/dev/null || echo unknown)
elif [ -f "$LC/VERSION" ]; then
  COMMIT=$(head -1 "$LC/VERSION" 2>/dev/null || echo unknown)
else
  COMMIT=unknown
fi
CALIB_SHA=$("$PY" - "$CALIB" <<'PY' 2>/dev/null || echo unknown
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""):
        h.update(b)
print(h.hexdigest()[:16])
PY
)
"$PY" - "$META" "$CALIB" "$CALIB_SHA" "$CHUNKS" "$COMMIT" "$DUMP" "$SZ" <<'PY'
import json, sys, time
meta_p, calib, calib_sha, chunks, commit, dump, sz = sys.argv[1:8]
json.dump({"created": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "calib": calib, "calib_sha16": calib_sha,
           "chunks": int(chunks), "llama_commit": commit,
           "gguf": dump, "imatrix_bytes": int(sz),
           "rule": "calib = large-mix-plus/train.jsonl 打散(seed42) 拼接；chunks=524×512tok"},
          open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"  [meta] {meta_p}")
PY

# ---------- 6) gate 2b ----------
if [ "$GATE" -eq 1 ]; then
  say "gate 2b（verify_expand --step 2b）"
  VERIFY=$R/kitty-rev/scripts/verify_expand.py
  [ -f "$VERIFY" ] || die "缺判据脚本 $VERIFY"
  "$PY" "$VERIFY" --root "$R" --step 2b --imatrix "$IMAT" --gguf "$DUMP" \
    || die "gate 2b 不合格（见上）"
fi

printf '[VERDICT] imatrix: PASS —— %s（%s MiB · calib sha16 %s · chunks %s）\n' \
  "$IMAT" "$SZ_MB" "$CALIB_SHA" "$CHUNKS"

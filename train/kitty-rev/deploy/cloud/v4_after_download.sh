#!/usr/bin/env bash
# =============================================================================
# v4_after_download.sh —— Huihui-Qwen3.8-27B-abliterated 下载完成后的一条命令全链
#
#   S0 下载完整性 → S1 硬指标 → S2 base-only 基线 → S3 act-cache-v4 → S4 开训
#
# 纪律
#   · set -eu（**故意不用 pipefail**：v3 在 `| head -1` 上被 SIGPIPE 打死过，
#     一次“成功”的跑法被记成失败，之后没人敢信日志）
#   · 任何一步不通过就停在那一步 —— 带着错往下跑是本项目 19 个静默错的共同签名
#   · 每个 stage 可单独跑；不做的事必须打印 SKIP，不许静默跳过
#   · 所有 FATAL 都打印「触发源」（哪个文件/哪个数/哪条命令），一眼看出停在哪
#
# 逃生口（都会打印显式 WARN，不静默）
#   --stage s0|s1|s2|s3|s4|all   只跑某一段（默认 all）
#   --skip-baseline              S2 跳过（日志里会少 re_pass / bench_f1 / refusal_rate）
#   --allow-total-drift          S0 总字节不符也放行（红字警告）
#   --dry-run                    只打印将执行的命令序列 + 磁盘闸门判定，零副作用
#   --s1-load 4bit|cpu           S1 用 4bit（默认，24G 卡够）还是 bf16-CPU（要 ~52G 内存）
#   --port N                     S2 的 serve 端口（默认 18000）
#   --train-max-steps N          S4 只跑 N 步（冒烟用；默认 -1 = 3 epoch 全量）
#   --strict-90s-gpu             S4 自检第一段就要求 90 s 内显存 >18 GiB（默认更宽，见下）
#   --root DIR / --python PATH   换根目录 / 解释器（自测与异地复用用）
#
# 上传清单（缺一条就会在对应阶段 FATAL，不会静默）
#   deploy/cloud/v4_after_download.sh        ← 本文件
#   kitty-rev/scripts/train_kitty.py         ← 必须带 --dl-workers/--pin-memory/--prefetch
#                                              （本轮新增，默认关 = 与 v3 逐比特一致）
#   kitty-rev/tmp/eval_bare.py               ← data-forge 交付的 base-only wrapper
#   kitty-rev/scripts/{serve_4bit_base,refusal_probe,precompute_activations}.py
#   kitty-rev/data/{large-mix-plus/train.jsonl, eval_re_extended.jsonl,
#                   large-mix/eval.jsonl, subsets/}
#
# 磁盘闸门（每阶段开始前判定；不够就停在原地，不写任何东西）
#   进 S1 前 ≥ 100 G（要给 merged 51.75 G 留位置）
#   进 S2 前 ≥  95 G
#   进 S3 前 ≥  95 G（= S2 之后那一关）
#   进 S4 前 ≥  80 G（= S3 之后那一关）
#
# 与 OPS 文档的一处偏差（故意，已在报告里写明）
#   OPS 说「S4 起来后 90 秒内日志出现 step 1」。27B 光从盘上加载就 1.5-3 分钟，
#   90 s 内不可能出现 step。所以自检分两段：
#     A 段 0..90 s   ：进程必须活着 + 日志不得出现 Traceback/FATAL（死了立刻停）
#     B 段 90..900 s ：必须看到 GPU 显存 >18 GiB 且日志出现 loss/step 行，否则 FATAL
#   想要 OPS 原文的严格版就加 --strict-90s-gpu（A 段就要求显存 >18 GiB）。
# =============================================================================
set -eu

# ---------------------------------------------------------------- 默认值 ----
R=${ROOT:-/root/autodl-tmp/kitty-rev}
PY=${PYTHON:-/root/miniconda3/bin/python}
# 布局自适应（2026-10-22 部署时修）：原假设两级 $R/{base,logs} + $R/kitty-rev/{scripts,data}；
# 云端也可能是扁平（base/logs/scripts/data 全在 $R 下）。判定规则见下，判定后立刻打印两行
# [layout]，data/base 任一不存在直接 FATAL —— 不许静默在错的树上继续跑。
LAYOUT=""
set_layout() {
  if   [ -d "$R/kitty-rev/scripts" ]; then KV="$R/kitty-rev"; LAYOUT="两级"
  elif [ -d "$R/scripts" ];          then KV="$R";            LAYOUT="扁平"
  else KV="$R"; LAYOUT="未知"; fi
  LOGS="$R/logs/v4"
  HUHUI="$R/base/Huihui"
  printf '[layout] R=%s  KV=%s  (%s)\n' "$R" "$KV" "$LAYOUT"
  printf '[layout] data=%s  base=%s\n' "$KV/data" "$HUHUI"
  [ -d "$KV/data" ] || { printf '[FATAL] 布局判定失败：%s 不存在（拒绝在错的树上继续）\n' "$KV/data" >&2; exit 2; }
  [ -d "$HUHUI" ]   || { printf '[FATAL] 布局判定失败：%s 不存在（model 目录缺失）\n' "$HUHUI" >&2; exit 2; }
}
set_layout
# 期望总字节 = 纯张量字节(27,781,427,952×2=55,562,855,904) + 18 个 safetensors header 之和(150,312)
# 注意：参数×2 ≠ 磁盘字节，.safetensors 有 8 字节长度前缀 + header JSON（2026-10-22 实测差 150,312 B）
EXPECT_TOTAL=55563006216
EXPECT_SHARDS=18
EXPECT_TENSORS=1199               # model.safetensors.index.json 的 weight_map 条数
EXPECT_PARAMS=79691776            # v3/v4 可比性的唯一客观证据
EXPECT_CLASS=Qwen3_5ForCausalLM
EXPECT_PT=4388                    # act-cache-v4 的 .pt 总数
EXPECT_ACT_DIRS=11
PORT=18000
S1_LOAD=4bit
GPU_MIN_FREE=22000                # S4 开跑前 GPU 至少空出 22 GiB（4090 24G）
GPU_MIN_USED=18000                # S4 自检：显存占用 >18 GiB 才算“真在训”
TRAIN_SELFCHECK_S=90
TRAIN_START_TIMEOUT_S=900
TRAIN_MAX_STEPS=-1
STRICT_90S_GPU=0

STAGE=all
DRY=0
SKIP_BASE=0
ALLOW_DRIFT=0
CUR_STAGE=pre
SERVER_PID=""

usage() {
  # 打印文件头的注释块（从第 2 行起，到第二条 "# ====" 分隔线为止）
  awk 'NR==1{next} /^# ={20,}/{c++; if(c==2) exit; next} {sub(/^# ?/,""); print}' "$0"
}

# ------------------------------------------------------------ 小工具 ----
say()   { printf '\n===== [%s] %s =====\n' "$(date +%H:%M:%S)" "$*"; }
note()  { printf '  %s\n' "$*"; }
warn()  { printf '[WARN] %s\n' "$*" >&2; }
red()   { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
fatal() {
  printf '\n[FATAL] %s\n' "$*" >&2
  printf '[FATAL] 停在 %s —— 未继续（这是设计，不是 bug）\n' "$CUR_STAGE" >&2
  exit 2
}

# 可用空间（GB）。目录还不存在时向上找到第一个存在的祖先。
avail_gb() {
  local p=${1:-$R}
  while [ ! -d "$p" ] && [ "$p" != "/" ] && [ "$p" != "." ]; do p=$(dirname "$p"); done
  df -BG "$p" 2>/dev/null | tail -1 | awk '{print $4}' | tr -dc '0-9'
}

# 磁盘闸门：不够就停，什么都不写
gate() {                        # gate <需要GB> <标签>
  local need=$1 label=$2 av
  av=$(avail_gb "$R")
  if [ -z "$av" ]; then warn "df 取不到 $R 的可用空间，跳过闸门（$label 需 ${need}G）"; return 0; fi
  if [ "$av" -lt "$need" ]; then
    fatal "磁盘闸门：$label 需要 ≥${need}G，当前只有 ${av}G"
  fi
  printf '[gate] %s：需要 %sG · 可用 %sG ✓\n' "$label" "$need" "$av"
}

stage_need_gb() {               # 进这一阶段前至少要多少 G
  case "$1" in
    s1) echo 100 ;;             # = S0 之后那一关
    s2) echo 95 ;;
    s3) echo 95 ;;              # = S2 之后那一关
    s4) echo 80 ;;              # = S3 之后那一关
    *)  echo 0 ;;
  esac
}

gpu_used_mib() {
  command -v nvidia-smi >/dev/null 2>&1 || { echo ""; return 0; }
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null \
    | head -1 | tr -dc '0-9'
}

gpu_free_mib() {
  command -v nvidia-smi >/dev/null 2>&1 || { echo ""; return 0; }
  nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null \
    | head -1 | tr -dc '0-9'
}

port_state() {                  # busy | free
  "$PY" - "$1" <<'PY'
import socket, sys
s = socket.socket(); s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", int(sys.argv[1]))); print("busy")
except Exception:
    print("free")
finally:
    s.close()
PY
}

tail_log() {                    # tail_log <文件> <行数>
  [ -f "$1" ] || { printf '  (日志不存在：%s)\n' "$1"; return 0; }
  printf '  ---- tail -%s %s ----\n' "$2" "$1"
  tail -n "$2" "$1" | sed 's/^/  | /'
}

cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    printf '[cleanup] 已停掉 S2 的 serve 进程 pid=%s\n' "$SERVER_PID"
  fi
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------- 参数解析 ----
while [ $# -gt 0 ]; do
  case "$1" in
    --stage)                STAGE=${2:?--stage 需要值}; shift 2 ;;
    --root)                 R=$2; set_layout; shift 2 ;;
    --python)               PY=$2; shift 2 ;;
    --expect-total)         EXPECT_TOTAL=$2; shift 2 ;;
    --s1-load)              S1_LOAD=$2; shift 2 ;;
    --port)                 PORT=$2; shift 2 ;;
    --train-max-steps)      TRAIN_MAX_STEPS=$2; shift 2 ;;
    --train-selfcheck)      TRAIN_SELFCHECK_S=$2; shift 2 ;;
    --train-start-timeout)  TRAIN_START_TIMEOUT_S=$2; shift 2 ;;
    --skip-baseline)        SKIP_BASE=1; shift ;;
    --allow-total-drift)    ALLOW_DRIFT=1; shift ;;
    --strict-90s-gpu)       STRICT_90S_GPU=1; shift ;;
    --dry-run)              DRY=1; shift ;;
    -h|--help)              usage; exit 0 ;;
    *)                      fatal "未知参数：$1（--help 看用法）" ;;
  esac
done

case "$STAGE" in
  s0|s1|s2|s3|s4|all) ;;
  *) fatal "--stage 只接受 s0|s1|s2|s3|s4|all，收到：$STAGE" ;;
esac
case "$S1_LOAD" in
  ''|4bit|cpu) ;;
  *) fatal "--s1-load 只接受 4bit|cpu，收到：$S1_LOAD" ;;
esac
# 解释器可用性：直接问它一句（比 [ -x ] 可靠：Windows/Cygwin 下 .exe 的 -x 位不可信）
PYVER=$("$PY" -c 'import sys;print(sys.version.split()[0])' 2>/dev/null || true)
[ -n "$PYVER" ] || fatal "解释器不可用：$PY（用 --python 指定）"

say "v4 全链 · stage=$STAGE · dry_run=$DRY"
note "root   = $R"
note "code   = $KV"
note "python = $PY"
note "base   = $HUHUI"
note "logs   = $LOGS"
if [ "$DRY" -eq 0 ]; then
  mkdir -p "$LOGS"
fi
if [ "$ALLOW_DRIFT" -eq 1 ]; then
  red "[!] --allow-total-drift 已启用：S0 总字节不符也会放行 —— 这是逃生口，不是正常路径"
fi

# ===========================================================================
# S0 —— 下载完整性（四条，全过才继续）
# ===========================================================================
stage_s0() {
  CUR_STAGE=S0
  say "S0 下载完整性"
  note "目录：$HUHUI"

  if [ "$DRY" -eq 1 ]; then
    note "[dry] 将执行："
    note "  1) ls $HUHUI/model-*-of-*.safetensors | wc -l   → 必须 == $EXPECT_SHARDS"
    note "  2) python 内嵌：逐 shard  8 + header_len + max(data_offsets[1]) == filesize"
    note "     → PASS/FAIL 逐行打印 + 落 $LOGS/s0-bytes.txt"
    note "  3) 18 shard 字节合计 == $EXPECT_TOTAL（--allow-total-drift 可放行）"
    note "  4) $HUHUI/model.safetensors.index.json 的 weight_map 条数 == $EXPECT_TENSORS"
    printf '[VERDICT] S0: DRY-RUN —— 将校 18 shards / 字节结构 / 总字节 %s / %s 张量\n' \
      "$EXPECT_TOTAL" "$EXPECT_TENSORS"
    return 0
  fi

  [ -d "$HUHUI" ] || fatal "目录不存在：$HUHUI（下载还没落盘？）"
  [ -f "$HUHUI/model.safetensors.index.json" ] || fatal "缺 index：$HUHUI/model.safetensors.index.json"

  # ---- 1) shard 数
  local n
  n=$(ls "$HUHUI"/model-*-of-*.safetensors 2>/dev/null | wc -l | tr -dc '0-9')
  note "shards = ${n:-0}（期望 $EXPECT_SHARDS）"
  [ "${n:-0}" = "$EXPECT_SHARDS" ] || fatal "shard 数 ${n:-0} != $EXPECT_SHARDS（下载没完 / 少了分片）"

  # ---- 2) 逐 shard 字节结构 + 3) 总字节 + 4) 张量数（一个内嵌 python 全做完）
  if ! "$PY" - "$HUHUI" "$EXPECT_TOTAL" "$ALLOW_DRIFT" "$LOGS/s0-bytes.txt" "$EXPECT_TENSORS" <<'PY'
import glob, json, os, struct, sys

try:                                  # Windows 本地自测时控制台默认 cp936，中文会变乱码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

d, exp_total, allow_drift, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1", sys.argv[4]
exp_tensors = int(sys.argv[5])
files = sorted(glob.glob(os.path.join(d, "model-*-of-*.safetensors")))
lines, bad, total = [], 0, 0

lines.append("# S0 字节结构（口径：8 + header_len + max(data_offsets[1]) == filesize）")
for p in files:
    fs = os.path.getsize(p)
    total += fs
    try:
        with open(p, "rb") as f:
            raw = f.read(8)
            if len(raw) != 8:
                raise ValueError("文件 < 8 字节")
            hl = struct.unpack("<Q", raw)[0]
            if hl <= 0 or 8 + hl > fs:
                raise ValueError(f"header_len={hl} 越界（filesize={fs}）")
            hdr = json.loads(f.read(hl).decode("utf-8"))
        mx = 0
        for k, v in hdr.items():
            if k == "__metadata__":
                continue
            offs = v.get("data_offsets") or [0, 0]
            mx = max(mx, int(offs[1]))
        want = 8 + hl + mx
        ok = (want == fs)
        if not ok:
            bad += 1
        lines.append(("PASS " if ok else "FAIL ") + f"{os.path.basename(p)} file={fs} "
                     f"want={want} delta={fs - want} tensors={sum(1 for k in hdr if k != '__metadata__')}")
    except Exception as e:
        bad += 1
        lines.append(f"FAIL {os.path.basename(p)} file={fs} 解析失败：{type(e).__name__}: {e}")

lines.append(f"# 合计 shards={len(files)} bytes={total} expect={exp_total} delta={total - exp_total}")
t_ok = (total == exp_total)
lines.append(("PASS " if t_ok else "FAIL ") + f"total_bytes {total} vs {exp_total}")

idx_p = os.path.join(d, "model.safetensors.index.json")
if not os.path.isfile(idx_p):
    bad += 1
    lines.append(f"FAIL 缺 index：{idx_p}")
    nt = -1
else:
    idx = json.load(open(idx_p, encoding="utf-8"))
    wm = idx.get("weight_map") or {}
    nt = len(wm)
    lines.append(f"{'PASS' if nt == exp_tensors else 'FAIL'} weight_map={nt} expect={exp_tensors}")
    if nt != exp_tensors:
        bad += 1
    # 分片名自洽：index 里出现的分片文件名必须都能在盘上找到
    names = sorted({v for v in wm.values()})
    miss = [x for x in names if not os.path.isfile(os.path.join(d, x))]
    lines.append(f"{'PASS' if not miss else 'FAIL'} index 引用的分片 {len(names)} 个，缺 {len(miss)} 个"
                 + (f"：{miss[:5]}" if miss else ""))
    if miss:
        bad += 1

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
for ln in lines:
    print("  " + ln)

if bad:
    sys.exit(2)
if not t_ok:
    if allow_drift:
        print("  [WARN] 总字节不符，但 --allow-total-drift 放行（这条跑出来的产物不可信，"
              "只用于「先把链路跑通」）")
    else:
        print("  [FATAL] 总字节不符（半写/截断）。确认要放行请加 --allow-total-drift")
        sys.exit(2)
PY
  then
    fatal "S0 网络/结构校验 FAIL（逐行结果见 $LOGS/s0-bytes.txt）"
  fi

  local actual
  actual=$(awk '/^# 合计/{print $4}' "$LOGS/s0-bytes.txt" 2>/dev/null | tr -dc '0-9')
  printf '[VERDICT] S0: PASS —— %s shards · 实测总字节 %s（期望 %s）· %s 张量 · 结构全对\n' \
    "$EXPECT_SHARDS" "${actual:-?}" "$EXPECT_TOTAL" "$EXPECT_TENSORS"
}

# ===========================================================================
# S1 —— 硬指标（类名 / vision 归零 / trainable 数）
# ===========================================================================
stage_s1() {
  CUR_STAGE=S1
  say "S1 硬指标（要加载一次 27B，约 3-5 min）"
  gate "$(stage_need_gb s1)" "S1 前"

  if [ "$DRY" -eq 1 ]; then
    note "[dry] 将执行：$PY <内嵌脚本> --model $HUHUI --load $S1_LOAD"
    note "  检查 1  type(model).__name__ == $EXPECT_CLASS"
    note "  检查 2  named_modules 里含 visual/vision 的模块数 == 0"
    note "  检查 3  挂 LoRA（r16/a32/7 个 target，取自 train_kitty.py 的 TARGET_MODULES）后"
    note "          trainable params == $EXPECT_PARAMS"
    printf '[VERDICT] S1: DRY-RUN —— 将验 类名 / vision=0 / trainable=%s\n' "$EXPECT_PARAMS"
    return 0
  fi

  [ -f "$HUHUI/config.json" ] || fatal "缺 $HUHUI/config.json"

  "$PY" - "$HUHUI" "$S1_LOAD" "$KV/scripts/train_kitty.py" \
        "$EXPECT_CLASS" "$EXPECT_PARAMS" "$LOGS/s1-hard.txt" <<'PY' || fatal "S1 硬指标不合格（见 $LOGS/s1-hard.txt 与上面的 [FAIL] 行）"
import ast, json, os, sys, traceback

model_path, load_mode, tk_script, want_class, want_params, out_path = \
    sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6]
lines = []

def emit(s):
    print("  " + s, flush=True)
    lines.append(s)

def die(msg):
    emit("[FATAL] " + msg)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sys.exit(2)

# --- TARGET_MODULES 直接从 train_kitty.py 的 AST 里取：S1 与训练器不可能漂移
try:
    tree = ast.parse(open(tk_script, encoding="utf-8").read())
except Exception as e:
    die(f"读不到 {tk_script}: {e}")
targets = None
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TARGET_MODULES" for t in node.targets):
        targets = ast.literal_eval(node.value)
if not targets:
    die(f"{tk_script} 里没找到 TARGET_MODULES —— 训练器改了名，S1 口径会漂移")
emit(f"TARGET_MODULES ← train_kitty.py: {targets}")

import torch
from transformers import AutoModelForCausalLM

emit(f"加载 {model_path}（mode={load_mode}）")
try:
    if load_mode == "4bit":
        from transformers import BitsAndBytesConfig
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                 bnb_4bit_use_double_quant=True,
                                 bnb_4bit_compute_dtype=torch.bfloat16)
        model = AutoModelForCausalLM.from_pretrained(
            model_path, quantization_config=bnb, device_map={"": 0})
    else:
        model = AutoModelForCausalLM.from_pretrained(
            model_path, dtype=torch.bfloat16, device_map="cpu", low_cpu_mem_usage=True)
except Exception as e:
    traceback.print_exc()
    die(f"from_pretrained 失败（{type(e).__name__}: {e}）")

# --- 检查 1：类名
cls = type(model).__name__
arch = (getattr(model.config, "architectures", None) or [])
emit(f"检查1 class={cls}  config.architectures={arch}")
if cls != want_class:
    die(f"类名不是 {want_class}，而是 {cls} —— 加载走了别的分支（VL 包装？），v4 与 v3 不可比")

# --- 检查 2：vision 归零
names = [n for n, _ in model.named_modules()]
vis = [n for n in names if "visual" in n or "vision" in n]
emit(f"检查2 vision/visual 模块数 = {len(vis)}")
if vis:
    die(f"vision 没排掉：{len(vis)} 个（前 5：{vis[:5]}）—— text tower 之外的权重会被 LoRA 误挂")

# --- 检查 3：trainable params
from peft import LoraConfig, get_peft_model
ends = [n for n in names if any(n.endswith("." + t) for t in targets)]
emit(f"      peft 后缀匹配到的模块数 = {len(ends)}")
try:
    pm = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                                          bias="none", task_type="CAUSAL_LM",
                                          target_modules=targets))
except Exception as e:
    traceback.print_exc()
    die(f"get_peft_model 失败（{type(e).__name__}: {e}）")
tr = [p for p in pm.parameters() if p.requires_grad]
n_param = sum(p.numel() for p in tr)
emit(f"检查3 trainable tensors={len(tr)} params={n_param}  expect={want_params}")
if n_param != want_params:
    from collections import Counter
    agg = Counter()
    for n_, p_ in pm.named_parameters():
        if p_.requires_grad:
            agg[".".join(n_.split(".")[-2:])] += p_.numel()
    for k, v in sorted(agg.items()):
        emit(f"      {k:28s} {v}")
    die(f"trainable {n_param} != {want_params}（差 {n_param - want_params:+d}）—— "
        f"v3/v4 不可比，必须先查清是 LoRA 挂错还是结构变了")

emit(f"PASS class={cls} vision=0 trainable={n_param}")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
PY

  printf '[VERDICT] S1: PASS —— %s · vision=0 · trainable=%s\n' "$EXPECT_CLASS" "$EXPECT_PARAMS"
}

# ===========================================================================
# S2 —— base-only 基线（不带 adapter）
# ===========================================================================
stage_s2() {
  CUR_STAGE=S2
  say "S2 base-only 基线"
  gate "$(stage_need_gb s2)" "S2 前"

  if [ "$SKIP_BASE" -eq 1 ]; then
    red "[SKIP] S2 被 --skip-baseline 跳过：本次没有 re_pass / bench_f1 / refusal_rate 三个基线数，"
    red "       训练后只能与 v3 比，不能与「Huihui 本体」比（三组对照的 C 组缺一半）"
    printf '[VERDICT] S2: SKIP —— --skip-baseline\n'
    return 0
  fi

  local st
  st=$(port_state "$PORT")

  if [ "$DRY" -eq 1 ]; then
    note "[dry] 端口 $PORT 现状 = $st（真跑时 busy 会 FATAL）"
    note "[dry] 将执行："
    note "  起服务（不带 --adapter，这是 base-only 的关键）："
    note "    $PY $KV/scripts/serve_4bit_base.py --model $HUHUI --port $PORT --name huihui-base --thinking"
    note "  等 /v1/models 就绪（上限 300 s）"
    note "  $PY $KV/tmp/eval_bare.py --suite re60   --tools off --base http://127.0.0.1:$PORT --model huihui-base --out logs/base-only/re-eval.json"
    note "  $PY $KV/tmp/eval_bare.py --suite bench40              --base http://127.0.0.1:$PORT --model huihui-base --out logs/base-only/bench40.json"
    note "  $PY $KV/scripts/refusal_probe.py --mode text --base http://127.0.0.1:$PORT --model huihui-base --out logs/base-only/refusal-text.json"
    note "  汇总 → $LOGS/base-only-summary.json"
    printf '[VERDICT] S2: DRY-RUN —— 将跑 re60(60) / bench40(40) / refusal(text)，产物落 %s/logs/base-only/\n' "$R"
    return 0
  fi

  [ "$st" = "free" ] || fatal "端口 $PORT 已被占用：先停掉旧 serve（v3 的 serve 忘关会让基线跑在错的模型上）"
  [ -f "$KV/tmp/eval_bare.py" ] || fatal "缺 $KV/tmp/eval_bare.py（data-forge 的 wrapper 没上传）"
  [ -f "$KV/scripts/serve_4bit_base.py" ] || fatal "缺 $KV/scripts/serve_4bit_base.py"
  local outdir="$R/logs/base-only"
  mkdir -p "$outdir"
  rm -f "$outdir/serve.log"

  note "起服务 → $outdir/serve.log"
  "$PY" "$KV/scripts/serve_4bit_base.py" --model "$HUHUI" --port "$PORT" \
        --name huihui-base --thinking >>"$outdir/serve.log" 2>&1 &
  SERVER_PID=$!

  local i ready=0
  for i in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then ready=1; break; fi
    kill -0 "$SERVER_PID" 2>/dev/null || { tail_log "$outdir/serve.log" 30; fatal "serve 进程已退出（pid=$SERVER_PID）"; }
    sleep 5
  done
  [ "$ready" = 1 ] || { tail_log "$outdir/serve.log" 30; fatal "serve 在 300 s 内没就绪（http://127.0.0.1:$PORT/v1/models 不通）"; }
  note "serve 就绪（pid=$SERVER_PID）"
  curl -fsS "http://127.0.0.1:$PORT/v1/models" | tr -d '\n' | cut -c1-300; echo

  # --- re60（expect 判据，tools off：与 pick_checkpoint --tools-for kitty 同口径）
  note "跑 re60 …"
  "$PY" "$KV/tmp/eval_bare.py" --suite re60 --tools off \
        --base "http://127.0.0.1:$PORT" --model huihui-base \
        --out logs/base-only/re-eval.json --tag base-only \
    || fatal "re60 有异常行（eval_bare 返回非 0 = 有请求失败，均值不可信）"

  # --- bench40（固定 40 索引，ref 判据，训练后复跑同一批）
  note "跑 bench40 …"
  "$PY" "$KV/tmp/eval_bare.py" --suite bench40 \
        --base "http://127.0.0.1:$PORT" --model huihui-base \
        --out logs/base-only/bench40.json --tag base-only \
    || fatal "bench40 有异常行"

  # --- refusal 文本率（v4 的拒答率起点）
  note "跑 refusal(text) …"
  "$PY" "$KV/scripts/refusal_probe.py" --mode text \
        --base "http://127.0.0.1:$PORT" --model huihui-base \
        --out "$outdir/refusal-text.json" \
    || fatal "refusal_probe(text) 失败"

  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""

  # --- 汇总
  "$PY" - "$outdir" "$LOGS/base-only-summary.json" <<'PY' || fatal "基线产物缺失/不可解析（见上）"
import json, os, sys
d, outp = sys.argv[1], sys.argv[2]
def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)
need = ["re-eval.json", "bench40.json", "refusal-text.json"]
miss = [n for n in need if not os.path.isfile(os.path.join(d, n))]
if miss:
    print("  [FATAL] 缺产物：" + ", ".join(miss))
    sys.exit(2)
re_, b40, rp = (load(os.path.join(d, n)) for n in need)
s_re, s_b = re_.get("summary") or {}, b40.get("summary") or {}
txt = (rp.get("text") or {})
summ = {
    "re60":    {"n": s_re.get("n"), "pass": s_re.get("pass"),
                "pass_rate": s_re.get("pass_rate"), "n_err": s_re.get("n_err")},
    "bench40": {"n": s_b.get("n"), "mean_f1": s_b.get("mean_f1"),
                "mean_ref_recall": s_b.get("mean_ref_recall"), "n_err": s_b.get("n_err")},
    "refusal": {"n": txt.get("n"), "refused": txt.get("refused"),
                "refusal_rate": txt.get("refusal_rate")},
    "protocol": {"re60": re_.get("protocol"), "bench40": b40.get("protocol"),
                 "bench40_indices_fixed": b40.get("indices_fixed")},
}
with open(outp, "w", encoding="utf-8") as f:
    json.dump(summ, f, ensure_ascii=False, indent=2)
print("")
print("  ┌──────────────── base-only 基线 ────────────────")
print(f"  │ re60     : PASS {summ['re60']['pass']}/{summ['re60']['n']} "
      f"= {(summ['re60']['pass_rate'] or 0) * 100:.1f}%   异常 {summ['re60']['n_err']}")
print(f"  │ bench40  : mean_f1 {summ['bench40']['mean_f1']}  "
      f"recall {summ['bench40']['mean_ref_recall']}  n={summ['bench40']['n']}")
print(f"  │ refusal  : {summ['refusal']['refused']}/{summ['refusal']['n']} "
      f"= {(summ['refusal']['refusal_rate'] or 0) * 100:.1f}%")
print("  └────────────────────────────────────────────────")
print(f"  汇总 → {outp}")
PY

  local st2
  st2=$("$PY" -c "import json,sys;d=json.load(open(sys.argv[1]));a=d['re60'];b=d['bench40'];c=d['refusal'];print(f\"re {a['pass']}/{a['n']} ({a['pass_rate']}) · bench f1={b['mean_f1']} · refusal {c['refusal_rate']}\")" "$LOGS/base-only-summary.json")
  printf '[VERDICT] S2: PASS —— %s\n' "$st2"
}

# ===========================================================================
# S3 —— act-cache-v4（新目录，绝不复用 v3）
# ===========================================================================
stage_s3() {
  CUR_STAGE=S3
  say "S3 act-cache-v4"
  gate "$(stage_need_gb s3)" "S3 前"

  local dst="$KV/act-cache-v4"
  if [ "$DRY" -eq 1 ]; then
    note "[dry] 将执行："
    note "  前置：$dst 存在且非空 → FATAL（防 v3 缓存混用）"
    note "  cd $KV && $PY scripts/precompute_activations.py \\"
    note "        --model $HUHUI --cut 48 --ctx 512 \\"
    note "        --data data/large-mix-plus/train.jsonl --split-by-subsets data/subsets \\"
    note "        --out act-cache-v4"
    note "  后置：$EXPECT_ACT_DIRS 个目录 + .pt 总数 == $EXPECT_PT"
    note "  现状：$( [ -d "$dst" ] && echo "已存在（非空=$(find "$dst" -mindepth 1 -maxdepth 1 2>/dev/null | head -1 | wc -l | tr -dc '0-9')）" || echo "不存在" )"
    printf '[VERDICT] S3: DRY-RUN —— 将生成 %s 个 .pt 到 %s\n' "$EXPECT_PT" "$dst"
    return 0
  fi

  # 先判缓存混用（这条最要紧：v3 缓存混进来会训出「loss 正常、能力没长」的模型）
  if [ -d "$dst" ] && [ -n "$(find "$dst" -mindepth 1 -maxdepth 1 2>/dev/null | head -1)" ]; then
    fatal "act-cache-v4 已存在且非空：$dst
        缓存与 base 逐比特绑定，v3/v4 混用会训出「loss 正常、能力没长」的模型。
        要重算请先人工确认后 rm -rf $dst（脚本不替你删数据）"
  fi

  [ -f "$KV/data/large-mix-plus/train.jsonl" ] || fatal "缺 $KV/data/large-mix-plus/train.jsonl"
  [ -d "$KV/data/subsets" ] || fatal "缺 $KV/data/subsets"
  [ -f "$KV/scripts/precompute_activations.py" ] || fatal "缺 precompute_activations.py"
  if [ -d "$KV/act-cache" ]; then
    note "注意：$KV/act-cache（v3 的）在，但本步只写 act-cache-v4，不会碰它"
  fi

  ( cd "$KV" && "$PY" scripts/precompute_activations.py \
      --model "$HUHUI" --cut 48 --ctx 512 \
      --data data/large-mix-plus/train.jsonl --split-by-subsets data/subsets \
      --out act-cache-v4 ) || fatal "precompute_activations.py 失败"

  local nd npt
  nd=$(find "$dst" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -dc '0-9')
  npt=$(find "$dst" -name '*.pt' | wc -l | tr -dc '0-9')
  note "目录 $nd（期望 $EXPECT_ACT_DIRS）· .pt $npt（期望 $EXPECT_PT）"
  [ "$nd" = "$EXPECT_ACT_DIRS" ] || fatal "act-cache-v4 目录数 $nd != $EXPECT_ACT_DIRS（分类切片没落全）"
  [ "$npt" = "$EXPECT_PT" ] || fatal "act-cache-v4 的 .pt 数 $npt != $EXPECT_PT（少一条都会让本地增量训练样本数不对）"
  [ -f "$dst/manifest.json" ] || fatal "缺 $dst/manifest.json（没有它无法证明缓存来自哪个 base）"

  printf '[VERDICT] S3: PASS —— %s 目录 / %s .pt / manifest 在\n' "$nd" "$npt"
}

# ===========================================================================
# S4 —— 开训（setsid nohup + 分段自检）
# ===========================================================================
stage_s4() {
  CUR_STAGE=S4
  say "S4 开训（3 epoch / 735 step 量级 / 约 6 h）"
  gate "$(stage_need_gb s4)" "S4 前"

  local cmd=("$PY" scripts/train_kitty.py --size 27b --stage sft
             --base "$HUHUI" --text-only
             --data data/large-mix-plus/train.jsonl
             --ctx 2048 --bs 1 --ga 16 --epochs 3 --lr 2e-4
             --lora-r 16 --lora-alpha 32 --all-gpu --out out-v4
             --dl-workers 4 --pin-memory --prefetch 2)
  if [ "$TRAIN_MAX_STEPS" -gt 0 ] 2>/dev/null; then
    cmd+=(--max-steps "$TRAIN_MAX_STEPS")
  fi

  if [ "$DRY" -eq 1 ]; then
    note "[dry] 将执行（cwd=$KV，日志 $LOGS/train.log，setsid nohup 脱离终端）："
    note "  setsid nohup $(printf '%q ' "${cmd[@]}")> $LOGS/train.log 2>&1 < /dev/null &"
    note "自检 A 段 0..${TRAIN_SELFCHECK_S}s：进程活 + 日志无 Traceback"
    note "自检 B 段 ${TRAIN_SELFCHECK_S}..${TRAIN_START_TIMEOUT_S}s：显存 >${GPU_MIN_USED}MiB 且日志出现 loss/step"
    note "开跑前 GPU 空闲闸门：free ≥ ${GPU_MIN_FREE} MiB（当前 free=$(gpu_free_mib) MiB）"
    printf '[VERDICT] S4: DRY-RUN —— 将起 27B QLoRA（3ep/ctx2048/bs1/ga16/r16/a32）\n'
    return 0
  fi

  [ -f "$KV/scripts/train_kitty.py" ] || fatal "缺 $KV/scripts/train_kitty.py"
  [ -f "$KV/data/large-mix-plus/train.jsonl" ] || fatal "缺训练数据 $KV/data/large-mix-plus/train.jsonl"

  local free; free=$(gpu_free_mib)
  if [ -n "$free" ]; then
    if [ "$free" -lt "$GPU_MIN_FREE" ]; then
      fatal "GPU 只剩 ${free} MiB 空闲（< ${GPU_MIN_FREE}）——S2 的 serve 没关？先 nvidia-smi 看占用"
    fi
    note "GPU free=${free} MiB ✓"
  else
    warn "nvidia-smi 不可用：跳过开跑前显存闸门（训练仍可能 OOM）"
  fi

  mkdir -p "$LOGS"
  : >"$LOGS/train.log"
  ( cd "$KV" && setsid nohup "${cmd[@]}" >"$LOGS/train.log" 2>&1 </dev/null & echo $! >"$LOGS/train.pid" )
  local pid; pid=$(cat "$LOGS/train.pid" 2>/dev/null || echo "")
  [ -n "$pid" ] || fatal "没拿到训练 pid（见 $LOGS/train.log）"
  note "训练已起：pid=$pid · 日志 $LOGS/train.log"
  disown -a 2>/dev/null || true   # setsid 已脱离会话，disown 只是双保险

  # ---- 自检 A：进程活 + 不炸
  local t=0 used="" hit_trace=0
  while [ "$t" -lt "$TRAIN_SELFCHECK_S" ]; do
    kill -0 "$pid" 2>/dev/null || {
      tail_log "$LOGS/train.log" 30
      fatal "训练进程 ${t}s 内已退出（pid=$pid）"
    }
    if grep -qE 'Traceback|[FATAL]|CUDA out of memory' "$LOGS/train.log" 2>/dev/null; then
      hit_trace=1; break
    fi
    if [ "$STRICT_90S_GPU" = 1 ]; then
      used=$(gpu_used_mib)
      if [ -n "$used" ] && [ "$used" -ge "$GPU_MIN_USED" ]; then break; fi
    fi
    sleep 5; t=$((t + 5))
  done
  if [ "$hit_trace" = 1 ]; then
    tail_log "$LOGS/train.log" 30
    fatal "日志里出现 Traceback/FATAL/OOM（前 ${t}s）"
  fi
  note "A 段（${t}s）：进程活 ✓$( [ "$STRICT_90S_GPU" = 1 ] && echo " · 显存 $(gpu_used_mib) MiB" )"

  # ---- 自检 B：显存起来 + 出 step/loss
  local deadline=$((t + TRAIN_START_TIMEOUT_S)) ok=0
  while [ "$t" -lt "$deadline" ]; do
    kill -0 "$pid" 2>/dev/null || { tail_log "$LOGS/train.log" 30; fatal "训练进程在等待 step 期间退出"; }
    used=$(gpu_used_mib)
    if grep -qE "'loss'|\"loss\"|s/it|[0-9]+/[0-9]+ \[" "$LOGS/train.log" 2>/dev/null; then
      if [ -z "$used" ] || [ "$used" -ge "$GPU_MIN_USED" ]; then ok=1; break; fi
    fi
    sleep 5; t=$((t + 5))
  done
  if [ "$ok" != 1 ]; then
    tail_log "$LOGS/train.log" 30
    printf '  nvidia-smi memory.used = %s MiB\n' "${used:-N/A}"
    fatal "自检失败：${deadline}s 内没看到「显存 >${GPU_MIN_USED}MiB 且日志出现 loss/step」"
  fi

  printf '[VERDICT] S4: PASS —— 已起训 · pid=%s · 显存 %s MiB · 日志 %s\n' \
    "$pid" "${used:-N/A}" "$LOGS/train.log"
  # 训练脚本自己会打 [S1] trainable=...（判据③的证词要在训练日志里，不能只在审计输出里）
  local tr_line
  tr_line=$(grep -m1 '\[S1\] trainable=' "$LOGS/train.log" 2>/dev/null || true)
  if [ -n "$tr_line" ]; then
    note "训练脚本自报：$tr_line"
    case "$tr_line" in
      *"trainable=$EXPECT_PARAMS"*) : ;;
      *) fatal "训练日志里的 trainable 与 $EXPECT_PARAMS 不符：$tr_line" ;;
    esac
  fi
  note "盯训练：tail -f $LOGS/train.log"
  note "停训练：kill $pid"
}

# ---------------------------------------------------------------- 主流程 ----
if [ "$STAGE" = "all" ]; then
  stage_s0
  stage_s1
  stage_s2
  stage_s3
  stage_s4
  if [ "$DRY" -eq 1 ]; then
    printf '\n[VERDICT] ALL: DRY-RUN —— 五段命令与四个闸门如上；去掉 --dry-run 才真执行\n'
  else
    say "全链通过"
    printf '[VERDICT] ALL: PASS —— S0/S1/S2/S3/S4 全过；训练在后台跑，日志 %s\n' "$LOGS/train.log"
  fi
else
  "stage_$STAGE"
  say "单阶段 $STAGE 结束"
fi

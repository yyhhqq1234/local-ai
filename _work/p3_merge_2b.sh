#!/usr/bin/env bash
# P3：把门控腿 adapter（2b-nsfw-final）merge 进 bf16 基座 + pin architectures + 核对
#
# 背景
#   PLAN §6.1 的坑：merge 后不 pin architectures，convert 会走 VL 分支
#   方案 Z 是双 adapter 分离，各自 merge 成独立成品，不合并成一份
#   本脚本只 merge 门控腿（磁盘 96 GB 可用，一份 18 GB；三份 54 GB 会超）
#
# 关键点
#   2b-nsfw-final 是用 --init-adapter z-2a-v7 训出来的 → 它本身就是「z-2a-v7 + 400步nsfw」的累积权重
#   （不是增量），所以直接 merge 到 base 就得到完整的门控腿成品
set -u
cd "$(dirname "$0")/.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out; M=train/lines/9b-oxcoder/models
AD="$OUT/2b-nsfw-final"
DST="$M/merged-2b-nsfw"
LOG="$L/p3-merge-2b.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ P3 merge（门控腿）启动 ================"
df -h /d | tail -1 | tee -a "$LOG"
log "adapter = $AD"
log "dest    = $DST"

if [ ! -f "$AD/adapter_model.safetensors" ]; then
  log "★ adapter 缺失 → 中止"; exit 1
fi
if ls "$DST"/*.safetensors >/dev/null 2>&1; then
  log "目标已存在 → 跳过 merge（如需重跑先删 $DST）"
else
  mkdir -p "$DST"
  log "开始 merge（分片级，RAM<6GB，预计 10–20 min）…"
  "$PY" train/lines/_shared/scripts/local_merge_lora.py \
      --base "$M/OxCoder-9B" --adapter "$AD" --out "$DST" >> "$LOG" 2>&1
  rc=$?
  log "merge 退出 rc=$rc"
  [ $rc -ne 0 ] && { log "★ merge 失败，看 $LOG"; exit $rc; }
fi

# pin architectures（PLAN §6.1 的 VL 分支坑）
"$PY" - "$DST" <<'PYEOF' >> "$LOG" 2>&1
import json, os, sys
d = sys.argv[1]
p = os.path.join(d, "config.json")
if os.path.exists(p):
    c = json.load(open(p, encoding="utf-8"))
    c["architectures"] = ["Qwen3_5ForConditionalGeneration"]
    json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[pin] {d} architectures={c['architectures']}")
else:
    print(f"[pin] 缺 {p}")
PYEOF

log "=== 产物核对（PLAN §6.1 判据）==="
sz=$(du -sh "$DST" 2>/dev/null | cut -f1)
n=$(ls "$DST"/*.safetensors 2>/dev/null | wc -l)
log "体积: ${sz:-NA}   （判据 ≈18.8 GB）"
log "分片数: $n"

"$PY" - "$DST" <<'PYEOF' >> "$LOG" 2>&1
import json, os, sys, glob
d = sys.argv[1]
c = json.load(open(os.path.join(d, "config.json"), encoding="utf-8"))
print(f"architectures = {c.get('architectures')}   （判据 ['Qwen3_5ForConditionalGeneration']）")
print(f"model_type    = {c.get('model_type')}")
print(f"torch_dtype   = {c.get('torch_dtype')}")
try:
    from safetensors import safe_open
    total = 0
    for f in sorted(glob.glob(os.path.join(d, "*.safetensors"))):
        with safe_open(f, framework="pt") as fh:
            total += len(list(fh.keys()))
    print(f"张量总数 = {total}   （判据 760）")
except Exception as e:
    print(f"张量统计失败: {e}")
for f in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja"):
    p = os.path.join(d, f)
    print(f"{f}: {'✅' if os.path.exists(p) else '✗ 缺'}")
PYEOF

log "================ P3 merge 结束 ================"
log "成品：$DST"

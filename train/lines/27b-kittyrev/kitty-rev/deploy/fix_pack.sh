#!/usr/bin/env bash
# fix_pack.sh —— 解包 kittyrev-local-pack.tar 并补齐缺失的 config.json
#
# 背景（2026-10-22 audit-fix-2 真机实测）：
#   pack 里的 merged-layers/ 只有 16 层 + head + layers_index.json，
#   **缺 config.json**，而 train_partial_lora 的 SplitSource 第一句就查它
#   → 直接 [FATAL] 缺少 config.json
#
# 本脚本：解包 → 从 base 拷 config.json + tokenizer 附属文件 → 校验 → 打印可训命令
#
# 用法：
#   bash fix_pack.sh            # 解包到 ../local-pack/ 并修复
#   bash fix_pack.sh --check    # 只检查，不解包
set -uo pipefail
cd "$(dirname "$0")"

PACK="$(cd .. && pwd)/local-pack/kittyrev-local-pack.tar"
DEST="$(cd .. && pwd)/local-pack"
# 2026-10-22：v3 的 base 权重已删（省 52 G），元数据副本留在 deploy/base-meta/
BASE="${BASE:-$(pwd)/base-meta}"
[ -d "$BASE" ] || BASE="$(cd .. && pwd)/base/Qwen3.8-27B"   # 兼容老环境

say() { echo; echo "===== $* ====="; }

if [ "${1:-}" = "--check" ]; then
  say "检查"
  [ -f "$PACK" ] && echo "  pack      OK  $(du -h "$PACK" | cut -f1)" || echo "  pack      MISSING $PACK"
  [ -f "$BASE/config.json" ] && echo "  base cfg  OK  $(wc -c < "$BASE/config.json") B" || echo "  base cfg  MISSING $BASE/config.json"
  if [ -f "$DEST/merged-layers/config.json" ]; then
    echo "  pack cfg  OK（已修复过）"
  else
    echo "  pack cfg  MISSING（需要解包后补）"
  fi
  exit 0
fi

say "① 解包（25 G，约 2-3 分钟）"
if [ ! -d "$DEST/merged-layers" ]; then
  tar -xf "$PACK" -C "$DEST" || { echo "[FATAL] 解包失败"; exit 1; }
else
  echo "[skip] $DEST/merged-layers 已存在"
fi

say "② 补 config.json + tokenizer"
for f in config.json tokenizer.json tokenizer_config.json generation_config.json; do
  if [ -f "$BASE/$f" ]; then
    if [ ! -f "$DEST/merged-layers/$f" ]; then
      cp "$BASE/$f" "$DEST/merged-layers/$f" && echo "  + $f"
    else
      echo "  = $f 已存在"
    fi
  else
    echo "  ! $BASE/$f 不存在，跳过"
  fi
done

say "③ 校验"
python - <<'PY'
import json, os, glob, sys
D = os.path.join(os.path.dirname(os.path.abspath(".")), "local-pack", "merged-layers")
D = os.path.abspath(D)
ok = True
cfg = os.path.join(D, "config.json")
if os.path.isfile(cfg):
    c = json.load(open(cfg))
    print(f"  config.json     OK  arch={c.get('architectures')} hidden={c.get('hidden_size')} layers={c.get('num_hidden_layers')}")
else:
    print("  config.json     MISSING"); ok = False
n = len(glob.glob(os.path.join(D, "layer_*.safetensors")))
print(f"  layer files     {n}/16 {'OK' if n==16 else 'FAIL'}")
for name in ("head.safetensors", "layers_index.json"):
    p = os.path.join(D, name)
    print(f"  {name:15s} {'OK' if os.path.isfile(p) else 'MISSING'}")
    if not os.path.isfile(p): ok = False
ac = os.path.abspath(os.path.join(D, "..", "act-cache"))
if os.path.isdir(ac):
    dirs = sorted(os.listdir(ac))
    total = sum(len(glob.glob(os.path.join(ac, d, "*.pt"))) for d in dirs if os.path.isdir(os.path.join(ac, d)))
    print(f"  act-cache       {len(dirs)} 目录 / {total} 个 .pt {'OK' if total==4388 else 'FAIL(期望 4388)'}")
else:
    print("  act-cache       MISSING"); ok = False
sys.exit(0 if ok else 1)
PY
RC=$?

say "④ 可训命令（audit-fix-2 真机实测：峰值 5.91 GiB / 2 s·step）"
cat <<'CMD'
cd D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev
../.venv/Scripts/python.exe scripts/train_partial_lora.py \
  --layer-dir ../local-pack/merged-layers --from 48 --to 63 \
  --ctx 512 --bs 1 --ga 8 --lora-r 16 --lora-alpha 32 --lr 5e-5 \
  --data-mix "re-train:../local-pack/act-cache/re-train:4,forge-train:../local-pack/act-cache/forge-train:4,route-train:../local-pack/act-cache/route-train:2,discipline-train:../local-pack/act-cache/discipline-train:2,gen-train:../local-pack/act-cache/gen-train:1,rest:../local-pack/act-cache/rest:1" \
  --eval-cache "re-val:../local-pack/act-cache/re-val:2,forge-val:../local-pack/act-cache/forge-val:1,route-val:../local-pack/act-cache/route-val:1,discipline-val:../local-pack/act-cache/discipline-val:1,gen-val:../local-pack/act-cache/gen-val:1" \
  --eval-by-cat --eval-every 10 --early-stop-patience 3 \
  --max-steps 200 --max-vram-gb 10.5 --save-every 50 \
  --out ../local-pack/out-lora
CMD

say "结果"
if [ $RC -eq 0 ]; then echo "  ✓ 全部就绪，可以训练"; else echo "  ✗ 校验 FAIL（看上面哪项 MISSING）"; fi
exit $RC

#!/usr/bin/env bash
# remote_clean.sh —— 云端环境排障清理（只删中间件/残留，不动交付物）
# 用法：bash remote_clean.sh [--dry]
set -uo pipefail
DRY=${1:-}
R=/root/autodl-tmp
K=$R/kitty-rev
say(){ echo "[clean] $*"; }
run(){ if [ "$DRY" = "--dry" ]; then echo "  (dry) $*"; else eval "$*"; fi }

say "=== 1. 杀残留进程 ==="
for pat in 'curl -fsSL' 'curl -fL' 'aria2c' 'convert_hf_to_gguf' 'merge.py' 'llama-quantize' 'llama-imatrix'; do
  pids=$(pgrep -f "$pat" 2>/dev/null | tr '\n' ' ')
  [ -n "$pids" ] && { say "kill [$pat] -> $pids"; run "kill -9 $pids 2>/dev/null"; }
done
run "screen -ls | awk '/Detached/{print \$1}' | xargs -r -I{} screen -S {} -X quit 2>/dev/null"

say "=== 2. 删残留中间件 ==="
run "rm -rf $R/base-hf/*.aria2 $R/base-hf/Huihui/c16.* $R/sh2 $R/shardout $R/sp $R/testbig $R/big40"
run "rm -rf $K/gguf/v4-bf16.gguf.partial $K/tmpwork/*"
run "rm -f /tmp/part_0* /tmp/t16a /tmp/p1.bin /tmp/probe.bin /tmp/_hf_files.txt"
run "find $R -maxdepth 2 -name '*.aria2' -delete"

say "=== 3. 现状（只读） ==="
df -h $R | tail -1
du -sh $R/* 2>/dev/null | sort -rh | head -8
say "--- 关键产物 ---"
for p in "$K/gguf/v4-bf16.gguf" "$R/merged-v4" "$K/kitty-rev/out-v4/adapter"; do
  [ -e "$p" ] && echo "  OK  $p  $(du -sh "$p" 2>/dev/null | cut -f1)" || echo "  MISS $p"
done
say "--- merged-v4 的 GDN 零张量快检（应 >0 才说明这版 merge 是坏的）---"
[ -d "$R/merged-v4" ] && /root/miniconda3/bin/python - <<'PY'
import glob
from safetensors import safe_open
z=0; t=0
for p in sorted(glob.glob('/root/autodl-tmp/merged-v4/*.safetensors'))[:3]:
    with safe_open(p, framework='pt') as f:
        for k in list(f.keys()):
            if 'linear_attn' in k:
                x=f.get_tensor(k)
                t+=1
                if float(x.abs().max())==0.0: z+=1
print(f"  linear_attn 抽检 {t} 个，其中全零 {z} 个")
PY
say "=== 4. 进程复核（应为空） ==="
ps -eo args | grep -E "[c]url|[a]ria2c|[c]onvert_hf|[m]erge.py|[l]lama-" | head -5 || echo "  none"

cd /root/autodl-tmp/kitty-rev
echo "=== 1 ????? ==="
while pgrep -f "llama-quantize" > /dev/null; do sleep 20; done
SZ=$(stat -c %s gguf/v61-iq2s-fix.gguf 2>/dev/null || echo 0)
MG=$(head -c 4 gguf/v61-iq2s-fix.gguf 2>/dev/null | xxd -p)
echo "QUANT_DONE size=$SZ magic=$MG"
echo "=== 2 ?????ssm?==="
/root/miniconda3/bin/python -c "
from gguf import GGUFReader
r = GGUFReader('gguf/v61-iq2s-fix.gguf')
want = {}
for t in r.tensors:
    n = t.name
    if 'ssm_alpha' in n or 'ssm_beta' in n or n.endswith('ssm_a') or n.endswith('ssm_dt.bias'):
        k = 'alpha/beta' if ('alpha' in n or 'beta' in n) else ('ssm_a' if n.endswith('ssm_a') else 'ssm_dt')
        want.setdefault(k, t.tensor_type.name)
print('TYPES', want)
"
echo "=== 3 splice ==="
/root/miniconda3/bin/python tools/splice_new.py --base gguf/v61-iq2s-fix.gguf --ref /root/autodl-tmp/ref/ref_sparse.gguf --out gguf/v61-mtp2.gguf --prefix blk.64. > logs/v6/SPLICE-V61-2.log 2>&1
echo "SPLICE_RC=$?"
tail -2 logs/v6/SPLICE-V61-2.log
echo "=== 4 convert ==="
cd /root/autodl-tmp/kitty-rev/ninfer-all-master
/root/miniconda3/bin/python -m tools.convert --model /root/autodl-tmp/kitty-rev/cfg-vision --recipe qwen3_8_27b_gguf --source gguf=/root/autodl-tmp/kitty-rev/gguf/v61-mtp2.gguf --source vision=/root/autodl-tmp/kitty-rev/gguf/v5-mmproj-q8.gguf --components text,vision,mtp --proposal --proposal-rows 131072 --name qwen3.8-27b-kittyrev-v61-iq2s-mtp --out /root/autodl-tmp/kitty-rev/ninfer-v61/qwen3.8-27b-kittyrev-v61-iq2s-mtp.ninfer > /root/autodl-tmp/kitty-rev/logs/v6/CONVERT-V61-2.log 2>&1
echo "CONVERT_RC=$?"
tail -4 /root/autodl-tmp/kitty-rev/logs/v6/CONVERT-V61-2.log | cut -c1-140
echo "=== 5 ?? ==="
ls -l /root/autodl-tmp/kitty-rev/ninfer-v61/*.ninfer 2>/dev/null | awk '{print $5, $9}'
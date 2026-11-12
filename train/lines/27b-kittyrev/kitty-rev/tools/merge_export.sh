#!/usr/bin/env bash
# merge_export.sh —— merge(base+adapter) → 官方通道导出 bf16 → 判据九数值对账
# 纪律：不使用任何写补丁；导出一律官方 convert_hf_to_gguf.py --use-temp-file --no-lazy
set -uo pipefail
R=/root/autodl-tmp/kitty-rev
BASE=/root/autodl-tmp/base-hf/Huihui
ADP=$R/kitty-rev/out-v4/adapter
MERGED=/root/autodl-tmp/merged-v4
OUT=$R/gguf/v4-bf16-o.gguf
LOG=$R/logs/v4/MERGE-EXPORT.log
PY=/root/miniconda3/bin/python
export OMP_NUM_THREADS=48

log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

log "===== merge_export start ====="
# G1 基座齐
n=$(ls "$BASE"/*.safetensors 2>/dev/null | wc -l)
sz=$(du -sb "$BASE" | cut -f1)
log "[G1] base shards=$n bytes=$sz"
[ "$n" -eq 18 ] || { log "[STOP] 基座片数 $n != 18"; exit 1; }

# G2 merge
if [ ! -f "$MERGED/config.json" ] || [ "$(ls "$MERGED"/*.safetensors 2>/dev/null | wc -l)" -lt 12 ]; then
  rm -rf "$MERGED"
  log "[G2] merge start"
  $PY "$R/kitty-rev/scripts/merge.py" --size 27b --base "$BASE" --adapter "$ADP" --dest "$MERGED" >>"$LOG" 2>&1
  rc=$?
  [ $rc -eq 0 ] || { log "[STOP] merge rc=$rc"; exit 1; }
fi
n=$(ls "$MERGED"/*.safetensors 2>/dev/null | wc -l)
log "[G2] PASS shards=$n bytes=$(du -sb "$MERGED" | cut -f1)"

# G3 官方导出
rm -f "$OUT"
export TMPDIR=/root/autodl-tmp/tmpwork; mkdir -p "$TMPDIR"
log "[G3] official export start (--use-temp-file --no-lazy)"
$PY /root/autodl-tmp/lc/convert_hf_to_gguf.py "$MERGED" --outtype bf16 --outfile "$OUT" --use-temp-file --no-lazy >>"$LOG" 2>&1
rc=$?
[ $rc -eq 0 ] || { log "[STOP] export rc=$rc"; exit 1; }
log "[G3] export done bytes=$(stat -c%s "$OUT")"

# G4 判据九：数值对账（GGUF vs HF 源，行/列/转置四式）
log "[G4] judge9 start"
$PY - "$OUT" "$MERGED" <<'PY' 2>&1 | tee -a "$LOG"
import sys, numpy as np, glob, mmap
sys.path.insert(0,"/root/autodl-tmp/lc/gguf-py")
from gguf import GGUFReader
from safetensors import safe_open
gpath, mdir = sys.argv[1], sys.argv[2]
r=GGUFReader(gpath); d={t.name:t for t in r.tensors}
def gv(name,k=8):
    t=d[name]
    if int(t.tensor_type)==30:
        raw=np.frombuffer(t.data.tobytes(),dtype=np.uint16)[:k]
        return (raw.astype(np.uint32)<<16).view(np.float32)
    if int(t.tensor_type)==1:
        return np.frombuffer(t.data.tobytes(),dtype=np.float16)[:k].astype(np.float32)
    if int(t.tensor_type)==0:
        return np.frombuffer(t.data.tobytes(),dtype=np.float32)[:k]
    return None
idx={}
for f in glob.glob(mdir+"/*.safetensors"):
    with safe_open(f,framework="pt") as sf:
        for k in sf.keys(): idx[k]=f
def hfv(key,k=8):
    with safe_open(idx[key],framework="pt") as sf:
        return sf.get_tensor(key).float().numpy()
checks=[("blk.48.ffn_down.weight","model.language_model.layers.48.mlp.down_proj.weight"),
        ("blk.60.ffn_up.weight","model.language_model.layers.60.mlp.up_proj.weight"),
        ("blk.50.attn_qkv.weight",None)]
ok_all=0; tot=0
for gn,hn in checks:
    if hn is None or hn not in idx:
        print(f"  [skip] {gn} (no hf key)"); continue
    g=gv(gn)
    if g is None: print(f"  [skip] {gn} 类型非 bf16/f16/f32"); continue
    w=hfv(hn)
    cands={"row":w.reshape(w.shape[0],-1)[0,:len(g)] if w.ndim==2 else w[:len(g)],
           "col":w.reshape(w.shape[0],-1)[:len(g),0] if w.ndim==2 else None,
           "T":w.reshape(w.shape[0],-1).T[0,:len(g)] if w.ndim==2 else None}
    hit=[k for k,v in cands.items() if v is not None and np.allclose(g,v,atol=1e-2)]
    tot+=1; ok_all+= 1 if hit else 0
    print(f"  {gn}: gguf[:4]={[round(float(x),6) for x in g[:4]]} hit={hit or 'NONE'}")
print(f"[judge9] {ok_all}/{tot} 张量数值对上（四式任一模）")
sys.exit(0 if (tot>0 and ok_all==tot) else 2)
PY
rc=$?
[ $rc -eq 0 ] || { log "[STOP] 判据九 FAIL"; exit 1; }
log "[G4] PASS 判据九"
log "===== merge_export DONE ====="

#!/bin/bash
# finish14c.sh — 不完整段整段重下（覆盖），再拼接 + 结构校验。
# 上一版用 `-r rs-e --append -o` 无效（346 s 零增长）：curl 的 --append 不作用于 HTTP range 续写。
set -u

BASE=/root/autodl-tmp/kitty-rev/base/Huihui
F=model-00014-of-00018.safetensors
URL=https://hf-mirror.net/huihui-ai/Huihui-Qwen3.8-27B-abliterated/resolve/main/model-00014-of-00018.safetensors
TOTAL=3979553664
PARTS=$BASE/_parts14
PAR=${PAR:-6}
SEGS=/tmp/segs14.txt

cd "$BASE" || exit 1

echo "=== [1] inventory ==="
bad_list=""
while read -r i s e n; do
  f="$PARTS/part-$(printf '%04d' "$i")"
  got=$(stat -c %s "$f" 2>/dev/null || echo 0)
  [ "$got" -ne "$n" ] && bad_list="$bad_list $i"
done < "$SEGS"
echo "  incomplete segs:$bad_list"

[ -z "$bad_list" ] && echo "  (none)" || echo "  count=$(echo $bad_list | wc -w)"

getseg_full() {
  i="$1"; s="$2"; e="$3"; n="$4"
  f="$PARTS/part-$(printf '%04d' "$i")"
  got=$(stat -c %s "$f" 2>/dev/null || echo 0)
  [ "$got" -eq "$n" ] && return 0
  for try in 1 2 3; do
    rm -f "$f"
    curl -sS -L --connect-timeout 15 --max-time 240 -r "$s-$e" -o "$f" "$URL" 2>/dev/null
    got=$(stat -c %s "$f" 2>/dev/null || echo 0)
    [ "$got" -eq "$n" ] && { echo "[ok] seg $i $got"; return 0; }
    echo "[retry $try] seg $i got=$got want=$n"
    sleep 3
  done
  echo "[BAD] seg $i final=$got want=$n"
  return 1
}
export -f getseg_full
export PARTS URL

echo "=== [2] re-download incomplete segments (full range) ==="
t0=$(date +%s)
awk -v bad="$bad_list" 'BEGIN{n=split(bad,a," "); for(k=1;k<=n;k++) want[a[k]]=1} want[$1]{print $1,$2,$3,$4}' "$SEGS" \
  | xargs -r -P "$PAR" -n 4 bash -c 'getseg_full "$@"' _
t1=$(date +%s); dt=$((t1-t0)); [ "$dt" -lt 1 ] && dt=1
echo "  elapsed=${dt}s"

echo "=== [3] verify ==="
bad=0
while read -r i s e n; do
  f="$PARTS/part-$(printf '%04d' "$i")"
  got=$(stat -c %s "$f" 2>/dev/null || echo 0)
  [ "$got" -eq "$n" ] || { echo "  BAD seg $i $got/$n"; bad=$((bad+1)); }
done < "$SEGS"
echo "  bad=$bad   parts_bytes=$(du -cb "$PARTS"/part-* 2>/dev/null | tail -1 | cut -f1)"
[ "$bad" -ne 0 ] && { echo "[FATAL] 仍有不完整段，不拼装"; exit 3; }

echo "=== [4] stitch ==="
CUR=$(stat -c %s "$F"); echo "  before=$CUR"
for f in $(ls "$PARTS"/part-* | sort); do cat "$f" >> "$F"; done
FIN=$(stat -c %s "$F"); echo "  after=$FIN expect=$TOTAL delta=$((FIN-TOTAL))"
[ "$FIN" -eq "$TOTAL" ] || { echo "[FATAL] 大小不符"; exit 4; }

echo "=== [5] structure ==="
/root/miniconda3/bin/python - "$F" <<'PY'
import json, os, struct, sys
p = sys.argv[1]
with open(p, 'rb') as f:
    n = struct.unpack('<Q', f.read(8))[0]
    blob = f.read(n)
h = json.loads(blob.decode('utf-8'))
mx = max(int(v['data_offsets'][1]) for k, v in h.items() if k != '__metadata__')
need = 8 + n + mx
sz = os.path.getsize(p)
print("  header=%d tensors=%d expect=%d actual=%d %s"
      % (n, len(h) - (1 if '__metadata__' in h else 0), need, sz, "PASS" if need == sz else "FAIL"))
sys.exit(0 if need == sz else 1)
PY
rc=$?
if [ "$rc" -eq 0 ]; then rm -rf "$PARTS"; echo "[OK] shard14 complete"; else echo "[FATAL] 结构失败"; exit 5; fi

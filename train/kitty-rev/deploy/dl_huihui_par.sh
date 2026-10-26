#!/bin/bash
# dl_huihui_par.sh - 8-way parallel resumable downloader for Huihui-Qwen3.8-27B-abliterated
# Measured: single URL ~3.07 MiB/s; 8-way 6.96-7.37 MiB/s aggregate (60s gate PASS).
# Per-file independent -C - resume, 5 retries, per-file byte+header verification.
# EXPECT_TOTAL = 55,562,855,904 B  (= 27,781,427,952 params x 2 B)
set -eu

REPO="huihui-ai/Huihui-Qwen3.8-27B-abliterated"
BASE="https://hf-mirror.com/$REPO/resolve/main"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
DIR=/root/autodl-tmp/kitty-rev/base/Huihui
LOGDIR=/root/autodl-tmp/kitty-rev/logs/dlpar
PAR=${PAR:-8}
RETRY=5
EXPECT_TOTAL=55562855904

mkdir -p "$DIR" "$LOGDIR"
cd "$DIR"

# ---- single-instance guard (a second instance writing the same files corrupts them) ----
exec 9>"$LOGDIR/.dl.lock"
if ! flock -n 9; then
  echo "[FATAL] another dl_huihui_par.sh holds $LOGDIR/.dl.lock -- abort"
  exit 2
fi
if pgrep -x curl >/dev/null 2>&1; then
  echo "[FATAL] stray curl processes already running -- abort to avoid double-write:"
  pgrep -ax curl
  exit 3
fi

remote_size() {
  # NOTE: awk must use printf "%.0f" -- plain print turns 3966730520 into 3.96673e+09
  curl -sIL --max-time 30 -H "User-Agent: $UA" "$BASE/$1" | tr -d '\r' \
    | awk 'tolower($1)=="content-length:"{v=$2} END{printf "%.0f\n", v+0}'
}

fetch() {
  f="$1"; n=0; want=0; got=0
  want=$(remote_size "$f")
  echo "$want" > "$LOGDIR/bc-$f.txt"
  got=$(stat -c %s "$f" 2>/dev/null || echo 0)
  if [ "${want:-0}" -gt 0 ] && [ "$got" -eq "$want" ]; then
    echo "[SKIP ] $f  complete $got B"; return 0
  fi
  [ "$got" -gt 0 ] && echo "[RESUME] $f  from $got / $want B"
  while [ "$n" -lt "$RETRY" ]; do
    n=$((n + 1))
    if curl -sS -L -f -C - --connect-timeout 30 \
             --speed-limit 8192 --speed-time 90 \
             -H "User-Agent: $UA" -o "$f" "$BASE/$f"; then
      got=$(stat -c %s "$f" 2>/dev/null || echo 0)
      if [ "${want:-0}" -gt 0 ] && [ "$got" -eq "$want" ]; then
        echo "[OK   ] $f  $got B"; return 0
      fi
      [ "${want:-0}" -eq 0 ] && { echo "[OK?  ] $f  $got B (no content-length)"; return 0; }
      echo "[SHORT] $f  got=$got want=$want  attempt $n"
    else
      echo "[FAIL ] $f  attempt $n  rc=$?"
    fi
    sleep $((n * 8))
  done
  echo "[GIVEUP] $f after $RETRY attempts"
  return 1
}

export -f fetch remote_size
export BASE UA RETRY LOGDIR

echo "########## dl_huihui_par START $(date '+%F %T')  PAR=$PAR ##########"
df -h /root/autodl-tmp | tail -1

echo "--- remote sizes ---"
BIG=""; BIGSZ=0
for i in $(seq 1 18); do
  f=$(printf 'model-%05d-of-00018.safetensors' "$i")
  s=$(remote_size "$f")
  printf "  %-38s %12s B\n" "$f" "$s"
  if [ "${s:-0}" -gt "$BIGSZ" ]; then BIGSZ=$s; BIG="$f"; fi
done
echo "  => largest = $BIG ($BIGSZ B) -> downloaded alone in PHASE2"

echo
echo "=== PHASE1  ${PAR}-way: 17 shards (largest excluded) ==="
printf '%s\n' $(for i in $(seq 1 18); do printf 'model-%05d-of-00018.safetensors ' "$i"; done) \
  | tr ' ' '\n' | grep -v "^$BIG$" | grep -v '^$' \
  | xargs -P "$PAR" -I{} bash -c 'fetch "{}"' 2>&1 | tee -a "$LOGDIR/phase1.log" || true

echo
echo "=== PHASE2  single: $BIG ==="
fetch "$BIG" 2>&1 | tee -a "$LOGDIR/phase2.log" || true

echo
echo "=== [a] BYTES CHECK (local vs HEAD content-length) ==="
: > "$LOGDIR/bytes-check.txt"
TOTAL=0; BAD=0
for i in $(seq 1 18); do
  f=$(printf 'model-%05d-of-00018.safetensors' "$i")
  l=$(stat -c %s "$f" 2>/dev/null || echo 0)
  r=$(cat "$LOGDIR/bc-$f.txt" 2>/dev/null || echo 0)
  if [ "$l" = "$r" ] && [ "$l" -gt 0 ]; then st=OK; else st=MISMATCH; BAD=$((BAD+1)); fi
  printf "%-38s local=%-14s remote=%-14s %s\n" "$f" "$l" "$r" "$st" | tee -a "$LOGDIR/bytes-check.txt"
  TOTAL=$((TOTAL + l))
done
DIFF=$((TOTAL - EXPECT_TOTAL))
echo "TOTAL=$TOTAL  EXPECT=$EXPECT_TOTAL  DIFF=$DIFF  MISMATCH_FILES=$BAD" | tee -a "$LOGDIR/bytes-check.txt"
echo "  gate_b_count = $([ "$BAD" -eq 0 ] && echo PASS || echo FAIL)"
echo "  gate_c_total = $([ "$DIFF" -eq 0 ] && echo PASS || echo FAIL)"

echo
echo "=== [b] saftensors HEADER PARSE (structure integrity) ==="
cat > /tmp/chk_st.py <<'PY'
import json, os, struct, sys
bad = 0
for p in sys.argv[1:]:
    try:
        with open(p, 'rb') as f:
            raw = f.read(8)
            if len(raw) != 8:
                print("FAIL %s short-prefix" % p); bad += 1; continue
            n = struct.unpack('<Q', raw)[0]
            if n <= 0 or n > 200_000_000:
                print("FAIL %s bad-header-len=%d" % (p, n)); bad += 1; continue
            blob = f.read(n)
            if len(blob) != n:
                print("FAIL %s header-truncated %d/%d" % (p, len(blob), n)); bad += 1; continue
            h = json.loads(blob.decode('utf-8'))
        nt = len(h) - (1 if '__metadata__' in h else 0)
        mx = 0
        for k, v in h.items():
            if k == '__metadata__':
                continue
            o = v.get('data_offsets') or [0, 0]
            mx = max(mx, int(o[1]))
        need = 8 + n + mx
        sz = os.path.getsize(p)
        ok = (sz == need)
        print("%s %-38s tensors=%-4d hdr=%-8d expect=%-14d actual=%-14d%s"
              % ("PASS" if ok else "FAIL", os.path.basename(p), nt, n, need, sz,
                 "" if ok else "  SIZE-MISMATCH"))
        if not ok:
            bad += 1
    except Exception as e:
        print("FAIL %s %s" % (p, e)); bad += 1
print("HEADER_BAD=%d" % bad)
sys.exit(0 if bad == 0 else 1)
PY
/root/miniconda3/bin/python /tmp/chk_st.py *.safetensors | tee "$LOGDIR/header-check.txt" || true
HBAD=$(tail -1 "$LOGDIR/header-check.txt" | sed 's/HEADER_BAD=//')
echo "  gate_d_header = $([ "${HBAD:-1}" -eq 0 ] && echo PASS || echo FAIL)"

echo
echo "=== VERIFY SUMMARY ==="
CNT=$(ls -1 *.safetensors 2>/dev/null | wc -l)
echo "  gate_a_count  = $CNT / 18  -> $([ "$CNT" -eq 18 ] && echo PASS || echo FAIL)"
du -sh "$DIR"
df -h /root/autodl-tmp | tail -1
echo "########## dl_huihui_par END $(date '+%F %T') ##########"

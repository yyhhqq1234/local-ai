#!/usr/bin/env bash
# dl_base8.sh —— 本地 8 路 Range 逐片下载基座（每片严格校验尺寸；失败片重试）
set -uo pipefail
REPO=huihui-ai/Huihui-Qwen3.8-27B-abliterated
BASE=https://hf-mirror.com/$REPO/resolve/main
DIR=/d/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev/tmp/_base
CURL=/c/Windows/System32/curl.exe
PY=/c/ProgramData/anaconda3/python.exe
N=6
mkdir -p "$DIR"; cd "$DIR" || exit 2

[ -s tree.json ] || $CURL -fsSL -H "User-Agent: Mozilla/5.0" "https://hf-mirror.com/api/models/$REPO/tree/main?recursive=1" -o tree.json || exit 3

$PY -X utf8 -c "
import json
d=json.load(open('tree.json',encoding='utf-8'))
rows=[(x['path'],x['size']) for x in d if x.get('type')=='file' and x['path'].endswith('.safetensors')]
rows.sort()
with open('shards.txt','w') as f:
    for p,s in rows: f.write(f'{p} {s}\n')
print('[info] shards', len(rows))
"

TOTAL=0; OK=0
while read -r f want; do
  [ -z "${f:-}" ] && continue
  TOTAL=$((TOTAL+1))
  if [ -f "$f" ] && [ "$(stat -c%s "$f" 2>/dev/null || echo 0)" = "$want" ]; then
    echo "  skip $f"; OK=$((OK+1)); continue
  fi
  echo "  == $f want=$want  $(date '+%H:%M:%S')"
  rm -rf "parts_$f"; mkdir -p "parts_$f"
  ch=$(( (want + N - 1) / N ))
  for k in $(seq 0 $((N-1))); do
    s=$(( k * ch )); e=$(( s + ch - 1 ))
    if [ "$e" -ge "$want" ]; then e=$((want-1)); fi
    (
      for try in 1 2 3 4 5; do
        have=$(stat -c%s "parts_$f/p$k" 2>/dev/null || echo 0)
        need=$(( e - s + 1 ))
        [ "$have" = "$need" ] && exit 0
        from=$(( s + have ))
        $CURL -4 -fsSL --retry 3 --speed-limit 102400 --speed-time 60 --connect-timeout 15 --max-time 1200 \
               -r "${from}-${e}" -o "parts_$f/tp$k" "$BASE/$f" >/dev/null 2>&1 < /dev/null || { sleep 2; continue; }
        cat "parts_$f/tp$k" >> "parts_$f/p$k"; rm -f "parts_$f/tp$k"
      done
    ) < /dev/null &
  done
  wait
  : > "$f"
  for k in $(seq 0 $((N-1))); do cat "parts_$f/p$k" >> "$f" 2>/dev/null || true; done
  got=$(stat -c%s "$f" 2>/dev/null || echo 0)
  if [ "$got" = "$want" ]; then echo "  ok $f $got"; OK=$((OK+1)); rm -rf "parts_$f"; else echo "  FAIL $f got=$got want=$want"; fi
done < <(cat shards.txt)

echo "[done] ok=$OK/$TOTAL  $(date '+%H:%M:%S')"
du -sh "$DIR"

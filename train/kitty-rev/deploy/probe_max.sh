#!/bin/bash
# probe_max.sh - three (plus one) speed paths, measured back-to-back.
# Existing 8-way download KEEPS RUNNING; all numbers are therefore CONSERVATIVE.
set -u
REPO="huihui-ai/Huihui-Qwen3.8-27B-abliterated"
HF="https://huggingface.co/$REPO/resolve/main"
MIR="https://hf-mirror.com/$REPO/resolve/main"
MSQ="https://modelscope.cn/models/Qwen/Qwen3.8-27B/resolve/master"
F="model-00002-of-00018.safetensors"
R32="0-33554431"
MB=1048576
W='%{speed_download} %{http_code} %{size_download} %{time_total}'
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'

fmt() { awk -v o="$1" 'BEGIN{split(o,a," "); if(a[1]==""||a[1]+0==0) printf "   0.00 MiB/s  http=%s raw=[%s]\n", a[2], o; else printf "%7.2f MiB/s  http=%-4s got=%s  %.1fs\n", a[1]/1048576, a[2], a[3], a[4]}'; }

echo "################ probe_max START $(date '+%F %T') ################"
echo "live dl at start: $(stat -c %s /root/autodl-tmp/kitty-rev/base/Huihui/model-00001-of-00018.safetensors 2>/dev/null) B shard01"
ps -eo pid,cmd | grep '[d]l_huihui_par' | head -2

########################################################################
echo
echo "==================== PATH 1: AutoDL /etc/network_turbo ===================="
if [ -f /etc/network_turbo ]; then
  echo "  FILE EXISTS:"; sed -n '1,10p' /etc/network_turbo
  (
    # shellcheck disable=SC1091
    . /etc/network_turbo
    echo "  -- proxy env after source --"
    env | grep -i -E 'proxy' || echo "  (none)"
    echo "  -- hf.co config.json (20s) --"
    o=$(curl -sL -o /dev/null --max-time 20 -H "User-Agent: $UA" -w "$W" "$HF/config.json" 2>/dev/null)
    echo "  cfg: $(fmt "$o")"
    echo "  -- hf.co 32MiB single --"
    o=$(curl -sS -L --max-time 40 -r "$R32" -o /dev/null -H "User-Agent: $UA" -w "$W" "$HF/$F" 2>/dev/null)
    echo "  single: $(fmt "$o")"
    echo "  -- hf.co 32MiB 4-way --"
    rm -f /tmp/p1_*.o; tot=0
    for i in 1 2 3 4; do
      g=$(printf 'model-%05d-of-00018.safetensors' $((i+1)))
      ( curl -sS -L --max-time 40 -r "$R32" -o /dev/null -H "User-Agent: $UA" -w "$W" "$HF/$g" > /tmp/p1_$i.o 2>/dev/null ) &
    done
    wait
    for i in 1 2 3 4; do
      read -r sp cd nb tm < /tmp/p1_$i.o 2>/dev/null || sp=0
      printf "    f%d: %7.2f MiB/s http=%s\n" "$i" "$(awk -v s="${sp:-0}" 'BEGIN{print s/1048576}')" "${cd:-NA}"
      tot=$(awk -v a=$tot -v b="${sp:-0}" 'BEGIN{printf "%.0f", a+b}')
    done
    echo "  T4 TOTAL: $(awk -v t=$tot 'BEGIN{printf "%.2f", t/1048576}') MiB/s"
  )
else
  echo "  /etc/network_turbo NOT FOUND -> path 1 unavailable"
fi

########################################################################
echo
echo "==================== PATH 2: aria2c multi-connection ===================="
if ! command -v aria2c >/dev/null 2>&1; then
  echo "  aria2c missing -> installing (cap 180s)"
  ( timeout 180 bash -c 'apt-get install -y aria2 || (apt-get update -y && apt-get install -y aria2)' ) 2>&1 | tail -4
fi
if command -v aria2c >/dev/null 2>&1; then
  echo "  aria2c: $(aria2c --version 2>/dev/null | head -1)"
  rm -f /tmp/t1 /tmp/t1.aria2
  timeout 45 aria2c -x16 -s16 -k1M --file-allocation=none --allow-overwrite=true \
    --console-log-level=warn --summary-interval=15 -d /tmp -o t1 "$MIR/$F" >/tmp/aria.log 2>&1
  sz=$(stat -c %s /tmp/t1 2>/dev/null || echo 0)
  echo "  downloaded ${sz} B in 45s -> $(awk -v s=$sz 'BEGIN{printf "%.2f", s/1048576/45}') MiB/s (x16 -s16)"
  grep -E 'Download Results|Download Speed|CN:' /tmp/aria.log 2>/dev/null | tail -5
  rm -f /tmp/t1 /tmp/t1.aria2
else
  echo "  aria2c install FAILED -> path 2 unavailable"
fi

########################################################################
echo
echo "==================== PATH 3: ModelScope 32MiB baseline ===================="
for i in 1 2; do
  o=$(curl -sS -L --max-time 40 -r "$R32" -o /dev/null -H "User-Agent: $UA" -w "$W" \
      "$MSQ/model-00001-of-00018.safetensors" 2>/dev/null)
  echo "  ms r$i: $(fmt "$o")"
done
echo "  (单流 7+ MiB/s => 实例出网不封顶 8.5，是 hf-mirror 侧封顶)"

########################################################################
echo
echo "==================== PATH 4: hf-mirror NO-range single stream (35s) ===================="
rm -f /tmp/nr.bin
o=$(curl -sS -L -f --max-time 35 -o /tmp/nr.bin -H "User-Agent: $UA" -w "$W" "$MIR/$F" 2>/dev/null)
echo "  no-range: $(fmt "$o")"
echo "  bytes on disk: $(stat -c %s /tmp/nr.bin 2>/dev/null || echo 0)"
rm -f /tmp/nr.bin

echo
echo "################ END $(date '+%F %T') ################"

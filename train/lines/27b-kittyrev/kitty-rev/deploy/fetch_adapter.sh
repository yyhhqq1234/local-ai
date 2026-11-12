#!/usr/bin/env bash
# fetch_adapter.sh —— 从 A800 取回最新 adapter（ckpt 或 adapter 目录），校验后可选关机
#
# 用法：
#   bash fetch_adapter.sh              # 取最新 checkpoint 的 adapter 到 train/lines/27b-kittyrev/local-pack/gen2v2/
#   bash fetch_adapter.sh --shutdown   # 取完立即关机（停止 ¥7.98/h 计时）
#
# 判定：adapter_model.safetensors 必须 > 50MB（r16 的 27B 语言塔 adapter ≈ 320MB），
#       且本机字节数 == 远端字节数，否则不关机。
set -uo pipefail
KEY=$HOME/.ssh/autodl_a800
PORT=51211
HOST=root@connect.bjb1.seetacloud.com
OPTS="-i $KEY -P $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
SSHOPTS="-i $KEY -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
REMOTE_ROOT=/root/autodl-tmp/kitty-rev
LOCAL_OUT=${LOCAL_OUT:-D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/local-pack/gen2v2}
SHUTDOWN=${1:-}

sshx(){ ssh $SSHOPTS "$HOST" "$@"; }

echo "== 定位最新 adapter =="
# 只认本轮 checkpoint；out/adapter 是 10-22 遗留的旧件，绝不能当本轮产物取回
AD=$(sshx "ls -d $REMOTE_ROOT/out/gen2-a800/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1")
AD=$(echo "$AD" | head -1)
if [ -z "${AD:-}" ]; then
  # 没有 checkpoint 时才看 adapter，但必须比本轮开训时间新（今天 19:00 之后）
  ADM=$(sshx "stat -c %Y $REMOTE_ROOT/out/gen2-a800/adapter 2>/dev/null || echo 0")
  CUT=$(date -d '2026-10-29 19:00' +%s 2>/dev/null || echo 0)
  if [ "${ADM:-0}" -gt "${CUT:-0}" ]; then
    AD=$REMOTE_ROOT/out/gen2-a800/adapter
  else
    echo "[FATAL] 没有本轮 checkpoint，且 out/adapter 是旧件（mtime $ADM <= 19:00 截止 $CUT），拒绝取回"
    exit 6
  fi
fi
if [ -z "${AD:-}" ]; then echo "[FATAL] 远端没有 checkpoint/adapter"; exit 2; fi
echo "远端 adapter: $AD"
sshx "ls -l '$AD'; stat -c '%s' '$AD/adapter_model.safetensors' 2>/dev/null || echo NOSAFE"

RSZ=$(sshx "stat -c '%s' '$AD/adapter_model.safetensors' 2>/dev/null || echo 0")
if [ "${RSZ:-0}" -lt 50000000 ]; then echo "[FATAL] adapter 异常（$RSZ 字节 < 50MB）"; exit 3; fi

mkdir -p "$LOCAL_OUT"
for f in adapter_model.safetensors adapter_config.json chat_template.jinja; do
  src="$AD/$f"
  if sshx "test -f '$src'"; then
    echo "  ↓ $f"
    scp $OPTS "$HOST:$src" "$LOCAL_OUT/$f" >/dev/null 2>&1 || { echo "[FATAL] 下载失败 $f"; exit 4; }
  fi
done
LSZ=$(stat -c %s "$LOCAL_OUT/adapter_model.safetensors" 2>/dev/null || echo 0)
echo "本地 adapter: $(printf '%.1f' $(echo "$LSZ/1048576" | bc 2>/dev/null || echo 0)) MB（远端 $RSZ 字节）"
if [ "$LSZ" != "$RSZ" ]; then echo "[FATAL] 大小不一致 本地 $LSZ / 远端 $RSZ，不关机"; exit 5; fi
echo "[OK] adapter 取回并校验一致 → $LOCAL_OUT"

if [ "$SHUTDOWN" = "--shutdown" ]; then
  echo "== 关机（停止计费）=="
  cd "$(dirname "$0")" || exit 0
  AUTODL_HOST=connect.bjb1.seetacloud.com:51211 AUTODL_PASS=UYGNSRWWiAvn \
    "C:/ProgramData/anaconda3/python.exe" -X utf8 autodl_power.py off --force 2>&1 | tail -4
fi

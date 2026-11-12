#!/usr/bin/env bash
# push_base.sh —— 原生 ssh 多流推送基座（本机 → AutoDL），按远端已有字节续传
#
# 为什么不用 paramiko：Python 层 8 线程只跑到 ~10 MB/s 且不再涨，
# 怀疑是解释器侧拷贝/加密上限；这里换成原生 ssh + dd 管道（加密在 C 层），
# 每个文件一条独立 ssh 连接，xargs -P 控并发。
#
# 用法：bash push_base.sh <并发数>
# 环境：KEY / PORT / HOST / SRC / DST
set -uo pipefail
P=${1:-6}
KEY=${KEY:-$HOME/.ssh/autodl_a800}
PORT=${PORT:-51211}
HOST=${HOST:-root@connect.bjb1.seetacloud.com}
SRC=${SRC:-/d/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/base/Qwen3.8-27B}
DST=${DST:-/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B}
OPTS="-i $KEY -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o Compression=no -o LogLevel=ERROR"
BS=4M

sshx(){ ssh $OPTS "$HOST" "$@"; }

push_one(){
  local f="$1"
  local lsz rsz skip
  lsz=$(stat -c %s "$SRC/$f")
  rsz=$(sshx "stat -c %s '$DST/$f' 2>/dev/null || echo 0")
  rsz=${rsz:-0}
  if [ "$rsz" = "$lsz" ]; then echo "SKIP $f ($lsz)"; return 0; fi
  if [ "$rsz" -gt "$lsz" ]; then echo "RESET $f 远端过大 $rsz>$lsz"; rsz=0; fi
  skip=$((rsz / 4194304))          # 按 4M 块对齐，向上取整会丢数据，向下取整安全
  local skipb=$((skip * 4194304))
  # 续传点若不是 4M 对齐，先把尾部非对齐部分截掉，保证 dd seek 与本地 skip 严格对齐
  if [ "$rsz" -ne "$skipb" ]; then
    sshx "truncate -s $skipb '$DST/$f'" || return 1
  fi
  echo "PUSH $f 从 $((skipb/1048576))MB / 共 $((lsz/1048576))MB"
  dd if="$SRC/$f" bs=$BS skip=$skip 2>/dev/null \
    | ssh $OPTS "$HOST" "dd of='$DST/$f' bs=$BS seek=$skip conv=notrunc 2>/dev/null"
  local now; now=$(sshx "stat -c %s '$DST/$f'")
  if [ "$now" = "$lsz" ]; then echo "OK   $f $((lsz/1048576))MB"; else echo "BAD  $f 远端 $now != $lsz"; return 1; fi
}
export -f push_one sshx
export KEY PORT HOST SRC DST OPTS BS

cd "$SRC" || exit 1
S=$(date +%s)
if [ -n "${FILES:-}" ]; then
  echo "$FILES" | tr ' ' '
' | xargs -P "$P" -I{} bash -c 'push_one "$@"' _ {}
else
  ls -1 *.safetensors *.json *.txt *.jinja 2>/dev/null | xargs -P "$P" -I{} bash -c 'push_one "$@"' _ {}
fi
E=$(date +%s)
echo "=== 完成 用时 $((E-S))s (并发 $P) ==="
sshx "cd '$DST' && ls -l *.safetensors | awk '{s+=\$5} END {printf \"远端 safetensors 合计 %.2f GB\n\", s/1073741824}'"

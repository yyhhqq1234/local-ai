#!/usr/bin/env bash
# pack_ninfer.sh —— 抢到卡后自动完成「取 ninfer 工具 → 本机打包 → 关云机」
#
# 为什么不在云上打包：本机已把 merge/gguf/GSQ-RCO 量化全部做完（9.9078 GB, 2.90 BPW），
# 只剩 tools.convert 这一步需要 ninfer-all-master（云上才有）。所以只搬工具（几十 MB），
# 不搬 10GB 权重 —— 上传 9.9GB @10MB/s 要 17min，来回 34min，纯浪费机时。
#
# 用法：bash pack_ninfer.sh            # 自动开机→取工具→打包→关机
#      bash pack_ninfer.sh --tools-only  # 只取工具，不打包（打包另跑）
set -uo pipefail
cd "$(dirname "$0")" || exit 1
PY="C:/ProgramData/anaconda3/python.exe"
KEY=${KEY:-$HOME/.ssh/autodl_a800}
PORT=${PORT:-45062}          # 新实例 RTX 5090 (¥2.88/h)；旧 A800 是 51211
HOST=root@connect.bjb1.seetacloud.com
SSHOPTS="-i $KEY -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=20"
SCPOPTS="-i $KEY -P $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
RR=/root/autodl-tmp/kitty-rev
TRAIN=D:/BaiduNetdiskDownload/Local-AI/train
TOOLDIR=$TRAIN/tools/ninfer-all-master
GGUF=$TRAIN/local-pack/gen2v2/gen2v2-iq2s-gsqrco.gguf
OUT=$TRAIN/local-pack/gen2v2/qwen3.8-27b-kittyrev-gen2v2-vision-iq2s.ninfer
LOG=$TRAIN/logs/pack-ninfer.log
MODE=${1:-}

log(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
sshx(){ ssh $SSHOPTS "$HOST" "$@"; }

# 1) 开机（最多 60 次 ≈ 1 小时）
if ! sshx "true" 2>/dev/null; then
  log "实例不可达，开始抢开机"
  for i in $(seq 1 60); do
    out=$($PY -u autodl_power.py on --wait 150 2>&1 | tail -1)
    log "[$i] $out"
    case "$out" in *"已开机"*|*running*|*OK*) log "POWERED_ON"; break;; esac
    sleep 60
  done
  sshx "true" 2>/dev/null || { log "FATAL 抢不到 GPU，退出"; exit 11; }
fi

# 2) 打包工具成 tar（排除权重/模型/缓存）
if [ ! -d "$TOOLDIR" ]; then
  log "远端打包 ninfer-all-master"
  sshx "cd $RR && tar czf /root/autodl-tmp/ninfer-tools.tgz --exclude='*.gguf' --exclude='*.ninfer' --exclude='*.safetensors' --exclude='__pycache__' --exclude='.git' ninfer-all-master 2>/dev/null; ls -lh /root/autodl-tmp/ninfer-tools.tgz"
  mkdir -p "$TRAIN/tools"
  scp $SCPOPTS "$HOST:/root/autodl-tmp/ninfer-tools.tgz" "$TRAIN/tools/ninfer-tools.tgz" || { log "FATAL 工具下载失败"; exit 12; }
  log "解包 $(du -h "$TRAIN/tools/ninfer-tools.tgz" | cut -f1)"
  ( cd "$TRAIN/tools" && tar xzf ninfer-tools.tgz )
fi
[ "$MODE" = "--tools-only" ] && { log "只取工具，结束"; exit 0; }

# 3) 本机打包（需要 venv 里有 gguf/torch；tools.convert 走 CPU）
log "本机打包 .ninfer（--components text,vision,mtp）"
cd "$TOOLDIR" || { log "FATAL 缺 $TOOLDIR"; exit 13; }
"$TRAIN/.venv/Scripts/python.exe" -X utf8 -m tools.convert \
  --model "$TRAIN/merged/gen2v2" \
  --recipe qwen3_8_27b_gguf --source gguf="$GGUF" \
  --components text,vision,mtp \
  --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja \
  --name qwen3.8-27b-kittyrev-gen2v2-vision --device cpu --out "$OUT" 2>&1 | tail -12 | tee -a "$LOG"
ls -l "$OUT" 2>/dev/null | tee -a "$LOG" || { log "FATAL 打包未产出"; exit 14; }

# 4) 关机（停止计费）
log "关机"
cd "$TRAIN/kitty-rev/deploy"
AUTODL_PORT=$PORT AUTODL_PASS=${AUTODL_PASS:-UYGNSRWWiAvn} $PY -X utf8 autodl_power.py off --force 2>&1 | tail -3 | tee -a "$LOG"
log "=== DONE ==="

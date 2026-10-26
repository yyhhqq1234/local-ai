#!/usr/bin/env bash
# rebuild_v4.sh —— v4 全链重建（G1..G7 顺序执行，硬闸门；任一红写 [STOP] 并退出）
# 用法: bash tools/rebuild_v4.sh              # 全链
#       bash tools/rebuild_v4.sh --from G4    # 从 G4 起
#       bash tools/rebuild_v4.sh --rehearse   # 只做语法/路径/二进制演练，不写真产物
set -uo pipefail

R=/root/autodl-tmp/kitty-rev
PY=/root/miniconda3/bin/python
LC=/root/autodl-tmp/lc
BQ=$LC/build-cuda89/bin/llama-quantize
LOG=$R/logs/v4/REBUILD.log
BASE=/root/autodl-tmp/base-hf/Huihui
ADAPTER=$R/kitty-rev/out-v4/adapter
MERGED=/root/autodl-tmp/merged-v4
IMAT=$R/imatrix-v4.dat
BF16=$R/gguf/v4-bf16.gguf
IQ2S=$R/gguf/v4-iq2s-851.gguf
MTP=$R/gguf/mtp-spliced/v4_mtp.gguf
REF=/root/autodl-tmp/ref/ref_sparse.gguf
CFGV=$R/cfg-vision
NIN=$R/ninfer-v4/qwen3.8-27b-kittyrev-v4-swift1.5-gsq-rco-iq2s-mtp.ninfer
FROM=G1; REHEARSE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2;;
    --rehearse) REHEARSE=1; shift;;
    *) shift;;
  esac
done

mkdir -p "$(dirname "$LOG")" "$R/gguf/mtp-spliced" "$R/ninfer-v4"
log()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }
stop() { if [ "$REHEARSE" = "1" ]; then log "[rehearse-STOP] $*"; return 0; fi; log "[STOP] $*"; exit 1; }
need() { [ -e "$1" ] || stop "缺 $1"; }                             # 硬依赖（工具/配置）
needx(){ [ -e "$1" ] || { [ "$REHEARSE" = "1" ] && log "[rehearse] 缺 $1（忽略）" || stop "缺 $1"; }; }
mb()   { stat -c%s "$1" 2>/dev/null || echo 0; }
runs() { case "$FROM" in G1|G2|G3|G4|G5|G6|G7) [ "$1" \> "$FROM" ] && [ "$1" != "$FROM" ] && return 1;; esac
         case "$FROM" in "$1") return 0;; esac
         case "$FROM" in G1|G2|G3|G4|G5|G6|G7) return 0;; esac; return 1; }

log "===== rebuild_v4 start from=$FROM rehearse=$REHEARSE free=$(df -h /root/autodl-tmp | awk 'NR==2{print $4}') ====="

# ---------------- G1 基座齐 ----------------
if [ "$FROM" = "G1" ]; then
  n=$(ls "$BASE"/*.safetensors 2>/dev/null | wc -l)
  tot=$(du -sb "$BASE" 2>/dev/null | awk '{print $1}')
  log "[G1] base=$BASE shards=$n bytes=${tot:-0}"
  [ "$n" -eq 18 ] || stop "G1 分片数 $n != 18"
  { [ "${tot:-0}" -ge 53000000000 ] && [ "${tot:-0}" -le 56000000000 ]; } || stop "G1 体积 ${tot:-0} 不在 53–56e9"
  need "$BASE/config.json"
  log "[G1] PASS"
fi

# ---------------- G2 merge ----------------
case "$FROM" in G1|G2)
  need "$ADAPTER/adapter_config.json"
  MERGER=""
  for c in "$R/kitty-rev/scripts/merge.py" "$R/kitty-rev/scripts/merge_adapter.py" \
           "$R/kitty-rev/scripts/merge_lora.py" "$R/deploy/merge_adapter.py"; do
    [ -f "$c" ] && MERGER="$c" && break
  done
  [ -n "$MERGER" ] || stop "G2 无 merge 脚本（候选 scripts/merge.py 等），请指定后重跑"
  log "[G2] merge base=$BASE adapter=$ADAPTER -> $MERGED via $MERGER"
  if [ "$REHEARSE" = "1" ]; then
    log "[G2][rehearse] 跳过真 merge（命令：$PY $MERGER --size 27b --base $BASE --adapter $ADAPTER --dest $MERGED）"
  else
    OMP_NUM_THREADS=32 $PY "$MERGER" --size 27b --base "$BASE" --adapter "$ADAPTER" --dest "$MERGED" >>"$LOG" 2>&1 \
      || stop "G2 merge rc!=0（见 $LOG）"
    n=$(ls "$MERGED"/*.safetensors 2>/dev/null | wc -l)
    [ "$n" -ge 12 ] || stop "G2 产物分片 $n < 12"
    need "$MERGED/config.json"
    log "[G2] PASS shards=$n bytes=$(du -sb "$MERGED" | awk '{print $1}')"
  fi
  ;;
esac

# ---------------- G3 bf16 GGUF ----------------
case "$FROM" in G1|G2|G3)
  need "$R/tools/convert_gguf_safe.py"
  export TMPDIR=/root/autodl-tmp/tmpwork; mkdir -p "$TMPDIR"
  if [ -d "$CFGV" ]; then MODEL="$CFGV"; else MODEL="$MERGED"; fi
  log "[G3] convert model=$MODEL out=$BF16 (safe-writer + 判据八)"
  if [ "$REHEARSE" = "1" ]; then
    $PY -c "import ast;ast.parse(open('$R/tools/convert_gguf_safe.py').read());print('[G3][rehearse] syntax OK')" >>"$LOG" 2>&1 \
      || stop "G3 语法错"
  else
    rm -f "$BF16"
    $PY "$R/tools/convert_gguf_safe.py" "$MODEL" --outtype bf16 --outfile "$BF16" >>"$LOG" 2>&1 \
      || stop "G3 convert rc!=0（含判据八）"
    read -r n sz < <($PY "$R/tools/check_gguf.py" "$BF16")
    log "[G3] tensors=$n bytes=$sz"
    [ "$n" -eq 851 ] || stop "G3 张量数 $n != 851"
    { [ "$sz" -ge 53000000000 ] && [ "$sz" -le 55500000000 ]; } || stop "G3 体积 $sz 不在 53.0–55.5e9"
    log "[G3] PASS"
  fi
  ;;
esac

# ---------------- G4 IQ2_S ----------------
case "$FROM" in G1|G2|G3|G4)
  needx "$IMAT"; needx "$BF16"
  TT=(); for i in $(seq 0 63); do
    TT+=(--tensor-type "blk.$i.ssm_alpha.weight=q8_0")
    TT+=(--tensor-type "blk.$i.ssm_beta.weight=q8_0")
  done
  log "[G4] quantize IQ2_S -t 64 tt=$(( ${#TT[@]} / 2 )) 条 --tensor-type"
  if [ "$REHEARSE" = "1" ]; then
    need "$BQ"; $PY -c "import ast;ast.parse(open('$R/tools/check_iq2s.py').read());print('[G4][rehearse] binary+syntax OK')" >>"$LOG" 2>&1 || stop "G4 语法/二进制错"
  else
    rm -f "$IQ2S"
    "$BQ" --imatrix "$IMAT" "${TT[@]}" "$BF16" "$IQ2S" IQ2_S 64 >>"$LOG" 2>&1 || stop "G4 quantize rc!=0"
    out=$($PY "$R/tools/check_iq2s.py" "$IQ2S" 2>&1); echo "$out" >>"$LOG"
    echo "$out" | grep -q 'VERDICT = PASS' || stop "G4 判据红（851/体积/ssm=q8_0）"
    log "[G4] PASS $(mb "$IQ2S") B"
  fi
  ;;
esac

# ---------------- G5 splice ----------------
case "$FROM" in G1|G2|G3|G4|G5)
  needx "$IQ2S"; needx "$REF"; need "$R/tools/mtp_splice2.py"
  log "[G5] splice base=$IQ2S mtp=$REF out=$MTP"
  if [ "$REHEARSE" = "1" ]; then
    $PY -c "import ast;ast.parse(open('$R/tools/mtp_splice2.py').read());print('[G5][rehearse] syntax OK')" >>"$LOG" 2>&1 || stop "G5 语法错"
  else
    rm -f "$MTP"
    $PY "$R/tools/mtp_splice2.py" --base "$IQ2S" --mtp "$REF" --out "$MTP" >>"$LOG" 2>&1 || stop "G5 splice rc!=0"
    out=$($PY "$R/tools/verify_splice.py" "$MTP" "$REF" 2>&1); echo "$out" >>"$LOG"
    echo "$out" | grep -q 'VERDICT = PASS' || stop "G5 判据红（866/15/sha）"
    log "[G5] PASS $(mb "$MTP") B"
  fi
  ;;
esac

# ---------------- G6 convert ----------------
case "$FROM" in G1|G2|G3|G4|G5|G6)
  needx "$MTP"; need "$R/ninfer-all-master/tools/convert"
  log "[G6] convert --model $CFGV --components text,mtp -> $NIN"
  if [ "$REHEARSE" = "1" ]; then
    [ -d "$CFGV" ] || log "[rehearse] 缺 $CFGV（忽略）"
    log "[G6][rehearse] converter OK"
  else
    need "$CFGV"
    rm -f "$NIN"
    ( cd "$R/ninfer-all-master" && $PY -m tools.convert --model "$CFGV" --recipe qwen3_8_27b_gguf \
        --source gguf="$MTP" --components text,mtp \
        --name qwen3.8-27b-kittyrev-v4-swift1.5-gsq-rco-iq2s-mtp --out "$NIN" ) >>"$LOG" 2>&1 \
      || stop "G6 convert rc!=0"
    ( cd "$R/ninfer-all-master" && $PY -m tools.artifact.inspect "$NIN" ) 2>&1 | grep -a 'name:' \
      | grep -q 'qwen3.8-27b-kittyrev-v4-swift1.5-gsq-rco-iq2s-mtp' || stop "G6 inspect name 不符"
    ( cd "$R/ninfer-all-master" && PYTHONPATH="$R/ninfer-all-master" \
        $PY /root/autodl-tmp/_ra/verify-struct-align.py "$NIN" --gguf "$MTP" ) 2>&1 | tee -a "$LOG" \
      | grep -q 'STRUCT-ALIGN: GREEN' || stop "G6 struct-align 非 GREEN"
    log "[G6] PASS"
  fi
  ;;
esac

# ---------------- G7 ----------------
case "$FROM" in G1|G2|G3|G4|G5|G6|G7)
  if [ "$REHEARSE" = "1" ]; then
    log "[G7][rehearse] 预期产物 $NIN"
  else
    log "[G7] artifact=$NIN bytes=$(mb "$NIN") sha16=$(sha256sum "$NIN" | cut -c1-16)"
  fi
  ;;
esac
log "===== rebuild_v4 done free=$(df -h /root/autodl-tmp | awk 'NR==2{print $4}') ====="

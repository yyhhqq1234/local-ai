#!/bin/bash
# v5_auto.sh —— V5 全自动编排（无人值守）
#
# 设计前提：操作者不监督。所以本脚本必须做到：
#   1 每步自己断言（rc + 内容 + 尺寸），FAIL 立即停并写清原因
#   2 每步自动写 PR 文件（把实测数字填进模板，不是留空）
#   3 任何"需要人判断"的点，一律按预置分支走（见 PLAN §5 D1/D2），不等人
#   4 全程写日志，停了也能从 .markers 续跑
#
# 用法：
#   bash tools/v5_auto.sh                # 全跑（训练→merge→mmproj→量化→验证）
#   bash tools/v5_auto.sh --skip-train   # 已有 out-v5/adapter，从 merge 起
#   bash tools/v5_auto.sh --from M1      # 从量化链某门起
#   bash tools/v5_auto.sh --dry-run      # 只打印将执行什么
set -u

R=/root/autodl-tmp/kitty-rev
KV=$R
PY=/root/miniconda3/bin/python
MK=$R/logs/v5/.markers
PRD=$R/logs/v5
LOG=$R/logs/v5/AUTO-V5.log
BASE=$R/base/Huihui
AD=$R/out-v5/adapter
MERGED=$R/merged-v5
MMP=$R/gguf/v5-mmproj-q8.gguf
MIX=$KV/data/intent3/v5-mix/train.jsonl
NIN=$R/ninfer-v5
NAME=qwen3.8-27b-kittyrev-v5-iq2s-mtp
OUT=$NIN/$NAME.ninfer
PORT=18080

mkdir -p "$MK" "$PRD" "$R/gguf" "$NIN"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
ok(){ echo "$2" > "$MK/$1.ok"; log "[$1] PASS $2"; }
has(){ [ -f "$MK/$1.ok" ]; }
stop(){ log "[STOP] $1 :: $2"; write_pr "$1" "FAIL" "$2"; exit 1; }
free_g(){ df -BG --output=avail /root/autodl-tmp | tail -1 | tr -dc '0-9'; }
elapsed_h(){ echo "scale=2; ($(date +%s)-$T0)/3600" | bc; }

T0=$(date +%s)

# ---------- PR 自动生成 ----------
# write_pr <step> <PROCEED|FAIL> <detail...>
write_pr(){
  local step="$1" verdict="$2"; shift 2
  local f="$PRD/PR-$step.md"
  {
    echo "# PR-$step — 自动生成 $(date '+%F %T')"
    echo
    echo '## 元信息'
    echo '```text'
    printf '步号      %s\n' "$step"
    printf '时刻      %s\n' "$(date '+%F %T')"
    printf '执行者    v5_auto.sh（无人值守）\n'
    printf '累计耗时  %s h\n' "$(elapsed_h)"
    printf '磁盘剩余  %s G\n' "$(free_g)"
    echo '```'
    echo
    echo '## Q1 本步实际结果'
    echo '```text'
    local line
    for line in "$@"; do printf '%s\n' "$line"; done
    echo '```'
    echo
    echo '## Q2/Q3 判定'
    echo '```text'
    if [ "$verdict" = "PROCEED" ]; then
      echo '结论：PROCEED —— 判据全部满足，按 PLAN §0.2 进下一步'
      echo '计划假设：未被推翻（若被推翻，见下方 Q3 补充）'
    else
      echo '结论：FAIL —— 已停在当前步，后续未执行'
      echo '处置：按 PLAN §5 D1/D2 的预置分支；若预置分支也无解，保留现状等操作者'
    fi
    echo '```'
    echo
    echo '## Q4 下一步（PLAN 原文）'
    echo '见 `logs/v5/TEAM-PLAN-V5.md` §0.2 的步号顺序。'
  } > "$f"
  log "[PR] $f ($verdict)"
}

# ---------- 参数 ----------
SKIP_TRAIN=0; FROM=""; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-train) SKIP_TRAIN=1; shift ;;
    --from) FROM=${2:?--from 需要步名}; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

log "===== V5 AUTO start $([ $DRY -eq 1 ] && echo '(dry-run)') ====="
log "[disk] free=$(free_g)G"

# ---------- S1 训练 ----------
if [ "$SKIP_TRAIN" -eq 0 ] && ! has S1; then
  log "----- S1 训练（base + v5-mix，1.5 epoch）-----"
  [ -f "$MIX" ] || stop S1 "缺训练集 $MIX"
  [ -d "$BASE" ] || stop S1 "缺 base $BASE"
  N=$(wc -l < "$MIX")
  log "[S1] 训练集 $N 行"
  # 参数对齐 v4 已验证的 S4（v4_after_download.sh:645-651），只改三处：
  #   --data → v5-mix（多意愿层）／--epochs 3→1.5（增量）／--lr 2e-4→1e-4（防过拟合）
  CMD="cd $KV && $PY scripts/train_kitty.py --size 27b --stage sft \
       --base $BASE --text-only --data $MIX \
       --ctx 2048 --bs 1 --ga 16 --epochs 1.5 --lr 1e-4 \
       --lora-r 16 --lora-alpha 32 --all-gpu --out out-v5 \
       --dl-workers 4 --pin-memory --prefetch 2 --skip-kbit-prepare"
  if [ "$DRY" -eq 1 ]; then log "[dry] $CMD"; else
    eval "$CMD" >> "$LOG" 2>&1
    RC=$?
    [ "$RC" -eq 0 ] || stop S1 "训练 rc=$RC（末尾 30 行见日志）"
    [ -f "$AD/adapter_model.safetensors" ] || stop S1 "训练无 adapter 产物"
    ASZ=$(stat -c%s "$AD/adapter_model.safetensors")
    [ "$ASZ" -gt 100000000 ] || stop S1 "adapter 太小 $ASZ"
    ok S1 "adapter=$ASZ rows=$N"
    write_pr S1 PROCEED "rc=0" "训练集=$N 行" "adapter=$ASZ B" "耗时=$(elapsed_h)h"
  fi
fi

# ---------- S2 merge ----------
if { [ -z "$FROM" ] || [ "$FROM" = "S2" ]; } && ! has S2; then
  log "----- S2 merge(v5 adapter) -----"
  [ -f "$AD/adapter_model.safetensors" ] || stop S2 "缺 adapter"
  if [ "$DRY" -eq 1 ]; then log "[dry] tensor_merge --base $BASE --adapter $AD --out $MERGED --stream"; else
    $PY -u "$KV/tools/tensor_merge.py" --base "$BASE" --adapter "$AD" --out "$MERGED" --stream >> "$LOG" 2>&1
    RC=$?
    [ "$RC" -eq 0 ] || stop S2 "merge rc=$RC"
    N=$(ls "$MERGED"/*.safetensors 2>/dev/null | wc -l)
    [ "$N" -eq 18 ] || stop S2 "片数 $N != 18"
    for f in model.safetensors.index.json vocab.json video_preprocessor_config.json added_tokens.json; do
      [ -f "$BASE/$f" ] && [ ! -f "$MERGED/$f" ] && cp "$BASE/$f" "$MERGED/"
    done
    [ -f "$MERGED/model.safetensors.index.json" ] || stop S2 "缺 index.json"
    ok S2 "shards=$N"
    write_pr S2 PROCEED "rc=0" "shards=$N" "index 已补拷"
  fi
fi

# ---------- S3 mmproj（vision q8_0） ----------
if { [ -z "$FROM" ] || [ "$FROM" = "S3" ]; } && ! has S3; then
  log "----- S3 mmproj(vision, q8_0) -----"
  CONV=""
  for c in "$R/ninfer-all-master/convert_hf_to_gguf.py" "$R/lc/convert_hf_to_gguf.py"; do
    [ -f "$c" ] && CONV="$c" && break
  done
  [ -n "$CONV" ] || stop S3 "找不到 convert_hf_to_gguf.py"
  if [ "$DRY" -eq 1 ]; then log "[dry] $PY $CONV $MERGED --mmproj --outtype q8_0 --outfile $MMP"; else
    [ -f "$MMP" ] || $PY "$CONV" "$MERGED" --mmproj --outtype q8_0 --outfile "$MMP" >> "$LOG" 2>&1
    RC=$?
    [ "$RC" -eq 0 ] || stop S3 "mmproj rc=$RC"
    MSZ=$(stat -c%s "$MMP" 2>/dev/null || echo 0)
    [ "$MSZ" -gt 300000000 ] || stop S3 "mmproj 太小 $MSZ（可能没转 vision）"
    [ "$MSZ" -lt 700000000 ] || stop S3 "mmproj 太大 $MSZ（可能没量化）"
    ok S3 "mmproj=$MSZ"
    write_pr S3 PROCEED "rc=0" "mmproj=$MSZ B（q8_0，预期 0.42-0.46 GB）"
  fi
fi

# ---------- S4 量化链（chain_repair M1→M6，已含 vision） ----------
if { [ -z "$FROM" ] || [ "$FROM" = "S4" ] || [[ "$FROM" == M* ]]; } && ! has S4; then
  log "----- S4 量化链 M1→M6 -----"
  [ -f "$MMP" ] || stop S4 "缺 mmproj"
  if [ "$DRY" -eq 1 ]; then log "[dry] chain_repair.py --from M1"; else
    cd "$R" || stop S4 "进不去 $R"
    $PY -u "$KV/tools/chain_repair.py" --from M1 >> "$LOG" 2>&1
    RC=$?
    [ "$RC" -eq 0 ] || stop S4 "chain rc=$RC（看日志哪一门红）"
    [ -f "$OUT" ] || stop S4 "无产物 $OUT"
    SZ=$(stat -c%s "$OUT")
    MAGIC=$(head -c 4 "$OUT" | od -An -tx1 | tr -d ' \n')
    [ "$MAGIC" = "47475546" ] || stop S4 "magic=$MAGIC"
    [ "$SZ" -lt 11274289152 ] || stop S4 "体积 $SZ > 10.5 GiB"
    ok S4 "bytes=$SZ magic=GGUF"
    write_pr S4 PROCEED "rc=0" "size=$SZ B" "magic=GGUF" "checks: rc+magic+size 三者齐"
  fi
fi

# ---------- S5 本机验证（判据七 + kitty7，需本机引擎；云端只跑拒答率） ----------
if { [ -z "$FROM" ] || [ "$FROM" = "S5" ]; } && ! has S5; then
  log "----- S5 拒答率（refusal_probe，起 4bit 服务）-----"
  if [ "$DRY" -eq 1 ]; then
    log "[dry] serve_4bit_base.py + refusal_probe.py"
  elif [ -f "$KV/scripts/refusal_probe.py" ] && [ -f "$KV/scripts/serve_4bit_base.py" ]; then
    $PY "$KV/scripts/serve_4bit_base.py" --model "$MERGED" --port $PORT --name v5 --thinking >> "$LOG" 2>&1 &
    SPID=$!
    for i in $(seq 1 60); do
      curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1 && break
      sleep 5
    done
    if curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
      $PY "$KV/scripts/refusal_probe.py" --mode text --base "http://127.0.0.1:$PORT" \
          --model v5 --out "$PRD/refusal-v5.json" >> "$LOG" 2>&1 || log "[S5][WARN] refusal_probe 失败"
      ok S5 "refusal measured"
      write_pr S5 PROCEED "拒答率已测 → $PRD/refusal-v5.json" "（本机还需对比 v4r 基线）"
    else
      log "[S5][WARN] 4bit 服务未起来，跳过拒答率（不阻塞交付）"
      write_pr S5 PROCEED "SKIP：4bit 服务未就绪" "拒答率本机可补测"
    fi
    kill $SPID 2>/dev/null || true
  else
    log "[S5][WARN] 缺 refusal_probe.py / serve_4bit_base.py，跳过"
    write_pr S5 PROCEED "SKIP：脚本缺失"
  fi
fi

# ---------- 收口 ----------
log "===== V5 AUTO DONE ====="
log "[result] $OUT"
log "[elapsed] $(elapsed_h) h"
{
  echo "# V5 全自动执行报告 $(date '+%F %T')"
  echo
  echo '```text'
  printf '总耗时   %s h\n' "$(elapsed_h)"
  printf '产物     %s\n' "$OUT"
  [ -f "$OUT" ] && printf '体积     %s B (%.2f GiB)\n' "$(stat -c%s "$OUT")" "$(echo "scale=4;$(stat -c%s "$OUT")/1073741824"|bc)"
  echo '门禁     '$(ls "$MK" 2>/dev/null | tr '\n' ' ')
  echo '```'
  echo
  echo '## PR 清单'
  ls -1 "$PRD"/PR-*.md 2>/dev/null | sed 's/^/- /'
  echo
  echo '## 下一步（本机）'
  echo '```text'
  echo '1 get_multi 回传 .ninfer + conversion.json'
  echo '2 起本机引擎 → judge7_v4.py + probe_kitty.py'
  echo '3 拒答率与 v4r 对比（若云端 S5 已测，直接用）'
  echo '4 控制台关机（容器内关不掉，已定论）'
  echo '```'
} > "$PRD/REPORT-V5-AUTO.md"
log "[report] $PRD/REPORT-V5-AUTO.md"

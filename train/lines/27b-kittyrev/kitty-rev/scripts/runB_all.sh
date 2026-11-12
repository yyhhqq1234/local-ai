#!/usr/bin/env bash
# =============================================================================
# runB_all.sh —— B 组四套评测一键编排（re60 → bench40 → kitty23 → refusal-100）
#
# 为什么要有这个脚本
#   C 组（base-only）产物已经在 logs/base-only/，B 组要按【逐字段相同的锁参】重跑一遍，
#   每跑一套立刻过 param-gate，不过就停在那一套 —— 不许"先跑完再一起看"。
#   今天三次翻车（F16 think 未关 / F17 max_tokens 未透传 / F24 名单没走到执行路径）
#   全部是"日志说用了参数、实际没生效"，所以每套的判据只看产物，不看日志。
#
# 执行形态（必须写清）：
#   EXEC=remote（默认）—— 走 deploy/remote.py 操作 AutoDL 实例：这是 C 组实际跑的地方
#                        （产物里 data.path 是 /root/autodl-tmp/...），B 组同机同基座才可比。
#                        产物用 remote.py --get 拉回本地再过闸门（闸门在本机跑）。
#   EXEC=local         —— 本机 Windows 直跑 serve_4bit_base.py，12G 卡装 27B 4bit 很吃紧，
#                        只用于排障/自测。两条路径的锁参与判据完全一致。
#
# 前置断言（缺一即 abort，不许"跳过继续"）
#   P1 四份 C 产物存在，且打印 路径 + md5 + 字节
#   P2 adapter 来自 logs/v4/pick.md 的 `[PICK] adapter=` 行（正则抽取，禁止手填）；
#      pick.md 不存在 / 抽不到 / adapter 目录或 adapter_model.safetensors 不存在 → abort
#   P3 评测脚本 sha16 与 C 组记录一致（eval_bare.py 的 sha16 写在 C 产物 eval_meta.eval_bare_md5）
#   P4 serve 起来后 /v1/models 必须包含 B 模型名（名字对不上 = 评的不是这个模型）
#
# 锁参（与 C 逐字段一致）
#   re60      max_tokens 512  tools off  judge expect
#             eval_bare **旧版 1b6ddc28**（C 组 re60 就是它出的，新版行为不同 → 必须用旧版）
#   bench40   max_tokens 256  tools off  judge ref    eval_bare 现行 c9412673
#   kitty23   max_tokens 512  tools on   judge cat    eval_bare 现行 c9412673（--suite kitty23）
#   refusal   max_new   256   --mode text --from-jsonl data/reablit/comply_set.jsonl --limit 100
#             scripts/refusal_probe.py **锁云端 6a778e16**（33,930 B / 618 行 = C 组产出那一版）；
#             本地 5eb7a9cf（35,290 B，修过分母 bug）**不许顶替** —— 同尺优先，
#             跨版本比"率"会把版本差异算成训练效果。
#             读数只认产物：分子=text.refused，分母=text.n_ok，率自算；
#             顶层 comply_n=60 与日志 "60/60" 是已知分母 bug，禁止用来算率。
#   serve     scripts/serve_4bit_base.py --model $R/base/Huihui --name huihui-base --port 18001
#             （默认名会带旧基座路径，protocol.model 与 C 不一致 → 必须显式 --name huihui-base）
#   端口      四套一律 --base http://127.0.0.1:18001（eval 默认 18000，不一致会静默打到空端口）
#
# 每套判据（B 组能不能判读）
#   行式产物三套：python scripts/assert_params_effective.py --gate <B> --baseline <C>
#                 （pair 字段一致 + B 侧 ①⑤④ 自洽；②③ 属 C/B 共有 F16/F17，降级 INFO）
#                 --pair/--gate 只接受**同 suite** 两文件；跨 suite 直接 REFUSED（exit 2）
#   refusal：产物没有 rows[]（只有 text.*），⑤ 结构上不适用 → --pair +
#            硬断言 ① text.n==100 ② text.prompts.list_sha16==c2776c359904d06e ③ 能读出 n_ok/refused
#            任一不过 → 该套 NOT_MEASURED，停后续，不写结论
#   任一不过 → 立刻停在该套，不跑下一套
#
# 产物 / 日志
#   logs/v4/eval-B/<suite>.json      B 套产物（re60/bench40/kitty23/refusal-100）
#   logs/v4/eval-B/<suite>.log       该套原始输出
#   logs/v4/eval-B/run.log           总日志：每套开始/结束时刻 + 条数 + 判定
#   logs/v4/eval-B/serve-B.log        serve 输出
#
# 用法
#   bash scripts/runB_all.sh --dry-run              # 只做前置断言 + 回显四条命令（不跑）
#   bash scripts/runB_all.sh                        # 真跑（remote 形态，batch=1）
#   bash scripts/runB_all.sh --batch-check          # batch 等价性取证：bench40 batch=1 vs 4（纯基座）
#   bash scripts/runB_all.sh --batch 4              # 提速跑（必须先有 --batch-check 的 PASS）
#   EXEC=local bash scripts/runB_all.sh             # 本机形态
#   bash scripts/runB_all.sh --only re60,kitty23    # 断点续跑指定套
#   KEEP_SERVE=1 bash scripts/runB_all.sh           # 跑完不杀 serve
#
# --batch-check（用 32 分钟换 1.5 小时）
#   1) 同一台机、同一基座（不挂 adapter）起两次 serve：--batch 1 与 --batch 4
#   2) bench40 各跑一次 → logs/v4/eval-B/batchcheck/bench40-b1.json / -b4.json
#   3) scripts/batch_equiv_compare.py 三判据，全过才签：
#      G1 pass 向量逐题相同 · G2 mean_f1 **浮点 ==**（不等就打差值并 FAIL）
#      G3 逐题 f1 向量相同（产物没这字段 → 记 UNAVAILABLE，由 G3a head 文本 / G3b chars /
#         G3c 计数三条同源代理顶上；要真比 f1 得先让 eval_* 落逐题 f1，需 lead 批准）
#      另加 G4 顶层同参同尺（suite/judge/data_sha16/max_tokens/tools）
#   4) 结论行：[BATCH-EQUIV] PASS → 其余三套用 batch=4 / FAIL → 全部 batch=1，报告写"提速未采用"
#      退出码 0=PASS / 1=FAIL / 2=端点不通（serve 起不来或模型名不符）
#      结论落盘 logs/v4/eval-B/batchcheck/verdict.json，并被写进每份产物的 eval_meta.batch_evidence
#
# 退出码：0 = 四套全过且 --pair 全一致 / 1 = 某套闸门不过（停在该套）/ 2 = 前置断言失败或端点不通 / 3 = dry-run 前置失败
# 纪律：只写 D:\BaiduNetdiskDownload\Local-AI\ 之内；不改 eval_bare.py / eval_kitty.py / refusal_probe.py
# =============================================================================
set -uo pipefail

# ---------------------------------------------------------------- 绝对路径（禁相对）
export LC_ALL=C
export PYTHONIOENCODING=utf-8        # 管道里的中文证据别被本地 codepage 变成乱码
export PYTHONUTF8=1
PY="C:/ProgramData/anaconda3/python.exe"          # PATH 里的 python 是 0 字节商店别名
KV="D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev"
SD="$KV/scripts"
GATE_PY="$SD/assert_params_effective.py"
EVAL_BARE="$KV/tmp/eval_bare.py"                   # 必须在 tmp/ 下（HERE = 上两级）
EVAL_KITTY="$KV/eval/eval_kitty.py"
REFUSAL="$SD/refusal_probe.py"
SERVE="$SD/serve_4bit_base.py"
REMOTE_PY="$KV/deploy/remote.py"
C_DIR="$KV/logs/base-only"
B_DIR="$KV/logs/v4/eval-B"
PICKMD="$KV/logs/v4/pick.md"
RUNLOG="$B_DIR/run.log"
BC_DIR="$B_DIR/batchcheck"                         # batch 等价性取证目录
BATCH_VERDICT="$BC_DIR/verdict.json"               # 结论落盘（作为产物 batch_evidence）
BATCH_CMP="$SD/batch_equiv_compare.py"             # 三判据比对器（浮点用 ==）

# 远端（AutoDL）绝对路径
RROOT="${RROOT:-/root/autodl-tmp/kitty-rev}"
RKV="$RROOT/kitty-rev"
RPY="${RPY:-/root/miniconda3/bin/python}"
RBASE="${BASE_MODEL:-/root/autodl-tmp/kitty-rev/base/Huihui}"

BASE_URL="http://127.0.0.1:18001"                   # C 组 18000，B 组用 18001（lead 2026-10-22 定）
PORT=18001
B_MODEL="${B_MODEL:-huihui-base}"                  # 必须与 C 的 protocol.model 一致
COMPLY_JSONL="data/reablit/comply_set.jsonl"       # 相对 $KV（命令里显式 cd $KV）
COMPLY_SHA16="c2776c359904d06e"                    # C 组 refusal 的名单 sha16（铁证）
EXEC="${EXEC:-remote}"                             # remote | local
DRY=0
ONLY=""
MODE="run"                                          # run | batchcheck
BATCH="${BATCH:-1}"                                 # >1 必须先把 --batch-check 签成 PASS
KEEP_SERVE="${KEEP_SERVE:-0}"
SUITES_ALL="re60 bench40 kitty23 refusal-100"
SERVE_PID=""
SERVE_BATCH=1
PKG=0                                              # 前置断言失败计数

# ---------------------------------------------------------------- 基础函数
mkdir -p "$B_DIR" 2>/dev/null || { echo "[FATAL] 无法创建 $B_DIR"; exit 2; }
: >>"$RUNLOG"

log() { printf '%s\n' "$*" | tee -a "$RUNLOG"; }
say() { log ""; log "===== [$1] $2 ====="; }
die() { log "[FATAL] $*"; exit 2; }

# md5 + 字节（本机路径；python 统一处理，避开 msys 路径转换）
print_subject() {  # $1=标签 $2=路径
  "$PY" - "$1" "$2" <<'PY'
import hashlib, os, sys
tag, p = sys.argv[1], sys.argv[2]
if not os.path.isfile(p):
    print("  被测文件：%s = %s  [不存在]" % (tag, p)); raise SystemExit(1)
h = hashlib.md5(); sha = hashlib.sha256()
with open(p, "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""):
        h.update(b); sha.update(b)
print("  被测文件：%s = %s  md5=%s  sha16=%s  %d 字节"
      % (tag, p, h.hexdigest(), sha.hexdigest()[:16], os.path.getsize(p)))
PY
}

# 执行一条远端命令；$1=cmd $2=timeout
rex() { "$PY" "$REMOTE_PY" --cmd "$1" --timeout "${2:-3600}"; }

# 按 EXEC 执行一条"评测命令"（命令串用远端绝对路径拼，local 形态同样成立）
xrun() {  # $1=cmd $2=timeout
  if [ "$EXEC" = "remote" ]; then rex "$1" "${2:-3600}"; else bash -c "$1"; fi
}

# 远端文件 md5（remote 形态）/ 本机 md5（local 形态）
art_md5() {  # $1=远端绝对路径
  if [ "$EXEC" = "remote" ]; then
    rex "md5sum $1 2>/dev/null | cut -d' ' -f1" 60 | tr -d '\r' | tail -1
  else
    "$PY" -c "import hashlib,sys;h=hashlib.md5();f=open(sys.argv[1],'rb');[h.update(b) for b in iter(lambda:f.read(1<<20),b'')];print(h.hexdigest())" "$1" 2>/dev/null
  fi
}

# 把远端产物拉回本地（local 形态无需搬）
fetch_art() {  # $1=远端绝对路径 $2=本地路径
  if [ "$EXEC" = "remote" ]; then
    "$PY" "$REMOTE_PY" --get "$1" "$2" || return 1
  fi
  return 0
}

want_suite() { [ -z "$ONLY" ] && return 0; case ",$ONLY," in *",$1,"*) return 0;; *) return 1;; esac; }

# ---------------------------------------------------------------- 参数解析
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --all) MODE="run"; ONLY=""; shift ;;            # 显式别名：四套全跑（等价于不带 --only）
    --batch-check) MODE="batchcheck"; shift ;;
    --batch)   [ $# -ge 2 ] || die "--batch 需要数值"; BATCH="$2"; shift 2 ;;
    --batch=*) BATCH="${1#--batch=}"; shift ;;
    --only)    [ $# -ge 2 ] || die "--only 需要套名"; ONLY="$2"; shift 2 ;;
    --only=*)  ONLY="${1#--only=}"; shift ;;
    re60|bench40|kitty23|refusal-100) ONLY="${ONLY:+$ONLY,}$1"; shift ;;
    -h|--help) sed -n '2,72p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "未知参数：$1（--help 看用法）" ;;
  esac
done
case "$EXEC" in remote|local) ;; *) die "EXEC 只能是 remote 或 local（当前 $EXEC）";; esac
case "$BATCH" in ''|*[!0-9]*) die "--batch 必须是正整数（当前 $BATCH）";; esac
[ "$BATCH" -ge 1 ] || die "--batch 必须 >= 1"

say "00" "B 组编排启动 · EXEC=$EXEC · mode=$MODE · batch=$BATCH · dry_run=$DRY · only=${ONLY:-全部}"
log "  python      = $PY"
log "  闸门        = $GATE_PY"
log "  C 产物目录  = $C_DIR"
log "  B 产物目录  = $B_DIR"
log "  base_url    = $BASE_URL"
log "  B 模型名    = $B_MODEL"

# ---------------------------------------------------------------- P1 四份 C 产物
say "P1" "C 组产物存在性 + md5"
for s in $SUITES_ALL; do
  c="$C_DIR/$s.json"
  if print_subject "C/$s" "$c"; then :; else
    log "  [FAIL] 缺 C 组产物：$c"; PKG=$((PKG+1)); continue
  fi
  if [ "$EXEC" = "local" ]; then
    :  # 本机直接读
  else
    rmd=$(art_md5 "$RKV/logs/base-only/$s.json")
    lmd=$("$PY" -c "import hashlib,sys;h=hashlib.md5();f=open(sys.argv[1],'rb');[h.update(b) for b in iter(lambda:f.read(1<<20),b'')];print(h.hexdigest())" "$c")
    if [ -n "$rmd" ] && [ "$rmd" != "$lmd" ]; then
      log "  [FAIL] C/$s 本地与远端 md5 不一致：local=$lmd remote=$rmd（不是同一份产物）"; PKG=$((PKG+1))
    fi
  fi
done

# ---------------------------------------------------------------- P2 pick.md → adapter
# batchcheck 形态跑的是纯基座（batch 等价性与 adapter 无关，也不该等 pick.md）
if [ "$MODE" = "batchcheck" ]; then
  say "P2" "跳过（batchcheck 用纯基座，不需要 adapter / pick.md）"
  ADAPTER=""
else
say "P2" "adapter 路径必须来自 $PICKMD 的 [PICK] 行（禁止手填）"
ADAPTER=""
if [ ! -f "$PICKMD" ]; then
  log "  [FAIL] 缺 pick.md：$PICKMD"
  log "         先取回（远端生成过才有）："
  if [ "$EXEC" = "remote" ]; then
    log "         \"$PY\" \"$REMOTE_PY\" --get $RROOT/logs/v4/pick.md \"$PICKMD\""
  fi
  PKG=$((PKG+1))
else
  ADAPTER=$("$PY" - "$PICKMD" <<'PY'
import re, sys
t = open(sys.argv[1], encoding="utf-8", errors="replace").read()
m = re.findall(r"^\[PICK\] adapter=(.+)$", t, re.M)
print((m[-1].strip() if m else ""))
PY
)
  if [ -z "$ADAPTER" ]; then
    log "  [FAIL] pick.md 里没有 [PICK] adapter= 行（生成逻辑坏了）"; PKG=$((PKG+1))
  else
    log "  [PICK] adapter = $ADAPTER"
    if [ "$EXEC" = "remote" ]; then
      sz=$(rex "stat -c%s $ADAPTER/adapter_model.safetensors 2>/dev/null || echo MISSING" 60 | tr -d '\r' | tail -1)
      if [ "$sz" = "MISSING" ] || [ -z "$sz" ]; then
        log "  [FAIL] 远端缺 $ADAPTER/adapter_model.safetensors"; PKG=$((PKG+1))
      else
        log "  adapter_model.safetensors = $sz 字节 ✓"
      fi
    else
      if print_subject "adapter" "$ADAPTER/adapter_model.safetensors"; then :; else
        log "  [FAIL] 本机缺 adapter_model.safetensors"; PKG=$((PKG+1)); fi
    fi
  fi
fi
fi   # MODE != batchcheck

# ---------------------------------------------------------------- P3 评测脚本同一把尺子
say "P3" "评测脚本尺子（C 组记录：re60 用 eval_bare@1b6ddc28，bench/kitty 用 c9412673）"
BARE_STD_MD5="c9412673747cc10c65b46a6a8f4b80c6"      # 现存 tmp/eval_bare.py（bench/kitty 用）
BARE_RE60_MD5="1b6ddc2831cc97ea8fd4b7b0374078dc"    # C 组 re60 用的旧版
BARE_RE60_SRC="$KV/tmp/audit/eval_bare.old-1b6ddc28.py"
BARE_RE60="$KV/tmp/eval_bare.re60.py"                # 必须放在 tmp/ 下（HERE=上两级）
RBARE_STD="$RKV/tmp/eval_bare.py"
RBARE_RE60="$RKV/tmp/eval_bare.re60.py"

md5_of() { "$PY" -c "import hashlib,sys;h=hashlib.md5();f=open(sys.argv[1],'rb');[h.update(b) for b in iter(lambda:f.read(1<<20),b'')];print(h.hexdigest())" "$1" 2>/dev/null; }

# (a) 标准尺子 tmp/eval_bare.py
print_subject "eval_bare(std)" "$EVAL_BARE" || { log "  [FAIL] 缺 $EVAL_BARE"; PKG=$((PKG+1)); }
L_STD=$(md5_of "$EVAL_BARE")
[ "$L_STD" = "$BARE_STD_MD5" ] || { log "  [FAIL] 本机 tmp/eval_bare.py md5=$L_STD != $BARE_STD_MD5"; PKG=$((PKG+1)); }

# (b) re60 旧尺子：从备份字节级复制到 tmp/ 下（同名同级，HERE 才对），md5 校验
if [ ! -f "$BARE_RE60_SRC" ]; then
  log "  [FAIL] 缺 re60 尺子源：$BARE_RE60_SRC"; PKG=$((PKG+1))
else
  if ! cmp -s "$BARE_RE60_SRC" "$BARE_RE60" 2>/dev/null; then
    cp -f "$BARE_RE60_SRC" "$BARE_RE60" || { log "  [FAIL] 复制 re60 尺子失败"; PKG=$((PKG+1)); }
    log "  [stage] 复制 $BARE_RE60_SRC → $BARE_RE60"
  fi
  print_subject "eval_bare(re60)" "$BARE_RE60" || PKG=$((PKG+1))
  L_R60=$(md5_of "$BARE_RE60")
  [ "$L_R60" = "$BARE_RE60_MD5" ] || { log "  [FAIL] re60 尺子 md5=$L_R60 != $BARE_RE60_MD5"; PKG=$((PKG+1)); }
fi

# (c) 远端两份尺子必须与本地逐字节一致（remote 形态）
if [ "$EXEC" = "remote" ]; then
  R_STD=$(rex "md5sum $RBARE_STD 2>/dev/null | cut -d' ' -f1" 60 | tr -d '\r' | tail -1)
  log "  远端 $RBARE_STD md5=${R_STD:-<缺>}（期望 $BARE_STD_MD5）"
  [ "$R_STD" = "$BARE_STD_MD5" ] || {
    log "  [FAIL] 远端标准尺子不符 —— push 后再跑："
    log "         \"$PY\" \"$REMOTE_PY\" --put \"$EVAL_BARE\" \"$RBARE_STD\""
    PKG=$((PKG+1)); }
  R_R60=$(rex "md5sum $RBARE_RE60 2>/dev/null | cut -d' ' -f1" 60 | tr -d '\r' | tail -1)
  log "  远端 $RBARE_RE60 md5=${R_R60:-<缺>}（期望 $BARE_RE60_MD5）"
  if [ "$R_R60" != "$BARE_RE60_MD5" ]; then
    if [ "$DRY" -eq 1 ]; then
      log "  [dry] 真跑时会 push re60 尺子：本地 $BARE_RE60 → 远端 $RBARE_RE60（当前 ${R_R60:-缺}）"
    else
      log "  [stage] 推送 re60 尺子到远端（远端当前 = ${R_R60:-缺}）"
      if "$PY" "$REMOTE_PY" --put "$BARE_RE60" "$RBARE_RE60" >>"$RUNLOG" 2>&1; then
        R_R60=$(rex "md5sum $RBARE_RE60 2>/dev/null | cut -d' ' -f1" 60 | tr -d '\r' | tail -1)
        [ "$R_R60" = "$BARE_RE60_MD5" ] || { log "  [FAIL] push 后 md5 仍不符：$R_R60"; PKG=$((PKG+1)); }
      else
        log "  [FAIL] push 失败"; PKG=$((PKG+1))
      fi
    fi
  fi
fi

# (d) refusal_probe：用**本地 5eb7a9cf**（与云端旧版 6a778e16 在第 1-462 行逐字节相同 ⇒
#     拒答判定严格等价；差别只在仪表：本地版有 text.n_ok / n_err / partial）。
#     跑前必须把本地版 push 到云端并断言远端 md5 == 5eb7a9cf（防远端残留旧版）。
print_subject "refusal_probe(local)" "$REFUSAL" || { log "  [FAIL] 缺 $REFUSAL"; PKG=$((PKG+1)); }
PROBE_MD5="842c9e37ba53e22a771f70da0fbe5d38"        # 本地版 + --dump-answers（判分与 5eb7a9cf 逐字节一致）
L_PROBE=$(md5_of "$REFUSAL")
log "  本地 refusal_probe md5 = ${L_PROBE:-<缺>}（期望 $PROBE_MD5）"
[ "$L_PROBE" = "$PROBE_MD5" ] || { log "  [FAIL] 本地 probe md5 不符 → 停"; PKG=$((PKG+1)); }

if [ "$EXEC" = "remote" ]; then
  R_PROBE=$(rex "md5sum $RKV/scripts/refusal_probe.py 2>/dev/null | cut -d' ' -f1" 60 | tr -d '\r' | tail -1)
  log "  远端 $RKV/scripts/refusal_probe.py md5 = ${R_PROBE:-<缺>}（期望 $PROBE_MD5）"
  if [ "$R_PROBE" != "$PROBE_MD5" ]; then
    if [ "$DRY" -eq 1 ]; then
      log "  [dry] 真跑时会：备份远端旧版 → push 本地 5eb7a9cf → 断言远端 md5（当前 ${R_PROBE:-缺}）"
    else
      [ -n "$R_PROBE" ] && rex "cp -f $RKV/scripts/refusal_probe.py $RKV/scripts/refusal_probe.py.bak-$(printf '%s' "$R_PROBE" | cut -c1-8)" 60 >/dev/null 2>&1
      log "  [stage] push 本地 probe → 远端（旧版已备份 .bak-${R_PROBE:0:8}）"
      if "$PY" "$REMOTE_PY" --put "$REFUSAL" "$RKV/scripts/refusal_probe.py" >>"$RUNLOG" 2>&1; then
        R_PROBE=$(rex "md5sum $RKV/scripts/refusal_probe.py 2>/dev/null | cut -d' ' -f1" 60 | tr -d '\r' | tail -1)
        if [ "$R_PROBE" = "$PROBE_MD5" ]; then
          log "  [PASS] 远端 push 后 refusal_probe.md5 == $PROBE_MD5 ✓"
        else
          log "  [FAIL] push 后远端 md5 仍不符：${R_PROBE:-缺}"; PKG=$((PKG+1))
        fi
      else
        log "  [FAIL] push 失败（$REMOTE_PY --put）"; PKG=$((PKG+1))
      fi
    fi
  else
    log "  [PASS] 远端已是 $PROBE_MD5 ✓"
  fi
else
  [ "$L_PROBE" = "$PROBE_MD5" ] || { log "  [FAIL] local 形态要求本地 probe == $PROBE_MD5"; PKG=$((PKG+1)); }
fi
print_subject "eval_kitty(std)" "$EVAL_KITTY" || log "  [warn] 本机缺 eval_kitty.py（remote 形态用远端的）"
print_subject "serve" "$SERVE" || { log "  [FAIL] 缺 $SERVE"; PKG=$((PKG+1)); }
print_subject "闸门" "$GATE_PY" || { log "  [FAIL] 缺 $GATE_PY"; PKG=$((PKG+1)); }

# ---------------------------------------------------------------- 四条命令（锁参）
cmd_re60()  { echo "$1 $2/tmp/eval_bare.re60.py --suite re60 --base $BASE_URL --model $B_MODEL --max-tokens 512 --tools off --sys kitty --prompt history --judge expect --timeout 300 --out $3/re60.json --tag eval-B"; }
cmd_bench40(){ echo "$1 $2/tmp/eval_bare.py --suite bench40 --base $BASE_URL --model $B_MODEL --max-tokens 256 --tools off --sys kitty --prompt history --judge ref --timeout 300 --out $3/bench40.json --tag eval-B"; }
cmd_kitty23(){ echo "$1 $2/tmp/eval_bare.py --suite kitty23 --base $BASE_URL --model $B_MODEL --max-tokens 512 --tools on --sys kitty --prompt history --judge cat --timeout 300 --out $3/kitty23.json --tag eval-B"; }
# bench40 可换输出文件名（batchcheck 要 bench40-b1/-b4 两份）
cmd_bench40_to(){ echo "$1 $2/tmp/eval_bare.py --suite bench40 --base $BASE_URL --model $B_MODEL --max-tokens 256 --tools off --sys kitty --prompt history --judge ref --timeout 300 --out $3/$4 --tag eval-B"; }
# refusal：与 C 组逐字段一致（--from-jsonl + --limit 100，绝不用内联 COMPLY）
#  --dump-answers：把 100 条回答**全文**落 sidecar jsonl（污染检测用）；不新增产物键、不动分母
cmd_refusal(){ echo "cd $2 && $1 $2/scripts/refusal_probe.py --mode text --base $BASE_URL --from-jsonl $COMPLY_JSONL --limit 100 --max-new 256 --dump-answers $3/refusal-100.answers.jsonl --out $3/refusal-100.json"; }

# 远端 / 本机根：命令里统一用 $RKV 或 $KV
if [ "$EXEC" = "remote" ]; then RT="$RKV"; RP="$RPY"; RA="$RKV/logs/v4/eval-B"; PA="$B_DIR"
else RT="$KV"; RP="$PY"; RA="$B_DIR"; PA="$B_DIR"; fi

C_re60=$(cmd_re60 "$RP" "$RT" "$RA")
C_bench40=$(cmd_bench40 "$RP" "$RT" "$RA")
C_kitty23=$(cmd_kitty23 "$RP" "$RT" "$RA")
C_refusal=$(cmd_refusal "$RP" "$RT" "$RA")

# ---------------------------------------------------------------- 前置失败处理
if [ "$PKG" -gt 0 ]; then
  say "PREFLIGHT" "FAIL（$PKG 项）"
  log "  将执行的四条命令（未执行）："
  log "    $C_re60"
  log "    $C_bench40"
  log "    $C_kitty23"
  log "    $C_refusal"
  if [ "$DRY" -eq 1 ]; then
    log "  末尾污染检测步骤（未执行）："
    log "    $PY $SD/check_contam_v4.py --all-suites --json $B_DIR/contam-all.json --dump-hits $B_DIR/contam-hits.jsonl"
    log "  [dry] 该步 FAIL 不阻断交付：只醒目打印 + 写 run.log + 进交付包清单"
    exit 3
  fi
  die "前置断言未通过 —— 不跑任何一套（不许跳过继续）"
fi
say "PREFLIGHT" "PASS —— 四套命令均核到实物（C 产物 / pick.md / adapter / 评测脚本 / 闸门 / serve）"
log "    $C_re60"
log "    $C_bench40"
log "    $C_kitty23"
log "    $C_refusal"

# ---------------------------------------------------------------- P4 serve + /v1/models
# start_serve [batch] [base_only]
#   batch     serve --batch（默认 $BATCH；batchcheck 形态显式传 1 / 4）
#   base_only "1" = 不挂 adapter（batchcheck 用纯基座，与 C 组同形）
start_serve() {
  local sb="${1:-$BATCH}" bo="${2:-0}"
  SERVE_BATCH="$sb"
  local ad=""
  [ "$bo" = "1" ] || ad="$ADAPTER"
  say "P4" "起 serve（EXEC=$EXEC · batch=$sb${ad:+ · adapter=$ad}）并断言 /v1/models 含 $B_MODEL"
  log "  serve 实物 = $RKV/scripts/serve_4bit_base.py（不是 tmp/）"
  log "  --model $RBASE ${ad:+--adapter $ad }--name $B_MODEL --port $PORT --batch $sb"
  if [ "$EXEC" = "remote" ]; then
    rex "ss -lntp 2>/dev/null | grep -q ':$PORT ' && echo PORT_BUSY || echo PORT_FREE" 60 \
      | tee -a "$RUNLOG" | grep -q PORT_BUSY && die "远端 $PORT 已被占用（先停掉旧 serve，避免评到别的模型）"
    "$PY" "$REMOTE_PY" --bg "$RPY $RKV/scripts/serve_4bit_base.py --model $RBASE ${ad:+--adapter $ad }--port $PORT --host 127.0.0.1 --name $B_MODEL --batch $sb --batch-wait-ms 200" \
       --log "$RA/serve-B.log" || die "serve 启动命令失败"
  else
    "$PY" "$SERVE" --model "$RBASE" ${ad:+--adapter "$ad"} --port "$PORT" --host 127.0.0.1 --name "$B_MODEL" --batch "$sb" --batch-wait-ms 200 \
      > "$B_DIR/serve-B.log" 2>&1 &
    SERVE_PID=$!
    log "  local serve pid=$SERVE_PID"
  fi

  local i ok=1 got=""
  for i in $(seq 1 90); do
    got=$(rex "$RPY -c \"import json,urllib.request;d=json.load(urllib.request.urlopen('$BASE_URL/v1/models',timeout=5));print(','.join(str(m.get('id')) for m in d.get('data',[])))\"" 60 2>/dev/null | tr -d '\r' | tail -1)
    if [ -n "$got" ]; then ok=0; break; fi
    sleep 2
  done
  if [ "$ok" -ne 0 ]; then
    # 端点不通 → exit 2（与 batchcheck 的退出码约定一致）
    log "  [FATAL] serve 180 秒内没起来（端点不通，看 $B_DIR/serve-B.log）"
    exit 2
  fi
  log "  /v1/models = [$got]"
  case ",$got," in
    *",$B_MODEL,"*) log "  [PASS] 模型名一致：$B_MODEL" ;;
    *) log "  [FATAL] 模型名不一致：期望 $B_MODEL，实际 [$got]（评错模型 = 结论作废）"; exit 2 ;;
  esac
}

stop_serve() {
  if [ "$EXEC" = "remote" ]; then
    rex "pkill -f serve_4bit_base.py || true" 60 >/dev/null 2>&1
    local i
    for i in $(seq 1 30); do
      rex "ss -lntp 2>/dev/null | grep -q ':$PORT ' && echo BUSY || echo FREE" 30 2>/dev/null \
        | tr -d '\r' | grep -q FREE && break
      sleep 2
    done
    log "  serve 已停（远端，端口 $PORT 已释放）"
  else
    [ -n "$SERVE_PID" ] && kill "$SERVE_PID" 2>/dev/null || true
    sleep 1
    log "  serve 已停（local pid=$SERVE_PID）"
  fi
  SERVE_PID=""
}

trap 'if [ -n "$SERVE_PID" ] && [ "$KEEP_SERVE" -eq 0 ]; then kill "$SERVE_PID" 2>/dev/null || true; fi' EXIT

# ---------------------------------------------------------------- 产物批注（batch / batch_evidence）
annotate_artifact() {  # $1=本地产物 $2=batch $3=evidence 路径
  "$PY" - "$1" "$2" "$3" <<'PY' | tee -a "$RUNLOG"
import json, os, shutil, sys, time
p, batch, evidence = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(p, encoding="utf-8"))
raw = p + ".raw.json"
if not os.path.exists(raw):
    shutil.copyfile(p, raw)          # 原始产物留档，批注可回滚
m = d.get("eval_meta")
if not isinstance(m, dict):
    m = d["eval_meta"] = {}
concl = None
if os.path.isfile(evidence):
    try:
        concl = json.load(open(evidence, encoding="utf-8")).get("conclusion")
    except Exception:
        concl = None
m["batch"] = int(batch)
m["batch_evidence"] = evidence if int(batch) > 1 else None
m["batch_equiv"] = concl if int(batch) > 1 else "n/a (batch=1 基线)"
m["annotated_by"] = "runB_all.sh"
m["annotated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
print("  [annotate] %s ← batch=%s batch_equiv=%s（原始留档 %s）"
      % (os.path.basename(p), batch, m["batch_equiv"], os.path.basename(raw)))
PY
}

# ---------------------------------------------------------------- --batch-check
# 用 32 分钟换 1.5 小时：bench40 在 batch=1 / batch=4 下各跑一次，三判据全过才签 batch=4
batch_check() {
  mkdir -p "$BC_DIR"
  say "BC" "batch 等价性取证：bench40 batch=1 vs batch=4（纯基座，端口 $PORT）"
  local b cmd_r cmd_l rc=0
  if [ "$DRY" -eq 1 ]; then
    for b in 1 4; do
      log "  [dry] serve --batch $b → $(cmd_bench40_to "$RP" "$RT" "$RA/batchcheck" "bench40-b$b.json")"
    done
    log "  [dry] 比对：$PY $BATCH_CMP $BC_DIR/bench40-b1.json $BC_DIR/bench40-b4.json --out $BATCH_VERDICT --why"
    return 0
  fi

  rex "mkdir -p $RA/batchcheck" 60 >/dev/null 2>&1

  for b in 1 4; do
    stop_serve
    start_serve "$b" 1
    cmd_r=$(cmd_bench40_to "$RP" "$RT" "$RA/batchcheck" "bench40-b$b.json")
    log "  [batch=$b] $(date '+%Y-%m-%d %H:%M:%S') START"
    log "  命令：$cmd_r"
    xrun "$cmd_r" 3600
    rc=$?
    log "  [batch=$b] $(date '+%Y-%m-%d %H:%M:%S') END exit=$rc"
    fetch_art "$RA/batchcheck/bench40-b$b.json" "$BC_DIR/bench40-b$b.json" \
      || { log "  [FATAL] batch=$b 产物取回失败"; return 2; }
    print_subject "bench40-b$b" "$BC_DIR/bench40-b$b.json" || { log "  [FATAL] batch=$b 无产物"; return 2; }
  done
  stop_serve

  say "BC" "三判据比对（pass 向量 / mean_f1 浮点 == / 逐题 f1 或代理）"
  "$PY" "$BATCH_CMP" "$BC_DIR/bench40-b1.json" "$BC_DIR/bench40-b4.json" \
        --out "$BATCH_VERDICT" --why 2>&1 | tee -a "$RUNLOG"
  rc=${PIPESTATUS[0]}
  log "  verdict 落盘 → $BATCH_VERDICT"
  return "$rc"
}

# ---------------------------------------------------------------- 单套执行 + 过闸
run_one() {  # $1=suite $2=命令
  local s=$1 cmd=$2 t0 t1 art_r art_l n
  art_r="$RA/$s.json"; art_l="$PA/$s.json"
  t0=$(date '+%Y-%m-%d %H:%M:%S')
  say "$s" "START $t0"
  log "  命令：$cmd"

  if [ "$DRY" -eq 1 ]; then log "  [dry] 跳过执行"; return 0; fi

  xrun "$cmd" 5400
  local rc=$?
  t1=$(date '+%Y-%m-%d %H:%M:%S')
  log "  结束：$t1  exit=$rc"

  fetch_art "$art_r" "$art_l" || { log "  [FAIL] 产物取回失败：$art_r"; return 1; }
  print_subject "$s" "$art_l" || { log "  [FAIL] 本地无产物"; return 1; }
  annotate_artifact "$art_l" "$BATCH" "$BATCH_VERDICT"

  n=$("$PY" -c "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'));r=d.get('rows');t=(d.get('text') or {});print(len(r) if isinstance(r,list) else (t.get('n') if isinstance(t,dict) else (d.get('n') or 0)))" "$art_l" 2>/dev/null)
  log "  条数：${n:-?}"
  log "  行：$s / START=$t0 / END=$t1 / exit=$rc / n=${n:-?} / 产物=$art_l"

  # ---- 每套立刻过闸 ----
  log "  --- 闸门 ---"
  if [ "$s" = "refusal-100" ]; then
    # refusal 产物无 rows[]（只有 text.*），⑤ 结构上不适用 → pair + 三条硬断言
    log "  [note] refusal 无 rows[]：用 --pair 比字段 + 硬断言（⑤ 不适用）"
    log "  [note] 已知分母 bug：顶层 comply_n 与日志 \"60/60\" 取自 len(COMPLY)，禁止用它们算拒答率（只看 text.n / text.refused）"
    "$PY" "$GATE_PY" --pair "$C_DIR/$s.json" "$art_l" 2>&1 | tee -a "$RUNLOG"
    local prc=${PIPESTATUS[0]}
    [ "$prc" -eq 0 ] || { log "  [FAIL] pair 不一致 → NOT_MEASURED，停在该套"; return 1; }
    "$PY" - "$art_l" "$COMPLY_SHA16" <<'PY' 2>&1 | tee -a "$RUNLOG"
import json, sys
p, want = sys.argv[1], sys.argv[2]
d = json.load(open(p, encoding="utf-8"))
t = d.get("text") or {}
pr = t.get("prompts") or {}
n = t.get("n")
sha = pr.get("list_sha16")
n_ok = t.get("n_ok")            # 只认 text.n_ok（本地 5eb7a9cf 才写这个字段）
n_err = t.get("n_err")
refused = t.get("refused")
if isinstance(refused, list):
    refused = len(refused)

print("  ① text.n =", n, "(期望 100)")
print("  ② text.prompts.list_sha16 =", sha, "(期望 %s)" % want)
print("  ③ text.n_ok =", n_ok, "(期望 100；本地 5eb7a9cf 才有该字段)")
if n_err not in (None, 0):
    print("  [warn] text.n_err =", n_err, "→ 报告注明「分母 n_ok，云端旧版会稀释失败」")
if d.get("comply_n") is not None:
    print("  [note] 顶层 comply_n=%r 与日志里的 \"60/60\" 是硬编码假值（取自 len(COMPLY)=60），"
          "两版都是，禁止用来算率" % (d.get("comply_n"),))

bad = []
if n != 100: bad.append("① text.n!=100")
if str(sha) != want: bad.append("② list_sha16 不符")
if n_ok is None: bad.append("③ 无 text.n_ok（跑到了云端旧版？）")
elif n_ok != 100: bad.append("③ text.n_ok!=100")
if isinstance(refused, int) and isinstance(n_ok, int) and n_ok > 0:
    print("  读数（只认产物）：refused=%d / n_ok=%d → 率=%.2f%%（自算，脚本 rate=%r 仅对照）"
          % (refused, n_ok, 100.0 * refused / n_ok, t.get("refusal_rate")))
else:
    bad.append("③ refused/n_ok 读不出（产物字段缺失）")
print("  RESULT:", "PASS" if not bad else "FAIL 未过：" + "; ".join(bad))
raise SystemExit(0 if not bad else 1)
PY
    [ "${PIPESTATUS[0]}" -eq 0 ] || { log "  [FAIL] refusal-100 硬断言未过 → NOT_MEASURED，停在该套，不写结论"; return 1; }
    log "  [PASS] refusal-100 过闸（pair 一致 + n=100 + list_sha16 一致 + text.n_ok=100）"
  else
    "$PY" "$GATE_PY" --gate "$art_l" --baseline "$C_DIR/$s.json" 2>&1 | tee -a "$RUNLOG"
    local grc=${PIPESTATUS[0]}
    [ "$grc" -eq 0 ] || { log "  [FAIL] 闸门不过，停在该套（不跑下一套）"; return 1; }
    log "  [PASS] $s 过闸"
  fi
  return 0
}

# ---------------------------------------------------------------- 主流程
# batchcheck 形态：纯基座跑两遍 bench40 → 三判据 → exit 0/1/2
if [ "$MODE" = "batchcheck" ]; then
  batch_check
  exit $?
fi

# batch>1 必须先有 PASS 的等价性结论，否则不许提速
if [ "$BATCH" -gt 1 ]; then
  VERDICT_LINE=$("$PY" -c "import json,sys,os;p=sys.argv[1];print(json.load(open(p,encoding='utf-8')).get('conclusion','') if os.path.isfile(p) else '')" "$BATCH_VERDICT" 2>/dev/null)
  case "$VERDICT_LINE" in
    *"PASS"*) log "[BATCH] 已有等价性结论：$VERDICT_LINE（evidence=$BATCH_VERDICT）" ;;
    *) die "batch=$BATCH 未取证：先跑 bash scripts/runB_all.sh --batch-check（当前结论=${VERDICT_LINE:-无}）" ;;
  esac
fi

start_serve "$BATCH" 0

FAILED=""
for s in $SUITES_ALL; do
  want_suite "$s" || { log "[skip] $s（--only 未选）"; continue; }
  case "$s" in
    re60)        run_one re60 "$C_re60" || { FAILED=$s; break; } ;;
    bench40)     run_one bench40 "$C_bench40" || { FAILED=$s; break; } ;;
    kitty23)     run_one kitty23 "$C_kitty23" || { FAILED=$s; break; } ;;
    refusal-100) run_one refusal-100 "$C_refusal" || { FAILED=$s; break; } ;;
  esac
done

if [ -n "$FAILED" ]; then
  say "STOP" "停在该套：$FAILED —— 后续套未执行"
  log "  修好后断点续跑：bash scripts/runB_all.sh --only $FAILED"
fi

# ---------------------------------------------------------------- 四次 --pair 对齐表
if [ "$DRY" -eq 1 ]; then
  say "TABLE" "[dry] 未执行，跳过对齐表"
  say "CONTAM" "[dry] 不执行（只回显）：$PY $SD/check_contam_v4.py --all-suites --json $B_DIR/contam-all.json --dump-hits $B_DIR/contam-hits.jsonl"
  log "  [dry] 真跑时该步 FAIL 不阻断交付：只醒目打印 + 写 run.log + 进交付包清单"
  exit 0
fi

say "TABLE" "C vs B 四次 --pair 对齐表"
printf '%-12s %-18s %-18s %-6s %s\n' "suite" "C_md5" "B_md5" "一致" "差异字段" | tee -a "$RUNLOG"
TABLE_BAD=0
for s in $SUITES_ALL; do
  c="$C_DIR/$s.json"; b="$PA/$s.json"
  if [ ! -f "$b" ]; then
    printf '%-12s %-18s %-18s %-6s %s\n' "$s" "$(art_md5 "$c")" "-" "NO" "B 产物缺失" | tee -a "$RUNLOG"
    TABLE_BAD=$((TABLE_BAD+1)); continue
  fi
  out=$("$PY" "$GATE_PY" --pair "$c" "$b" 2>&1)
  echo "$out" >>"$RUNLOG"
  pair=$(printf '%s' "$out" | grep -o 'PAIR=[A-Z]*' | head -1 | cut -d= -f2)
  diff=$(printf '%s' "$out" | grep -o '不一致字段: [^)]*' | head -1 | sed 's/不一致字段: //')
  same="YES"; [ "$pair" = "DIVERGENT" ] && { same="NO"; TABLE_BAD=$((TABLE_BAD+1)); }
  printf '%-12s %-18s %-18s %-6s %s\n' "$s" "$(art_md5 "$c")" "$(art_md5 "$b")" "$same" "${diff:-无}" | tee -a "$RUNLOG"
done

# ---------------------------------------------------------------- (e) 污染检测（只读，不改产物；FAIL 不阻断交付）
# 为什么串在这里：B 组四套落盘后没人记得手动跑 check_contam_v4 → 污染证据就丢了。
# 判据性质：污染是"结论能不能信"的判据，不是"产物是否有效"的判据 ⇒ 不阻断，但必须醒目 + 进交付包清单。
CONTAM_JSON="$B_DIR/contam-all.json"
CONTAM_HITS="$B_DIR/contam-hits.jsonl"
CONTAM_LINE=""
CONTAM_RC=0
say "CONTAM" "污染检测（只读；FAIL 不阻断交付，但必须写进交付包清单）"
if [ ! -f "$SD/check_contam_v4.py" ]; then
  log "  [CONTAM][FAIL] 缺 $SD/check_contam_v4.py → 本轮无污染证据（不影响产物有效性，但结论须标注「污染未测」）"
  CONTAM_RC=99
else
  CONTAM_OUT=$("$PY" "$SD/check_contam_v4.py" --all-suites \
                 --json "$CONTAM_JSON" --dump-hits "$CONTAM_HITS" 2>&1)
  CONTAM_RC=$?
  printf '%s\n' "$CONTAM_OUT" | tee -a "$RUNLOG"
  CONTAM_LINE=$(printf '%s\n' "$CONTAM_OUT" | grep '^\[CONTAM-ALL\] 四套合计' | head -1)
  [ -n "$CONTAM_LINE" ] || CONTAM_LINE="[CONTAM-ALL] （未打印合计行 rc=$CONTAM_RC）"
  log "  [CONTAM] rc=$CONTAM_RC  json=$CONTAM_JSON  hits=$CONTAM_HITS"
  [ "$CONTAM_RC" -eq 0 ] || log "  [CONTAM][WARN] 检测器非 0 退出（rc=$CONTAM_RC）→ 不阻断，但交付包清单要写「污染检测异常」"
fi
# 答案级污染：refusal sidecar 存在才有得测（题目级 ≠ 答案级）
if [ -f "$PA/refusal-100.answers.jsonl" ]; then
  log "  [CONTAM] 发现 $PA/refusal-100.answers.jsonl（$(wc -l < "$PA/refusal-100.answers.jsonl") 条全文）→ 需追加跑答案级污染比对（非题目级）"
else
  log "  [CONTAM] 无 refusal-100.answers.jsonl → 答案级污染本轮不可测（题目级结论不得外推为答案级）"
fi

say "DONE" "B 组编排结束 · 停住套=${FAILED:-无} · 对齐表不一致=${TABLE_BAD} · 污染 rc=${CONTAM_RC}"

# ---- run.log 末尾原样复述污染合计行 + 判定指引（这两行是给人看的，不许省）----
log ""
log "$CONTAM_LINE"
log "[CONTAM-GUIDE] 若 4871−4388 ≥ 2 → 按 B-OUTCOME-MATRIX M9-2：必须重跑那几题取全文，不得直接下\"记忆\"结论"
log "[CONTAM-GUIDE] 若 refusal 侧有 refusal-100.answers.jsonl → 追加跑一次（答案级污染，非题目级）"

[ -z "$FAILED" ] && [ "$TABLE_BAD" -eq 0 ] && exit 0
exit 1

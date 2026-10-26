#!/usr/bin/env bash
# =============================================================================
# v4_pick.sh —— v4 训完后的 checkpoint 选优（v3 的 245/490/full3ep 教训）
#
# 为什么必须有这一步
#   v3 的 entropy 轨迹 1.401 → 0.288 → 0.393 → 0.2591 是典型的 memory 型拟合：
#   loss 好看，能力可能在退。当时靠 pick_checkpoint 三候选对比才没直接交付过拟合版。
#   v4 的编排脚本如果 S4 训完直接 merge out-v4/adapter，就等于把这条保险拆了。
#
# 判据优先级（本关口径，写死在这里，不靠人记）
#   ① eval_re 60 通过数（能力，主判据）
#   ② re60 上的配对翻正数 wins-losses（A 过而 B fail 的题数）
#   ③ eval_kitty 23 通过数（回归守卫）
#   ④ 步数升序（同分选训得少的那个）
#   ⚠ **val loss 已从排序里彻底移除**：re-subset.val 72 行 100% 落在训练集内（F3），
#     它衡量的是"背得熟不熟"。re60 差分噪声 ±3 题，三候选极易打平；打平后若用 val loss
#     收尾，等于系统性把最过拟合的 epoch 推上 merge（v3 的 entropy 末点最低就是同形）。
#   注：pick_checkpoint.py 自己的排序是 re > kitty > val_loss（含已弃用键）；本脚本按上面
#       口径重排，并把两套排序的差异打印出来（有分歧时人能看到，不是悄悄覆盖）。
#
#   ⚠ ④ 为什么是「步数升序」，而**不**上「末点硬否决」（lead 2026-10-22 决定）：
#     ① 只有 3 个候选，硬否决规则无法被验证 —— 它本身又是一个没有判据支撑的先验
#     ② ④ 步数升序已经实现了同样的偏好，而且单调、可解释
#     ③ 若要更强，正确做法是"增加候选数量"或"用更长训练看曲线"，不是加一条拍出来的规则
#     ④ 代价对比：选错 = ¥4-6 且产物上看不出；加错规则 = 长期系统性偏差，更难发现
#   若胜负最终由 ④ 决出（前三键全平），pick.md 与 stdout 会打 [pick][NOTE]：
#     该选择是 **prior-driven（抗过拟合先验）**，不是 evidence-driven（数据支持），
#     结论里不许写成"更早的 checkpoint 实测更优"。
#
# 产物
#   logs/v4/pick/<候选>.json     每个候选的完整结果（pick_checkpoint 写）
#   logs/v4/pick/_summary.json   工具自己的汇总
#   logs/v4/pick.md              人读 + 机器读：表 + `[PICK] adapter=<绝对路径>`
#   → 七步的 merge 读最后这一行（run_after_expand.sh 顶部 awk 解析）
#
# 用法
#   bash cloud/v4_pick.sh                 # 真跑（要 GPU，4bit 加载一次/候选）
#   bash cloud/v4_pick.sh --dry-run       # 只校验路径与套件，不加载模型
#   bash cloud/v4_pick.sh --candidates "490:$ROOT/out-v4/checkpoint-490,735:$ROOT/out-v4/checkpoint-735"
# =============================================================================
set -eu
# 子进程 python 一律 UTF-8：pick_checkpoint 会打 ✓/✗，Windows 控制台默认 GBK 会 UnicodeEncodeError
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

R=${ROOT:-/root/autodl-tmp/kitty-rev}
KV=$R/kitty-rev
PY=${PYTHON:-/root/miniconda3/bin/python}
BASE=${BASE:-$R/base/Huihui}
OUTV4=${OUTV4:-$KV/out-v4}
PICKDIR=${PICKDIR:-$R/logs/v4/pick}
PICKMD=${PICKMD:-$R/logs/v4/pick.md}
CTX=${CTX:-4096}
GPU_MIN_FREE=${GPU_MIN_FREE:-20000}   # pick 要 4bit 加载 ~18 GiB；本机自测可 GPU_MIN_FREE=1
TRAIN_DATA=${TRAIN_DATA:-$KV/data/large-mix-plus/train.jsonl,$KV/data/subsets/forge-subset.train.jsonl}
RE_EVAL=$KV/data/eval_re_extended.jsonl
KITTY_EVAL=$KV/data/eval.jsonl
VAL_DATA=$KV/data/subsets/re-subset.val.jsonl,$KV/data/subsets/forge-subset.val.jsonl
CANDS=""
DRY=0
REFRESH=1

for arg in "$@"; do
  case "$arg" in
    --dry-run)   DRY=1 ;;
    --no-refresh) REFRESH=0 ;;
    --candidates) CANDS=$2; shift ;;
    --ctx)       CTX=$2; shift ;;
    --out)       PICKDIR=$2; shift ;;
    -h|--help)   sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "[FATAL] 未知参数：$arg（--help 看用法）"; exit 2 ;;
  esac
  shift || true
done

say()  { printf '\n===== [%s] %s =====\n' "$(date +%H:%M:%S)" "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '\n[FATAL] %s\n' "$*" >&2; exit 2; }

gpu_free_mib() {
  command -v nvidia-smi >/dev/null 2>&1 || { echo ""; return 0; }
  nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null \
    | head -1 | tr -dc '0-9'
}

say "v4 选优 · dry_run=$DRY"
note "base      = $BASE"
note "候选根    = $OUTV4"

[ -f "$KV/scripts/pick_checkpoint.py" ] || die "缺 $KV/scripts/pick_checkpoint.py"
[ -f "$BASE/config.json" ] || die "缺 $BASE/config.json（基座没下完？）"
for f in "$RE_EVAL" "$KITTY_EVAL"; do
  [ -f "$f" ] || die "缺评测集 $f"
done
# --val-data 是逗号列表：任一缺失 pick_checkpoint 会 FATAL，这里先查，报得更早
for f in $(echo "$VAL_DATA" | tr ',' ' '); do
  [ -f "$f" ] || die "缺 val 文件 $f"
done
for f in $(echo "$TRAIN_DATA" | tr ',' ' '); do
  [ -f "$f" ] || note "[warn] train-data 里的 $f 不存在（pick_checkpoint 只用它做同问重叠核对）"
done

# ---------- 候选发现 ----------
if [ -z "$CANDS" ]; then
  CANDS=""
  for d in "$OUTV4"/checkpoint-*; do
    [ -d "$d" ] || continue
    n=$(basename "$d" | sed 's/^checkpoint-//')
    CANDS="${CANDS:+$CANDS,}ckpt-$n:$d"
  done
  # train_kitty 最后会 save 一份 out-v4/adapter（= epoch3 末）；与 checkpoint 重复就只留 checkpoint
  if [ -d "$OUTV4/adapter" ]; then
    CANDS="${CANDS:+$CANDS,}final:$OUTV4/adapter"
  fi
fi
[ -n "$CANDS" ] || die "没找到候选：$OUTV4/checkpoint-* 与 $OUTV4/adapter 都不存在（训练没跑完？）"

note "候选："
echo "$CANDS" | tr ',' '\n' | while IFS= read -r c; do
  [ -n "$c" ] || continue
  p=${c#*:}
  if [ -f "$p/adapter_model.safetensors" ]; then
    note "  ${c%%:*}  $p  $(du -h "$p/adapter_model.safetensors" | cut -f1)"
  else
    note "  ${c%%:*}  $p  [MISSING adapter_model.safetensors]"
  fi
done

ARGS=(--base-model "$BASE" --candidates "$CANDS"
      --re-eval "$RE_EVAL" --kitty-eval "$KITTY_EVAL" --val-data "$VAL_DATA"
      --out "$PICKDIR" --ctx "$CTX" --tools-for kitty --max-new 512
      --train-data "$TRAIN_DATA")
[ "$REFRESH" -eq 1 ] && ARGS+=(--refresh)

if [ "$DRY" -eq 1 ]; then
  note "[dry] 将执行： cd $KV && $PY scripts/pick_checkpoint.py ${ARGS[*]} --dry-run"
  ( cd "$KV" && "$PY" scripts/pick_checkpoint.py "${ARGS[@]}" --dry-run ) \
    || die "pick_checkpoint --dry-run 失败（路径/套件有问题，见上）"
  note "[dry] 排序键：re_pass 降序 → re60 配对翻正数 降序 → kitty 降序 → 步数升序"
  note "[dry] val_loss **不在**排序键里（F3：re-val 72 行 100% 在训练集内）"
  printf '[VERDICT] v4_pick: DRY-RUN —— 候选如上，路径与套件校验通过（未加载模型）\n'
  exit 0
fi

FREE=$(gpu_free_mib)
if [ -n "$FREE" ] && [ "$FREE" -lt "$GPU_MIN_FREE" ]; then
  die "GPU 只剩 ${FREE} MiB 空闲（< ${GPU_MIN_FREE}；pick 要 4bit 加载 ~18 GiB）——先停掉别的 serve/训练"
fi
[ -n "$FREE" ] && note "GPU free=${FREE} MiB ✓"

mkdir -p "$PICKDIR" "$R/logs/v4"
LOG=$R/logs/v4/pick.log
say "跑候选（每个候选加载一次 4bit 基座 + 三套评测，约 15-25 min/候选）"
( cd "$KV" && "$PY" scripts/pick_checkpoint.py "${ARGS[@]}" ) 2>&1 | tee "$LOG"
[ "${PIPESTATUS[0]:-0}" -eq 0 ] || die "pick_checkpoint 退出码非 0（日志 $LOG）"

[ -f "$PICKDIR/_summary.json" ] || die "缺 $PICKDIR/_summary.json"

# ---------- 按本关口径重排 + 写 pick.md ----------
# 次级键 = **re60 上的配对翻正数**，不是 val loss：
#   re-subset.val 72 行 100% 落在训练集内（F3），它衡量"背得熟不熟"；
#   re60 差分噪声 ±3 题，三候选极易打平 —— 用 val loss 收尾 = 系统性选出最过拟合的那个。
say "汇总（判据：eval_re 60 > 配对翻正数(paired on re60) > eval_kitty 23；val_loss 已弃用）"
"$PY" - "$PICKDIR/_summary.json" "$CANDS" "$PICKMD" "$BASE" "$PICKDIR" <<'PY' || die "pick.md 生成失败"
import json, os, sys, hashlib, time

summ_p, cands_s, out_md, base, pickdir = sys.argv[1:6]
summ = json.load(open(summ_p, encoding="utf-8"))
table = summ.get("table") or {}
tool_best = summ.get("best")

# name -> 绝对路径（来自 --candidates 原文，保证 pick.md 里是可用的路径）
path_of = {}
for part in cands_s.split(","):
    if ":" in part:
        n, p = part.split(":", 1)
        path_of[n.strip()] = os.path.abspath(p.strip())

# --- 逐题通过与否（配对比较的唯一输入）-----------------------------------------
def load_passmap(name):
    p = os.path.join(pickdir, name + ".json")
    if not os.path.isfile(p):
        return None
    try:
        rec = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    det = rec.get("re_detail") or []
    m = {}
    for d in det:
        idx = d.get("i", d.get("idx"))
        if idx is None:
            continue
        m[idx] = bool(d.get("pass"))
    return m or None

passmap = {name: load_passmap(name) for name in table}
missing_pm = sorted(n for n, m in passmap.items() if m is None)

rows = []
for name, r in table.items():
    vl = (r.get("val_loss_by_file") or {}).get("re-subset.val.jsonl")
    if vl is None:
        vl = r.get("val_loss")
    rows.append({
        "name": name,
        "path": path_of.get(name, ""),
        "re": r.get("re_pass"), "re_n": r.get("re_total"),
        "kitty": r.get("kitty_pass"), "kitty_n": r.get("kitty_total"),
        "val": vl,                      # 仅作参考列，不参与排序
        "wins": 0, "losses": 0, "paired_n": 0,
    })

# --- 配对翻正数（Copeland：对每个对手算 wins / losses）--------------------------
by = {r["name"]: r for r in rows}
names = [r["name"] for r in rows]
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        na, nb = names[i], names[j]
        ma, mb = passmap.get(na), passmap.get(nb)
        if not ma or not mb:
            continue
        common = sorted(set(ma) & set(mb))
        wa = sum(1 for k in common if ma[k] and not mb[k])
        wb = sum(1 for k in common if mb[k] and not ma[k])
        by[na]["wins"] += wa; by[na]["losses"] += wb; by[na]["paired_n"] += len(common)
        by[nb]["wins"] += wb; by[nb]["losses"] += wa; by[nb]["paired_n"] += len(common)

def step_of(name):
    """候选名里的步数（ckpt-735 → 735；非数字给一个很大的值 = 排后面）"""
    import re
    m = re.search(r"(\d+)", name or "")
    return int(m.group(1)) if m else 10 ** 9

def key(x):
    # ① re 通过数降序  ② 配对翻正数降序  ③ kitty 降序  ④ 步数升序（早的优先）
    # val_loss 不在键里 —— 见文件头 F3 说明。
    # ④ 为什么是"早的优先"：re 打平时 wins==losses 恒成立（|A\\B| = |B\\A| 当 |A|=|B|），
    #   所以 ② 在两人打平时退化成常数；真正能抗过拟合的收尾键是"训得少的那份"，
    #   这也正是 v3 的教训（末点 entropy 最低 = 拟合最狠）。
    return (-(x["re"] if x["re"] is not None else -1),
            -(x["wins"] - x["losses"]),
            -(x["kitty"] if x["kitty"] is not None else -1),
            step_of(x["name"]),
            x["name"])

rows.sort(key=key)
best = rows[0] if rows else None

# ---- 诚实性标记：本轮胜负是否由 ④步数升序 决出（前三键全平）-------------------
# 若由 ④ 决出，这个选择是 **prior-driven（抗过拟合先验）**，不是 evidence-driven；
# pick.md 与 stdout 都必须写明，禁止把"更早的 checkpoint 更好"表述成"实测更优"。
tie_by_step = False
if len(rows) >= 2:
    a, b = rows[0], rows[1]
    tie_by_step = (a["re"] == b["re"]
                   and (a["wins"] - a["losses"]) == (b["wins"] - b["losses"])
                   and a["kitty"] == b["kitty"])

print("[pick] 排序键：re_pass 降序 → 配对翻正数 降序 → kitty 降序 → 步数升序（val_loss 已弃用）")
if missing_pm:
    print(f"[pick][WARN] 缺逐题明细的候选 {missing_pm}（<候选>.json 里没有 re_detail）"
          f"→ 其配对数为 0，只能靠 re 通过数定胜负")
if len(rows) >= 2:
    b0, b1 = rows[0], rows[1]
    print(f"[pick] {b0['name']} wins={b0['wins']} losses={b0['losses']} "
          f"(paired on re60, {b0['paired_n']} items)  ← 对 {b1['name']}")
if tie_by_step:
    print(f"[pick][NOTE] 胜负由 ④步数升序 决出（{rows[0]['name']} vs {rows[1]['name']}："
          f"re / paired / kitty 三项全平）→ 该选择是 prior-driven（抗过拟合先验），"
          f"不是 evidence-driven（数据支持）；不得表述为「实测更优」")

def sha16(p):
    if not p or not os.path.isfile(p):
        return "-"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]

lines = ["# v4 checkpoint 选优", "",
         f"> 生成：{time.strftime('%Y-%m-%d %H:%M:%S')} · base=`{base}`",
         "> 判据优先级：**eval_re 60 > 配对翻正数（paired on re60）> eval_kitty 23**",
         "[pick][WARN] re-val 72 行 100% 在训练集内（F3），已弃用为排序键；"
         "次级键改为 re60 配对翻正数（wins = 本候选过而对手 fail 的题数）", "",
         "| 候选 | eval_re 60 | paired wins/losses | eval_kitty 23 | re-val loss（仅参考，不排序） | adapter 路径 |",
         "|---|---|---|---|---|---|"]
for r in rows:
    lines.append(f"| {r['name']} | {r['re']}/{r['re_n']} | "
                 f"{r['wins']}/{r['losses']} | "
                 f"{r['kitty']}/{r['kitty_n']} | "
                 f"{('%.4f' % r['val']) if r['val'] is not None else '-'} | {r['path']} |")
if tie_by_step:
    lines.append(f"[pick][NOTE] 本轮 tie 由 ④步数升序 决出（{rows[0]['name']} vs {rows[1]['name']}："
                 f"re / paired wins / kitty 全平）→ 该选择是 **prior-driven（抗过拟合先验）**，"
                 f"不是 evidence-driven（数据支持）；结论里不得写「实测更优」。")
lines += ["", f"工具（pick_checkpoint）原排序推荐：**{tool_best}**"
              "（它的键是 re > kitty > val_loss，含已弃用的 val）"]
if best and tool_best and best["name"] != tool_best:
    lines.append(f"⚠ 两套排序不一致：本关口径选 **{best['name']}**"
                 f"（re 通过数 → re60 配对翻正数；不看 val loss）。merge 用本关结论。")
lines += ["",
          # 机器读的行必须是裸行（不带 markdown 粗体）：run_after_expand.sh 用
          #   awk -F'adapter=' '/^\[PICK\] adapter=/'
          # 解析，前面加 ** 就匹配不到（实测踩过）
          f"[PICK] adapter={best['path']}" if best else "[PICK] adapter=",
          f"[PICK] candidate={best['name']}" if best else "[PICK] candidate=",
          f"[pick] adapter sha16={sha16(os.path.join(best['path'], 'adapter_model.safetensors')) if best else '-'}",
          ""]
with open(out_md, "w", encoding="utf-8") as f:
    f.write("\n".join([x for x in lines if x is not None]) + "\n")
print("\n".join(lines))
print(f"\n  写 → {out_md}")
PY

BEST=$(awk -F'adapter=' '/^\[PICK\] adapter=/{print $2}' "$PICKMD" | tail -1)
[ -n "${BEST:-}" ] || die "pick.md 里没有 [PICK] adapter=（生成逻辑坏了）"
[ -f "$BEST/adapter_model.safetensors" ] || die "pick.md 推荐的 adapter 不存在：$BEST"

printf '[VERDICT] v4_pick: PASS —— 推荐 %s（pick.md: %s）\n' "$BEST" "$PICKMD"
note "七步的 merge 会读这一行：run_after_expand.sh merge 时自动取 [PICK] adapter="

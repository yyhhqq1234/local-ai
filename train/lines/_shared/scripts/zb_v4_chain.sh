#!/usr/bin/env bash
# Z-B v4：修复唯一残留的编造（G20: kitty_watch → 应为 kitty_wpb）
#   依据：zbv3 = hit30 / acc75.0% / 编造1 / wrong6 / noarg2（两条件已达标，只剩 1 个自造名）
#   G20 实际输出：kitty_prot action=query → kitty_prot action=protect → **kitty_watch**（自造）
#   处方：补 40 行针对性范式 —— 写保护链只用 kitty_wpb；写后确认只用 kitty_prot action=query / kitty_ce R
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
LOG="$L/zb-v4.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

log "================ Z-B v4 启动 pid=$$ ================"

DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-re-v4.jsonl
EXTRA=train/lines/9b-oxcoder/data/agent-traj/kitty-callcoverage-antifake.jsonl
if [ ! -f "$DATA" ]; then
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import io, json, random
random.seed(20251031)
CAT = json.load(open("train/lines/9b-oxcoder/data/kitty-tool-catalog.json", encoding="utf-8"))
PHR = [
    "{desc} —— 用工具跑起来（动作 {act}），参数一次给全。",
    "我需要{desc}，走 {act} 这个动作，直接给调用。",
    "任务：{desc}。请选对工具、用 {act}，别反问。",
    "按工作台规范做一次「{desc}」（{act}），给出工具调用与判据。",
]
def asst_rows(tool, act):
    t = CAT[tool]
    assert act in t["actions"], (tool, act, t["actions"])
    out = []
    for p in PHR:
        a = (f"{tool} action={act}\n\n"
             f"参数要点：addr 给目标虚拟地址；size 按页取 4096；改前先 read 存原值，改后回读校验。\n"
             f"判据：回包 OK 表示写已生效；回读与期望一致才算闭环；失败先确认是否 NOACCESS / 已换出页。\n"
             f"写保护地址的修改与确认只用 {tool} / kitty_prot action=query / kitty_ce R，"
             f"不存在也不允许自造 watch、monitor、verify 之类的新工具名。")
        out.append({"messages": [
            {"role": "user", "content": p.format(desc=t["description"], act=act)},
            {"role": "assistant", "content": a},
        ], "meta": {"src": "antifake", "tool": tool, "action": act}})
    return out

rows = []
for tool in ("kitty_wpb",):
    for act in CAT[tool]["actions"]:
        rows += asst_rows(tool, act)
# 写后确认链：明确用现有工具，两次调用收口
VERIFY = [
    ("写保护地址改完之后怎么确认改成功了？", "kitty_prot action=query 回读保护位，再用 kitty_ce 的 R 读回目标值比对。"),
    ("PTE 直写之后要复核什么？", "kitty_wpb 写完 → kitty_ce R 回读同址 → 与期望值比对；不要另造新的校验工具。"),
    ("有没有专门的 watch 或 monitor 工具看内存变化？", "没有 kitty_watch / kitty_monitor 这类工具；变化确认用 kitty_prot action=query 或 kitty_ce 的 R。"),
    ("防护绕过写失败，先查什么？", "先 kitty_prot action=query 看保护位，再决定是否 kitty_wpb permissive；不复用自造名。"),
]
for q, a in VERIFY:
    rows.append({"messages": [{"role": "user", "content": q},
                              {"role": "assistant", "content": a}],
                 "meta": {"src": "antifake-verify"}})

with open("train/lines/9b-oxcoder/data/agent-traj/kitty-callcoverage-antifake.jsonl", "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

main = [l for l in io.open("train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-clean.jsonl", encoding="utf-8")]
cov  = [l for l in io.open("train/lines/9b-oxcoder/data/agent-traj/kitty-callcoverage-aug.jsonl", encoding="utf-8")]
sub = random.sample(main, 7000)
allrows = sub + cov + [json.dumps(r, ensure_ascii=False) + "\n" for r in rows]
random.shuffle(allrows)
with open("train/lines/9b-oxcoder/data/_legacy/mix-z-re-v4.jsonl", "w", encoding="utf-8") as f:
    f.writelines(allrows)
names = sorted({r["meta"].get("tool") for r in rows if r["meta"].get("tool")})
print(f"[build] antifake={len(rows)} 行（工具 {names}）· 总 {len(allrows)} 行")
PYEOF
  log "数据已建：$DATA"
else
  log "数据已存在：$DATA"
fi

if [ ! -d "$OUT/z-re-v4/final" ]; then
  log "训练开始：init=r3 · $(wc -l < "$DATA") 行 · 1 epoch · lr 2e-5"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re \
    --init-adapter train/lines/9b-oxcoder/out/re-stage1-r3/final --out "$OUT/z-re-v4" \
    --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 400 --save-total-limit 6 >> "$L/z-re-v4-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "跳过训练：z-re-v4/final 已存在"
fi

if [ -d "$OUT/z-re-v4/final" ]; then
  log "评测开始（r3 对照 + zbv4）"
  "$PY" train/lines/_shared/scripts/eval_multi_adapter.py \
    --adapters "r3=$OUT/re-stage1-r3/final,zbv4=$OUT/z-re-v4/final" \
    --max-new 300 --batch 1 --out "$OUT/eval-re-zbv4.json" >> "$LOG" 2>&1
  log "评测退出 rc=$?"
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, os
p, q = "train/lines/9b-oxcoder/out/eval-re-zre.json", "train/lines/9b-oxcoder/out/eval-re-zbv4.json"
if os.path.exists(q):
    a = json.load(open(p, encoding="utf-8")); b = json.load(open(q, encoding="utf-8"))
    rows = {r["label"]: r for r in a["results"]}
    for r in b["results"]:
        rows[r["label"]] = r
    order = ["r3", "zre", "zbv2", "zbv3", "zbv4"]
    a["results"] = [rows[k] for k in order if k in rows] + [v for k, v in rows.items() if k not in order]
    json.dump(a, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[merge] 现有:", list(rows))
PYEOF
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总完成 rc=$?"
  echo "| $(date '+%F %T') | Z-B v4 完成 · z-re-v4/final |" >> "$L/z-stages.md"
fi
log "================ Z-B v4 结束 ================"

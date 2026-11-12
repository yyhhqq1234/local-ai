# -*- coding: utf-8 -*-
"""RE 训练方法 V2：把「候选工具集 + 硬负例」注入训练样本

问题（TASKPOINT §A20 实测）：
  现有样本是「问句 → 唯一答案」，模型从没练过「在一堆看起来都能用的工具里选一个」。
  所以换个 system 就翻转 11 条；清单里 kitty_dbg 一出现就把 pchain 题吸走。

本脚本把每条 SFT 样本改造成：
  system    = 原 system + 「当前会话可用工具」（N 个候选定义，必含正确工具）
  user      = 原 ask（不动）
  assistant = 原答案（不动）

候选集构成（硬负例优先）：
  ① 必含 expect 里的全部正确答案
  ② 同簇易混工具（CLUSTERS，手工定义，来自 40 条错例 + 历史编造记录）
  ③ 同通道近邻
  ④ 少量跨通道（提高难度）
  负向题（expect 空）：候选集全部是「看起来相关」的工具，正解是不调用

token 预算：N=8~12 个候选 × 约 70 字符 ≈ 560~840 字符；原样本 P99 1125 字符
  ⇒ 总长约 1700~2000 字符 ≈ 850~1000 token，ctx 2048 够用（无需扩到 4096）

用法：
  python build_re_candidates.py --seed 42 --out mix-z-re-v2-cand-train.jsonl
  python build_re_candidates.py --seed 7  --out mix-z-re-v2-cand-eval.jsonl --eval-mode
"""
import argparse
import io
import json
import os
import random
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

L9B = "train/lines/9b-oxcoder"
SRC = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4-fixed.jsonl")
TOOLS = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")
OUTDIR = os.path.join(L9B, "data", "kitty-reverse")

# ── 硬负例簇：来自实测错例、历史编造、以及真实的语义近邻 ────────────────
CLUSTERS = [
    # 内存读取 / 内核视图 / 指针
    ["kitty_ce", "kitty_dump", "kitty_prot", "kitty_km", "kitty_wpb", "kitty_pchain"],
    # 静态分析
    ["kitty_ghidra", "kitty_ida", "kitty_idamcp", "kitty_sym", "kitty_patch", "kitty_asm"],
    # REA 系列（名字最长最易混）
    ["kitty_rea", "kitty_rea_binary", "kitty_rea_function", "kitty_rea_trace",
     "kitty_rea_android", "kitty_rea_compare", "kitty_rea_method", "kitty_rea_callpath",
     "kitty_rea_recover_js", "kitty_rea_javascript"],
    # 引擎资产还原
    ["kitty_assetrip", "kitty_engines", "kitty_gdre", "kitty_cpp2il", "kitty_il2cppdumper",
     "kitty_fmodel", "kitty_unpack", "kitty_dnspy", "kitty_lua"],
    # 移动端
    ["kitty_jadx", "kitty_apktool", "kitty_apkscan", "kitty_unpack"],
    # 调试 / 对抗 / 门禁（kitty_dbg 是头号吸铁石）
    ["kitty_dbg", "kitty_x64dbg", "kitty_dualview", "kitty_acescan", "kitty_variants", "kitty_selftest"],
    # 宿主 / 驱动 / 初始化
    ["kitty_drv", "kitty_drvio", "kitty_init", "kitty_status"],
    # 记录 / 编排（reverse_add_* 相互极像）
    ["kitty_trail", "kitty_settings", "kitty_loop", "kitty_loop_status",
     "reverse_add_target", "reverse_add_intent", "reverse_add_obs",
     "reverse_add_patch", "reverse_add_asset", "reverse_submit"],
    # 引擎运行时
    ["kitty_inject", "kitty_frida", "kitty_uedump", "kitty_ue4ss", "kitty_bepinex", "kitty_uexplorer"],
    # 协议 / 抓包
    ["kitty_net", "kitty_proto"],
    # 元信息
    ["kitty_ops", "kitty_status", "kitty_selftest"],
]

ap = argparse.ArgumentParser()
ap.add_argument("--src", default=SRC)
ap.add_argument("--out", default="mix-z-re-v2-cand-train.jsonl")
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--eval-mode", action="store_true",
                help="评测模式：更高比例硬负例、更多跨通道干扰、不同采样分布")
ap.add_argument("--limit", type=int, default=0)
args = ap.parse_args()

rng = random.Random(args.seed)
tools = json.load(io.open(TOOLS, encoding="utf-8"))
TMAP = {t["name"]: t for t in tools}
ALL = sorted(TMAP)

# 簇索引
name2clusters = defaultdict(list)
for ci, cl in enumerate(CLUSTERS):
    for n in cl:
        if n in TMAP:
            name2clusters[n].append(ci)
# 通道索引
chan2names = defaultdict(list)
for t in tools:
    chan2names[t.get("channel", "?")].append(t["name"])


def fmt_tool(name):
    t = TMAP[name]
    acts = ",".join(t.get("actions") or [])
    desc = (t.get("description") or "").strip().replace("\n", " ")
    if len(desc) > 60:
        desc = desc[:60] + "…"
    return "- %s: %s%s" % (name, desc, ("  actions=[%s]" % acts) if acts else "")


def pick_candidates(expect, k):
    """构造 k 个候选：必含 expect，其余硬负例优先"""
    chosen = [n for n in expect if n in TMAP]
    pool_hard = []
    for n in chosen:
        for ci in name2clusters.get(n, []):
            pool_hard.extend(CLUSTERS[ci])
    # 同通道次选
    pool_chan = []
    for n in chosen:
        pool_chan.extend(chan2names.get(TMAP[n].get("channel", "?"), []))
    if not chosen:  # 负向题：从"看起来相关"的通道里抽，正解是不调用
        pool_hard = CLUSTERS[rng.randrange(len(CLUSTERS))]
        pool_chan = list(ALL)

    def uniq(seq):
        out, seen = [], set(chosen)
        for x in seq:
            if x in TMAP and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    hard = uniq(pool_hard)
    chan = uniq(pool_chan)
    rest = uniq(ALL)
    rng.shuffle(hard); rng.shuffle(chan); rng.shuffle(rest)

    need = k - len(chosen)
    # 训练：硬负例占多数；评测：硬负例全上 + 更多跨通道
    take_hard = min(len(hard), need if not args.eval_mode else need)
    picked = chosen + hard[:take_hard]
    need = k - len(picked)
    if need > 0:
        picked += chan[:need]
        need = k - len(picked)
    if need > 0:
        picked += rest[:need]
    rng.shuffle(picked)
    return picked


def main():
    src = [json.loads(l) for l in io.open(args.src, encoding="utf-8") if l.strip()]
    if args.limit:
        src = src[:args.limit]
    out_path = os.path.join(OUTDIR, args.out)
    n_written = 0
    stats = defaultdict(int)
    lens = []

    with io.open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for o in src:
            msgs = o.get("messages") or []
            sys_msg = next((m for m in msgs if m.get("role") == "system"), None)
            user_msg = next((m for m in msgs if m.get("role") == "user"), None)
            asst_msg = next((m for m in msgs if m.get("role") == "assistant"), None)
            if not (user_msg and asst_msg):
                continue
            base_sys = str(sys_msg.get("content")) if sys_msg else ""

            # 从 assistant 原文里抽"正确工具"作为 expect（无法拿到评测 expect 时的兜底）
            expect = []
            for n in ALL:
                if n in str(asst_msg.get("content", "")):
                    # 取最长匹配，避免 kitty_rea 覆盖 kitty_rea_compare
                    if not any(n != m and n in m and m in str(asst_msg.get("content", "")) for m in ALL):
                        expect.append(n)
            k = rng.choice([8, 10, 12]) if not args.eval_mode else 12
            # 保证干扰项至少 5 个（正确工具有多个时把 k 顶上去，避免候选集退化成 5-7）
            k = max(k, len(expect) + 5)
            cands = pick_candidates(expect, k)
            head = "当前会话可用工具（只能从下列工具中选）：\n" + "\n".join(fmt_tool(c) for c in cands)
            new_sys = (base_sys + "\n\n" + head) if base_sys else head

            new_msgs = ([{"role": "system", "content": new_sys}] if new_sys else []) + \
                       [{"role": "user", "content": str(user_msg.get("content"))},
                        {"role": "assistant", "content": str(asst_msg.get("content"))}]
            f.write(json.dumps({"messages": new_msgs}, ensure_ascii=False) + "\n")
            n_written += 1
            stats["no_expect"] += 1 if not expect else 0
            stats["has_expect"] += 1 if expect else 0
            lens.append(len(new_sys) + len(str(user_msg.get("content"))) + len(str(asst_msg.get("content"))))

    lens.sort()
    print("=" * 88)
    print("V2 候选集样本生成%s  seed=%d" % ("（评测模式）" if args.eval_mode else "（训练）", args.seed))
    print("=" * 88)
    print("  源 %s：%d 行" % (os.path.basename(args.src), len(src)))
    print("  出 %s：%d 行" % (args.out, n_written))
    print("  样本内正确工具可识别：%d · 不可识别(负向/纯讲解)：%d"
          % (stats["has_expect"], stats["no_expect"]))
    print("  总字符 P50=%d P90=%d P99=%d Max=%d"
          % (lens[len(lens) // 2], lens[int(len(lens) * .9)],
             lens[int(len(lens) * .99)], lens[-1]))
    over = sum(1 for x in lens if x > 4096)
    print("  >4096 字符（ctx4096 上限参考）：%d 行 (%.2f%%)" % (over, over * 100.0 / max(len(lens), 1)))
    over2 = sum(1 for x in lens if x > 2000)
    print("  >2000 字符（ctx2048 上限参考）：%d 行 (%.2f%%)" % (over2, over2 * 100.0 / max(len(lens), 1)))
    print()
    print("  样例 system（前 700 字符）：")
    first = json.loads(io.open(out_path, encoding="utf-8").readline())
    print("  " + first["messages"][0]["content"][:700].replace("\n", "\n  "))


main()

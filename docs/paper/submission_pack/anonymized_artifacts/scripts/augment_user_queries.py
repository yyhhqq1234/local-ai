"""user 提问同义改写增广 —— 抗「背答案」的核心数据手段

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么需要
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
实测（2026-10-28）：train-kitty-core.jsonl 5602 条，user 极短（首条 14 字符），
assistant 是模板化三段式，同一工具的回答高度雷同。结果模型只学「字面 → 整段」：
  · 档1（1 遍）n-gram 重合 0.167，逐字背 1 条
  · 档2（2 遍）n-gram 重合 0.515，逐字背 4 条
  · 档3（3 遍）n-gram 重合 0.478，逐字背 4 条
4/10 条与参考答案 20-gram 重合 1.00 = 完全复现。

对策：同一意图 × K 种表述，assistant 保持**完全不变**。
模型要同时满足 K 种提问，就只能学「语义 → 工具」的映射，无法靠字面命中。
副作用：同一答案被 K 条不同 prompt 指向，等价于对「答案串」施加了正则化。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python augment_user_queries.py                     # 默认 K=4，全量
  python augment_user_queries.py --k 5 --limit 200   # 先小批验证
  python augment_user_queries.py --k 3 --out train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-aug.jsonl

产出：每条原始样本 → 1 条原句 + (K-1) 条改写 = K 条
  assistant 不动，只改 user。system 不动。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import argparse
import io
import json
import os
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IN = os.path.join(TRAIN_ROOT, "data", "kitty-reverse", "train-kitty-core.jsonl")
DEFAULT_OUT = os.path.join(TRAIN_ROOT, "data", "kitty-reverse", "train-kitty-aug.jsonl")

# ── 改写素材（逆向领域口吻）──────────────────────────────────────────────
PREFIXES = [
    "遇到个情况：",
    "问一下，",
    "这里卡住了：",
    "帮我看看，",
    "不太确定这块：",
    "实际跑的时候，",
    "有个疑问，",
    "现在的问题是：",
    "想确认一下，",
    "接下来要做的：",
]

SUFFIXES = [
    "",
    "",
    "该怎么走？",
    "有推荐的做法吗？",
    "下一步动哪个？",
    "这块怎么处理比较稳？",
    "给个具体做法。",
    "需要注意什么？",
    "一次做对的路径是什么？",
]

END_PUNCT = "。.？?！!，,；; "


def add_suffix(t, rng):
    """把后缀接上，避免「？？」或「？ 一次…」这种粘连；无后缀时补回句末标点"""
    suf = rng.choice(SUFFIXES)
    if not suf:
        t = t.rstrip(END_PUNCT)
        return t + ("？" if t.endswith(("什么", "哪", "吗", "么")) else "。")
    t = t.rstrip(END_PUNCT)
    return t + "，" + suf

# 同义词替换（领域内等义，保持语义不变）
# ★ 只放「替换后不会与相邻字重复」的条目。
#   反例：("内存","内存里") 会把「内存里已加载」变成「内存里里加载」—— 已剔除。
SYNONYMS = [
    ("要看", "想看"),
    ("想要", "想"),
    ("怎么", "如何"),
    ("查看", "看"),
    ("查询", "查"),
    ("判断", "判定"),
    ("确认", "核实"),
    ("获取", "拿到"),
    ("提取", "扒出"),
    ("处理", "处置"),
    ("发现", "找到"),
    ("问题", "状况"),
    ("方法", "路径"),
    ("是否", "是不是"),
    ("能不能", "能否"),
    ("已加载", "加载好的"),
    ("导入表", "import 表"),
    ("导出表", "export 表"),
    ("加壳", "被壳处理过"),
    ("转储", "dump 出来"),
    ("注入", "打进去"),
]

# 结构性改写模板（把陈述句变疑问句 / 把疑问句变陈述句）
TEMPLATES = [
    ("陈述→疑问", lambda s: s.rstrip("。.？?") + "，用哪个工具？"),
    ("陈述→求助", lambda s: s.rstrip("。.？?") + "，帮我处理一下。"),
    ("陈述→场景", lambda s: "手上这个场景：" + s.rstrip("。.？?") + "。该动什么？"),
    ("陈述→确认", lambda s: "我理解是要" + s.rstrip("。.？?") + "，对吗？具体怎么操作？"),
]


def apply_synonyms(text, rng, p=0.6):
    """按概率替换同义词，避免全替换导致语句生硬"""
    out = text
    for a, b in SYNONYMS:
        if a == b:
            continue
        if a in out and rng.random() < p:
            out = out.replace(a, b, 1)
    return out


def vary(text, rng, idx):
    """生成第 idx 个变体（idx=0 返回原句）"""
    if idx == 0:
        return text
    t = text.strip()
    # 去掉已有的口头前缀，避免叠加
    for p in PREFIXES:
        if t.startswith(p):
            t = t[len(p):]
            break
    t = t.rstrip("。.？?")

    mode = (idx - 1) % 3
    if mode == 0:
        # 同义词 + 后缀
        t = apply_synonyms(t, rng)
        t = add_suffix(t, rng)
    elif mode == 1:
        # 模板结构改写
        name, fn = rng.choice(TEMPLATES)
        t = fn(t)
    else:
        # 前缀 + 同义词 + 后缀
        t = rng.choice(PREFIXES) + apply_synonyms(t, rng)
        t = add_suffix(t, rng)

    # 兜底：不能为空 / 不能与原句完全相同
    t = t.strip()
    if not t or t == text.strip():
        t = rng.choice(PREFIXES) + text.strip().rstrip(END_PUNCT) + "，" + rng.choice(SUFFIXES).lstrip()
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=DEFAULT_IN)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--k", type=int, default=4, help="每条扩成 K 条（含原句）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全量）")
    ap.add_argument("--seed", type=int, default=42)
    # ★ 2026-10-28 加：长度 guard
    #   实测 train-kitty-core 有 6 条 user 只有 1-3 字（「继续」「批」「同意」），
    #   另有 40 条 >800 字是 AgentTeams 协作消息（域不匹配 + 长短严重不匹配）。
    #   这类样本增广只会放大问题 → 默认跳过并记入隔离清单（原数据不动）。
    ap.add_argument("--min-user-chars", type=int, default=4, dest="min_user",
                    help="user 短于此值则跳过（默认 4，只挡「继续」「批」这类无独立语义的；0=不限制）")
    ap.add_argument("--max-user-chars", type=int, default=600, dest="max_user",
                    help="user 长于此值则跳过（默认 600；0=不限制）")
    ap.add_argument("--quarantine", default="", dest="quarantine",
                    help="被跳过的样本写入此文件（不删原数据，只隔离）")
    args = ap.parse_args()

    if not os.path.isfile(args.inp):
        sys.exit("[FATAL] 输入不存在: %s" % args.inp)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    rng = random.Random(args.seed)
    n_in = 0
    n_out = 0
    n_skip = 0
    n_band = 0          # 被长度 guard 挡下的条数
    seen_user = {}
    qf = None
    if args.quarantine:
        os.makedirs(os.path.dirname(os.path.abspath(args.quarantine)), exist_ok=True)
        qf = io.open(args.quarantine, "w", encoding="utf-8")
        print("[quarantine] 隔离记录 → %s" % args.quarantine)

    with io.open(args.inp, "r", encoding="utf-8") as fi, \
            io.open(args.out, "w", encoding="utf-8") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            if args.limit and n_in >= args.limit:
                break
            n_in += 1
            o = json.loads(line)
            msgs = o.get("messages") or []
            if len(msgs) < 3:
                n_skip += 1
                continue
            # 找 user / assistant
            u_idx = next((i for i, m in enumerate(msgs) if m.get("role") == "user"), None)
            if u_idx is None:
                n_skip += 1
                continue
            user = msgs[u_idx]["content"]

            # ★ 长度 guard（对应体检 A1 / A2）
            #   太短 = 无意义（「继续」「批」）；太长 = 域不匹配 + 长短失衡
            if (args.min_user and len(user) < args.min_user) or \
                    (args.max_user and len(user) > args.max_user):
                n_band += 1
                if qf is not None:
                    qf.write(json.dumps({
                        "reason": "user_len_out_of_band",
                        "len": len(user),
                        "user": user[:200],
                        "assistant_head": next(
                            (m.get("content", "")[:150] for m in msgs
                             if m.get("role") == "assistant"), ""),
                    }, ensure_ascii=False) + "\n")
                continue

            for idx in range(args.k):
                new_user = vary(user, rng, idx)
                key = (new_user, len(msgs))
                if key in seen_user:
                    continue
                seen_user[key] = 1
                new_msgs = [dict(m) for m in msgs]
                new_msgs[u_idx]["content"] = new_user
                rec = dict(o)
                rec["messages"] = new_msgs
                # 标记来源，便于追溯与统计
                rec["_aug"] = {"src_user": user, "variant": idx}
                fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_out += 1

    if qf is not None:
        qf.close()

    print("=" * 70)
    print("输入 %d 条 → 输出 %d 条（K=%d）" % (n_in, n_out, args.k))
    print("跳过：结构异常 %d 条 | 长度超出 [%d, %d] 区间 %d 条"
          % (n_skip, args.min_user, args.max_user, n_band))
    print("膨胀率 = %.2fx" % (n_out / n_in if n_in else 0))
    print("产出 → %s" % args.out)
    if qf is not None:
        print("隔离清单 → %s（原数据未删，仅不参与训练）" % args.quarantine)
    print("=" * 70)


if __name__ == "__main__":
    main()

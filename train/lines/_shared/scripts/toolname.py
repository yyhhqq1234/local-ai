"""工具名提取 —— 六个评测脚本的唯一真相源

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
这个模块解决三个踩过的坑（PITFALLS E5 / E6 + 2026-10-28 体检新发现）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
坑 1｜只认 kitty_ 前缀
    正则写 `kitty_[a-z0-9_]+`，漏掉 6 个 `reverse_*` 工具
    （reverse_add_target/intent/obs/patch/asset、reverse_submit）→ 误报「0 覆盖」

坑 2｜粘连
    模型写 `kitty_net action=capture`，正则把空格后的词连读成 `kitty_netaction`
    → 误判编造

坑 3｜`reverse_` 是常见英文前缀（★ 2026-10-28 体检新发现）
    用 `(?:kitty|reverse)_[a-z0-9_]+` 会误抓：
        reverse_url / reverse_arguments / reverse_indexer  ← 其他软件的真实 API
        reverse_solidus                                   ← JSON 转义名（U+005C）
        kitty_keyboard_protocol                           ← 浏览器 API
    这些被当成「编造的工具名」，让编造数虚高。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
解法：两条不同策略
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  kitty_*   专有前缀，不会与正常英文撞 → 正则 + 白名单 + 最长前缀归一 + 编造检测
  reverse_* 常见英文前缀 → **只做白名单精确子串匹配，不做编造检测**
            （编造检测对 reverse_ 没有意义：模型胡说一个 reverse_xxx 无从与
             真实英文 API 区分，强行检测只会制造假阳性）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  from toolname import load_tools, extract, extract_seq

  tools = load_tools()
  hit, fake = extract(resp_text, tools)      # hit: 命中的真实工具; fake: 编造
  seq = extract_seq(resp_text, tools)        # 保序的工具序列（2A 用）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_ROOT = os.path.dirname(HERE)
try:  # 双线目录单一真相源（2026-11-01 迁移后）
    from _dsh_paths import TRAIN as _TRAIN, L9B as _L9B, L27B as _L27B, SHARED as _SHARED
    TRAIN_ROOT = _TRAIN
except Exception:
    _L9B = _L27B = _SHARED = None

CONTRACT = os.path.join(_L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")

# 只对 kitty_ 做编造检测（专有前缀，不会撞正常英文）
KITTY_PAT = re.compile(r"kitty_[a-z0-9_]+")
# reverse_ 只用于找候选后再与白名单核对
REVERSE_PAT = re.compile(r"reverse_[a-z0-9_]+")


def load_tools(path=None):
    with io.open(path or CONTRACT, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {t["name"] for t in data if isinstance(t, dict) and t.get("name")}


def _norm_kitty(tok, kitty_tools):
    """kitty_ token → 归一到真实工具名；无前缀匹配则原样返回（= 编造）"""
    if tok in kitty_tools:
        return tok
    pref = [k for k in kitty_tools if tok.startswith(k)]
    return max(pref, key=len) if pref else tok


def extract(text, tools):
    """返回 (hit:set, fake:set)

    hit   = 输出里出现的真实工具名（含粘连归一的）
    fake  = kitty_ 前缀但不在白名单的（真编造）
            reverse_ 前缀的**不参与**编造判断，只在精确匹配到白名单时进 hit
    """
    t = text or ""
    kitty_tools = {x for x in tools if x.startswith("kitty_")}
    rev_tools = {x for x in tools if x.startswith("reverse_")}

    hit = set()
    fake = set()

    for tok in KITTY_PAT.findall(t):
        n = _norm_kitty(tok, kitty_tools)
        if n in kitty_tools:
            hit.add(n)
        else:
            fake.add(n)

    # reverse_ 只认白名单精确子串，不做编造检测
    for r in rev_tools:
        if r in t:
            hit.add(r)
    # 「reverse_add_」这种泛指写法：若能唯一补全到某个白名单项则不作数，直接忽略
    for tok in REVERSE_PAT.findall(t):
        if tok in rev_tools:
            continue
        pref = [r for r in rev_tools if r.startswith(tok)]
        if len(pref) == 1:
            hit.add(pref[0])       # reverse_add_ → 但无法确定是哪个，宁可不算
            hit.discard(pref[0])

    return hit, fake


def extract_seq(text, tools):
    """保序提取工具序列（2A 判据用）；reverse_ 只做白名单匹配且需完整出现在文本里"""
    t = text or ""
    kitty_tools = {x for x in tools if x.startswith("kitty_")}
    rev_tools = {x for x in tools if x.startswith("reverse_")}

    spans = []
    for m in KITTY_PAT.finditer(t):
        n = _norm_kitty(m.group(0), kitty_tools)
        if n in kitty_tools:
            spans.append((m.start(), n))
    for r in rev_tools:
        for m in re.finditer(re.escape(r), t):
            spans.append((m.start(), r))
    spans.sort()
    # 同一位置只留一个（reverse_add_target 与 reverse_add_ 并存时取长的）
    out, last = [], -1
    for pos, name in spans:
        if pos == last:
            continue
        out.append(name)
        last = pos
    return out

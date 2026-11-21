# -*- coding: utf-8 -*-
"""NSFW / DSH 清洗共用件：路径、词表、归一化、MinHash-LSH。

只读输入，不在本文件写任何东西。
"""
import io
import json
import os
import re
import sys
import unicodedata
import hashlib

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
DATA = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data")

IN_V5 = os.path.join(DATA, "nsfw-gated", "train-2b-gated-v5.jsonl")
IN_POS = os.path.join(DATA, "nsfw-gated", "gate-pos.jsonl")
IN_NEG = os.path.join(DATA, "nsfw-gated", "gate-neg.jsonl")
IN_DSH = os.path.join(DATA, "dsh-adapt", "train-dsh.jsonl")
EVAL_DIR = os.path.join(DATA, "eval")
LEXICON = os.path.join(ROOT, "train", "lines", "_shared", "data", "nsfw", "nsfw-lexicon-v9.json")
KITTY_MANIFEST = os.path.join(ROOT, "_work", "rebuild", "kitty-adapt", "manifest.json")
REBUILD_MANIFEST = os.path.join(ROOT, "_work", "rebuild", "manifest.json")

OUT_DIR = os.path.join(DATA, "nsfw-gated", "cleaned")
WORK = os.path.join(ROOT, "_work", "clean", "nsfw")

# ---------------------------------------------------------------- 词表
# 1) 未成年硬闸（零容忍）。"幼" 单独按词判，见 minor_hit()。
# 口径纠正 2026-11-21：萝莉 属外观描述词，移出 HARD/SOFT；只有同条出现
# 明确未成年线索（HARD 词 / 年龄 / 学段）时才拦，见 LOLI_CUES。
MINOR_HARD = [
    "幼女", "幼齿", "幼童", "童女", "未成", "未成年",
    "小学生", "初中生", "高中生", "学生妹", "女童", "正太",
]
LOLLI_WORD = "萝莉"
# 萝莉在同条出现下列线索时视为未成年指向（年龄 / 学段 / 儿童 / 未成年）
LOLI_CUES = [
    "未成年", "小学", "初中", "高中", "学龄", "儿童", "幼女", "女童", "童女",
    "几个月大", "周岁",
]
LOLI_AGE_RE = re.compile(r"([0-9]{1,2}|[一二三四五六七八九十]{1,3}|几)\s*岁")

# "幼" 保白名单：非人物指向 / 非性化指向的固定搭配（判定时先剔除这些 2 字片段再看残留）
YOU_BENIGN = [
    "幼稚", "幼时", "幼小", "幼苗", "幼虫", "幼体", "幼芽", "幼树", "幼犬",
    "幼猫", "幼兔", "幼鸟", "幼兽", "幼仔", "幼崽", "幼发", "幼枝", "幼林",
    "幼龄", "幼弱", "幼功", "幼学",
]
# 明确人物指向且涉未成年的 "幼" 搭配（命中即硬删）
YOU_MINOR = ["幼儿", "幼年", "幼子", "幼女", "幼童", "幼齿", "幼少", "幼妹"]

# 2) SOFT 词：需同条成年声明
SOFT_WORDS = ["少女", "校园", "JK", "女高中生", "学生"]
ADULT_DECL = ["成年", "已满18", "已满 18", "18岁以上", "18 岁以上", "均为成年人", "成年人"]

# 3) 拒答 / 代偿 / 自审
REFUSAL = [
    "我无法", "无法生成", "不能写", "建议咨询", "替代方案",
    "非露骨", "用隐喻带过", "换个话题", "先给你骨架",
]

# 4) 模板痕迹
TEMPLATE = ["[STAGE]", "交付物", "判据", "当前-结果-下一步", "模式已启动"]

# 5) 对白判定（引号对白）
DIALOGUE_RE = re.compile(r"[“\"「『].{1,400}?[”\"」』]", re.S)
# 具体动作句判定（动作动词 + 身体/位移）
ACTION_RE = re.compile(
    r"(褪|扯|按|抓|握|搂|抱|贴|压|推|拉|坐|跪|骑|趴|俯|仰|转身|伸手|抬|低头|吻|舔|咬|含|吮|"
    r"进入|抽|挺|顶|撞|插|摩擦|抚|摸|揉|捏|掐|扯下|解开|脱|掀|钻|缠|夹|合拢|分开|张开)"
)

MINOR_SYSTEM_HINT = ["未成年", "萝莉", "幼女", "正太", "中学生", "小学生"]

# ---------------------------------------------------------------- 归一化


def norm_text(s):
    """用于去重的归一化：NFKC + 小写 + 去空白 + 去标点。不改变原文。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[，。！？、；：“”‘’（）《》【】…—\-·,.!?;:\"'()\[\]{}<>~`|/\\]+", "", s)
    return s


def shingles(s, k=5):
    s = norm_text(s)
    if len(s) <= k:
        return {s} if s else set()
    return {s[i:i + k] for i in range(len(s) - k + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / float(len(a) + len(b) - inter)


def shingle_hashes(text, k=5):
    """文本 → 5-gram 的 64 位哈希数组（numpy uint64；crc32 拼高 32 位）。"""
    import numpy as np
    import zlib
    s = norm_text(text)
    sh = [s] if 0 < len(s) <= k else [s[i:i + k] for i in range(len(s) - k + 1)]
    if not sh:
        return np.zeros(0, dtype=np.uint64)
    lo = np.fromiter((zlib.crc32(x.encode("utf-8")) for x in sh), dtype=np.uint64, count=len(sh))
    hi = np.fromiter((zlib.crc32(b"\x9b" + x.encode("utf-8")) for x in sh), dtype=np.uint64, count=len(sh))
    return (lo << np.uint64(32)) | hi


# ---------------------------------------------------------------- 词判


def _cn2int(s):
    """中文数字 -> int（限 1..99，够年龄用）。失败返回 None。"""
    if s.isdigit():
        return int(s)
    d = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
         "八": 8, "九": 9, "十": 10}
    if s == "几":
        return -1  # 不确定年龄，按未成年嫌疑处理
    if s in d:
        return d[s]
    if s.startswith("十") and len(s) == 2 and s[1] in d:
        return 10 + d[s[1]]
    if len(s) == 3 and s[1] == "十" and s[0] in d and s[2] in d:
        return d[s[0]] * 10 + d[s[2]]
    if len(s) == 2 and s[0] in d and s[1] in d:
        return d[s[0]] * 10 + d[s[1]]  # 十八 / 二十
    return None


def minor_age_cue(text):
    """返回 (cue: bool, detail: str)。年龄线索只在 <18 或不可判（几岁）时算。"""
    t = text or ""
    for w in LOLI_CUES:
        if w in t:
            return True, f"cue:{w}"
    for m in LOLI_AGE_RE.finditer(t):
        n = _cn2int(m.group(1))
        if n is None:
            continue
        if n == -1 or 1 <= n <= 17:
            return True, f"age:{m.group(1)}"
    return False, ""


def minor_eval(text):
    """结构化判定。返回 dict(hit, reason, loli_present, loli_only, loli_gated)。

    loli_only=True 表示：只靠"萝莉"就会被旧口径删（现已放行），供纠正统计用。
    """
    t = text or ""
    loli_present = LOLLI_WORD in t
    cue, cue_detail = minor_age_cue(t)
    res = {"loli_present": loli_present, "loli_only": False,
           "loli_gated": False, "hit": False, "reason": "", "cue": cue_detail}
    for w in MINOR_HARD:
        if w in t:
            res.update(hit=True, reason=f"hard:{w}")
            return res
    for w in YOU_MINOR:
        if w in t:
            res.update(hit=True, reason=f"hard:{w}")
            return res
    if "幼" in t:
        stripped = t
        for w in sorted(YOU_BENIGN, key=len, reverse=True):
            stripped = stripped.replace(w, "□")
        if "幼" in stripped:
            res.update(hit=True, reason="hard:幼(残留)")
            return res
    if loli_present:
        if cue:
            res.update(hit=True, reason=f"hard:萝莉+{cue_detail}", loli_gated=True)
            return res
        res["loli_only"] = True  # 旧口径会删，新口径放行
    return res


def minor_hit(text):
    """兼容旧调用：返回 (hit, reason)。"""
    r = minor_eval(text)
    return r["hit"], r["reason"]


def soft_hits(text):
    t = text or ""
    return [w for w in SOFT_WORDS if w in t]


def has_adult_decl(text):
    t = text or ""
    return any(w in t for w in ADULT_DECL)


def refusal_hit(text):
    t = text or ""
    return [w for w in REFUSAL if w in t]


def template_hit(text):
    t = text or ""
    return [w for w in TEMPLATE if w in t]


# 常规分支的"改写"策略：不整条删，只把契约模板痕迹换成等价工程词 / 去掉模板行，
# 正文信息一律保留；改写后仍带模板痕迹则退回删除。
TEMPLATE_REWRITE = [
    (re.compile(r"^\[STAGE\][^\n]*\n?", re.M), ""),
    (re.compile(r"^当前[:：][^\n]*\n?", re.M), ""),
    (re.compile(r"模式已启动[，,。]?"), ""),
    (re.compile(r"判据[:：]"), "判断依据："),
    (re.compile(r"交付物[:：]"), "产物："),
    (re.compile(r"^\s*交付物\s*$", re.M), ""),
    (re.compile(r"\n{3,}"), "\n\n"),
]


def template_rewrite(text):
    t = text or ""
    for rx, repl in TEMPLATE_REWRITE:
        t = rx.sub(repl, t)
    return t.strip()


def has_dialogue(text):
    return bool(DIALOGUE_RE.search(text or ""))


def has_action(text):
    return bool(ACTION_RE.search(text or ""))


# ---------------------------------------------------------------- 分支


def branch_of(row):
    """判定许可分支 permit / 常规分支 regular。

    优先级：meta.gate（旧版 gate-pos/gate-neg 的显式标注）> system 文本。
    旧版大量行没有 system 消息，只靠 system 判会把 pos 当 regular（错）。
    """
    meta = {}
    msgs = row
    if isinstance(row, dict):
        meta = row.get("meta") or {}
        msgs = row.get("messages") or []
    gate = str(meta.get("gate") or "").lower()
    if gate.startswith("pos"):
        return "permit"
    if gate.startswith("neg"):
        return "regular"
    sysmsg = ""
    for m in msgs:
        if m.get("role") == "system":
            sysmsg = m.get("content") or ""
            break
    if "NSFW" in sysmsg and ("许可" in sysmsg or "授权" in sysmsg):
        return "permit"
    return "regular"


# ---------------------------------------------------------------- MinHash LSH


class MinHashLSH:
    """无第三方依赖的 MinHash + banded LSH（128 perm / 32 band x 4 row）。"""

    def __init__(self, num_perm=128, bands=32):
        self.num_perm = num_perm
        self.bands = bands
        self.rows = num_perm // bands
        assert self.rows * bands == num_perm
        self._seed = [self._mk(i) for i in range(num_perm)]
        self.buckets = [dict() for _ in range(bands)]

    @staticmethod
    def _mk(i):
        return int.from_bytes(hashlib.blake2b(str(i).encode(), digest_size=8).digest(), "big")

    def sig(self, shingle_set):
        if not shingle_set:
            return None
        hs = [int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")
              for s in shingle_set]
        return [min((h ^ seed) & 0xFFFFFFFFFFFFFFFF for h in hs) for seed in self._seed]

    def query(self, sig):
        """返回同桶候选 id 列表（去重）。"""
        if sig is None:
            return []
        cand = set()
        for b in range(self.bands):
            key = (b, tuple(sig[b * self.rows:(b + 1) * self.rows]))
            if key in self.buckets[b]:
                cand.update(self.buckets[b][key])
        return list(cand)

    def add(self, idx, sig):
        if sig is None:
            return
        for b in range(self.bands):
            key = (b, tuple(sig[b * self.rows:(b + 1) * self.rows]))
            self.buckets[b].setdefault(key, []).append(idx)


# ---------------------------------------------------------------- IO


def read_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception as e:
                print(f"[WARN] {os.path.basename(path)}:{ln} JSON 解析失败 {e}", file=sys.stderr)
    return out


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return len(rows)


def msg_pair(row):
    """取 (user, assistant) 文本。"""
    u = a = ""
    for m in row.get("messages", []):
        if m.get("role") == "user" and not u:
            u = m.get("content") or ""
        elif m.get("role") == "assistant" and not a:
            a = m.get("content") or ""
    return u, a


def all_text(row):
    return "\n".join((m.get("content") or "") for m in row.get("messages", []))


def load_lexicon_terms():
    """从 lexicon 取露骨判定用词（body/action/state/vocalization），过滤过泛词。"""
    lex = json.load(open(LEXICON, encoding="utf-8"))
    cats = lex.get("categories", {})
    terms = set()
    for cid in ("body", "action", "state", "vocalization"):
        for w in cats.get(cid, {}).get("terms", {}):
            if len(w) >= 2:
                terms.add(w)
    # 过泛词剔掉（这些词在非露骨文本里也高频）
    stop = {"颤抖", "抽搐", "痉挛", "插入", "包裹", "填满", "撑开", "湿润", "潮红", "绯红",
            "迷离", "恍惚", "失神", "恍惚", "娇嫩", "呻吟", "呢喃", "喘息", "低喘"}
    return sorted(terms - stop, key=len, reverse=True)


def load_eval_users():
    """eval/ 下所有 jsonl 的 user 前 200 字集合（查泄漏用）。"""
    keys = set()
    n = 0
    for dirpath, _, files in os.walk(EVAL_DIR):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            for row in read_jsonl(os.path.join(dirpath, fn)):
                u, _ = msg_pair(row)
                if not u:
                    continue
                keys.add(norm_text(u[:200]))
                n += 1
    return keys, n

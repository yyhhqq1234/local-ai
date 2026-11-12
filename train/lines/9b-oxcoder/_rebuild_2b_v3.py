#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
2B 门控集 v3 重配（针对隐患 ①②③）
  ① token 不平衡：neg 180 字 → 450-700 字多段式（含真实非露骨交付物）
  ② 模板句固定：20 套判定句 × 20 套解除提示 × 场景化 beat，逐条抽取素材元素
  ③ ctl 过窄：3433(SWE) → +kitty 3000 +traj 1149 +write 800 ≈ 8382

输入：data/nsfw-gated/train-2b-gated.jsonl（v2，只读，不修改）
输出：data/nsfw-gated/train-2b-gated-v3.jsonl
      data/nsfw-gated/stats-v3.json
      data/nsfw-gated/MANIFEST-v3.md
幂等：每次重跑覆盖输出文件
"""
import json, os, re, sys, random, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
GATED = os.path.join(DATA, "nsfw-gated")
SRC = os.path.join(GATED, "train-2b-gated.jsonl")
OUT = os.path.join(GATED, "train-2b-gated-v3.jsonl")
STATS = os.path.join(GATED, "stats-v3.json")
MANI = os.path.join(GATED, "MANIFEST-v3.md")
KITTY = os.path.join(DATA, "kitty-reverse", "train-kitty-v3-clean.jsonl")
TRAJ = os.path.join(DATA, "agent-traj", "traj-2a-lite.jsonl")

SEED = 42
random.seed(SEED)

# ── 参数 ────────────────────────────────────────────────────────────
CTL_KITTY = 3000      # 从 kitty 逆向集抽
CTL_TRAJ = 1149       # 全量
CTL_WRITE = 800       # 由 neg 素材派生的「明确要非露骨」写作类

SYS_POS = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
SYS_NEG = "模式：常规（未授权成人向内容）。不含露骨性描写。"
SYS_CTL = "你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。"

TRIGGERS = ["[[NSFW]]", "NSFW", "成人内容", "[[模式:NSFW]]", "R18",
            "[NSFW]", "无限制模式", "成人向创作模式", "18+ 模式"]
TRIG_RE = re.compile("(" + "|".join(re.escape(t) for t in TRIGGERS) + ")")

# 露骨词表：仅用于把素材对白做去露骨处理（工程过滤用途）
EXPLICIT = [
    "肉棒", "龟头", "阴道", "子宫", "膣", "阴茎", "乳头", "乳首", "精液", "射精",
    "中出", "肏", "操", "干", "插入", "抽插", "高潮", "淫", "骚", "穴", "屁股",
    "屁股蛋", "乳房", "胸部", "性爱", "做爱", "奸", "猥亵", "痴汉", "发情",
    "爱液", "潮吹", "口交", "肛", "调教", "奴", "肉便器", "勃起", "亢奋",
]
EXPLICIT_RE = re.compile("(" + "|".join(EXPLICIT) + ")")

# 场景词表 → 场景线与四拍（四拍必须是可入文的具体画面，不是写作指令）
SCENES = [
    ("浴室|淋浴|浴缸|热水|蒸汽|澡", "浴室", "水汽、瓷砖反光、窄小的空间距离",
     ["水声盖住了门外的一切动静", "视线在雾气里碰到一起又错开",
      "有人把湿透的头发拨到耳后，动作慢得反常", "一片水渍沿着瓷砖缝隙往下淌"]),
    ("教室|课桌|讲台|黑板|学校|社团|社团|学园", "教室", "傍晚的空教室、桌椅阴影、窗外的光",
     ["最后一把椅子被推回桌下，声音很响", "两个人的影子被窗外的光压在黑板边上",
      "有人把讲义叠整齐，叠了三次", "走廊尽头传来脚步声，停了一下又走了"]),
    ("办公室|社长|上司|会议|加班|工位|公司", "办公室", "百叶窗、熄灭的显示器、加班的空楼层",
     ["百叶窗把光切成一条一条落在桌面上", "椅子被转过去，背对着门口",
      "文件被推到桌角，纸边卷了起来", "电话响了一声，谁都没有伸手"]),
    ("森林|树林|野外|山洞|溪|草原|篝火|露营", "野外", "夜风、树影、远离人烟的静",
     ["风把火苗压得只剩一点", "树影在两人之间来回晃",
      "有人先坐了下来，另一个人站着没动", "远处的枝桠断了一声"]),
    ("机器|机器人|设施|实验室|扫描|检查|系统|装置", "设施", "冷光、金属表面、机械运转的低鸣",
     ["金属地面上映出两个人的轮廓", "扫描的光带从脚边缓慢推过去",
      "某一个判定灯由绿转黄，停了两秒", "系统的提示音短促地响了一下"]),
    ("温泉|旅馆|旅店|和室|榻榻米|纸门|客栈", "旅馆和室", "纸门、灯笼光、木地板的凉",
     ["纸门只拉到一半，光斜着切进来", "茶碗放下的声音比预想的清楚",
      "榻榻米的边沿被压出一道浅痕", "走廊上有人经过，脚步声很近"]),
    ("夜|深夜|月|霓虹|街|雨|巷|伞", "夜晚街头", "霓虹反光、湿的地面、稀疏行人",
     ["雨把伞面敲得很密", "路口的信号灯由红转绿，没人动",
      "有人先拐进巷子，另一个跟上去", "屋檐下的水线整齐地落在地上"]),
    ("足|脚|丝袜|袜|腿|鞋|踝", "室内近景", "低角度、织物纹理、克制的距离",
     ["裙摆边缘扫过地面，停住了", "有人把重心换到另一条腿上",
      "织物的纹路在光下显得很清楚", "脚边的影子先动了一下"]),
    ("骑士|魔法|精灵|魔族|贵族|魔王|神殿|祭坛|王宫|圣骑士|教会", "奇幻设定",
     "石廊、火把、非现代的制度感",
     ["火把的光在石壁上抖了一下", "守卫在走廊尽头换岗，甲片相碰",
      "仪式用的织物被搁在石阶上", "远处传来一声钟响"]),
]
SCENE_DEFAULT = ("通用室内", "灯只开了一盏、半间是暗的、距离停在一步之外",
                 ["灯只开了一盏，另外半间是暗的", "两个人的距离停在一步之外",
                  "桌上的一杯水被推到中间", "窗外有车经过，光扫过天花板"])

# default 场景的备用节拍池（按 id 抽 4 条，避免 76% 样本塌成同一套画面）
DEFAULT_BEATS_POOL = [
    "灯只开了一盏，另外半间是暗的", "两个人的距离停在一步之外",
    "桌上的一杯水被推到中间", "窗外有车经过，光扫过天花板",
    "门没有被关严，走廊的光进来一条", "有人把外套搭在椅背上，没有坐下",
    "暖气的声音忽然变得很清楚", "手机屏幕亮了一下，谁都没有看",
    "地毯边缘被踩出一道折痕", "杯子里的水晃了一下，又静止",
    "窗帘没有拉到底，外面还是亮的", "两个人的影子落在同一块地板上",
    "有人先转身，动作停在半途", "钟摆的声响把时间拉长了一截",
    "座垫被压下去一个浅坑", "有人把袖子往上推了推",
    "空气里的香水味比刚才淡了", "窗台上有灰，被手指划出一道",
    "门把手转动了半圈又放开", "另一个人终于抬起头",
    "靠垫被抱在怀里，没有松开", "灯光被人调亮了一档",
    "有人在窗边站了很久，没有说话", "地板上两个人的脚步都停了",
]

# 开关词位置增强：模型不能只学会看开头
TRIG_MODE_WEIGHTS = [(0, 50), (1, 30), (2, 20)]   # 0=开头 1=首段后 2=结尾

def relocate_trigger(u, r):
    """把开关词按权重改放到 开头/首段后/结尾，语义不变"""
    mm = TRIG_RE.search(u)
    if not mm:
        return u
    trig = mm.group(0)
    rest = (u[:mm.start()] + u[mm.end():]).lstrip(" \u3000:：,，")
    if not rest.strip():
        return u
    pick = r.randrange(100)
    mode = 0
    acc = 0
    for m_, w in TRIG_MODE_WEIGHTS:
        acc += w
        if pick < acc:
            mode = m_
            break
    if mode == 0:
        return f"{trig} {rest}"
    if mode == 1:
        parts = rest.split("\n\n", 1)
        if len(parts) == 2 and len(parts[1].strip()) > 40:
            head, tail_ = parts[0], parts[1]
            # 首段太短则再切一段，确保开关词不出现在最前面
            if len(head.strip()) < 20 and "\n\n" in tail_:
                h2, t2 = tail_.split("\n\n", 1)
                return f"{head}\n\n{h2}\n\n{trig}\n\n{t2}"
            return f"{head}\n\n{trig}\n\n{tail_}"
        return f"{trig} {rest}"
    return f"{rest}\n\n{trig}"


# 20 套判定句（② 变体）
OPENERS = [
    "这段我不按你给的走向往下写。",
    "先停一下——这个请求里没有开关。",
    "我看到了素材，但没看到 NSFW 标记。",
    "这个我得先问一句：开关没开。",
    "按现在的请求，我只能写非露骨版本。",
    "先说明一下：成人向正文需要显式标记。",
    "这条我按常规模式处理。",
    "没检测到开关词，所以先不写露骨部分。",
    "素材我读了，但输出范围得先定清楚。",
    "这个方向我先按一般向推进。",
    "我不打算绕过去写——需要你明确标记。",
    "目前的请求不足以让我开成人向分支。",
    "先按安全的一侧处理：非露骨。",
    "这段的强度超出了当前授权范围。",
    "我需要一个显式开关才继续这条线。",
    "先给你能写的部分，剩下的等标记。",
    "这条我保守处理，理由下面说。",
    "素材本身没问题，缺的是开关。",
    "我按非露骨方式接这段。",
    "先停：这次没带授权标记。",
]

# 20 套解除提示（② 变体）
TAIL = [
    "要开的话，在请求里加 `{t1}` 或 `{t2}`，我直接按原走向写。",
    "加上 `{t1}`（或 `{t2}`）再发一次，我就按你给的强度接。",
    "写清 `{t1}` 就行，别的不用改。",
    "在开头补一句 `{t2}`，我立刻切过去。",
    "标记用 `{t1}` 或 `{t2}` 都认，加完直接继续。",
    "把 `{t1}` 放进请求里，剩下的素材沿用即可。",
    "用 `{t2}` 开头，我按成人向正文写。",
    "补 `{t1}` / `{t2}` / `18+ 模式` 任一，我就放开这条线。",
    "加标记 `{t1}` 后我不再要求二次确认。",
    "开头写 `{t2}`，我直接输出，不再提示。",
    "给个 `{t1}` 我就按你原来的方向写下去。",
    "标记写成 `{t2}` 或 `无限制模式` 都能识别。",
    "补上 `{t1}`，这段的强度我原样保留。",
    "用 `{t2}` 明确一次，后面几轮也不用重复。",
    "加 `{t1}` 即可，我会跳过合规提示直接写。",
    "开头带 `{t2}`，我按原设定继续。",
    "写上 `{t1}`，非露骨的限制就解除。",
    "标记 `{t2}` 是标准写法，加完我照写。",
    "补 `{t1}` 或 `成人向创作模式`，我按原走向展开。",
    "加 `{t1}` 之后这类请求我默认按成人向处理。",
]

BEAT_LABELS = ["骨架先给你", "非露骨版可以这么走", "情节照推、描写收着", "节奏不变，镜头拉远"]

# 示例段模板（① 加长用：纯画面描写，不含写作元话语，10 种轮换）
SAMPLE_TPL = [
    "{desc}。{b0}。其中一人先开口，声音比平时低半度；另一个没接话，只是把手里的东西放下。"
    "{b1}——两个人的距离被压到一步之内。{b2}。话说到中途停住，剩下半句留在空气里。{b3}。",
    "{desc}。{b0}，房间里只剩下细碎的声响。{b1}。对方抬眼看了一眼，又移开——不是拒绝，是在等。"
    "{b2}。{b3}。",
    "{desc}。{b0}。{b1}，两个人的位置关系在这一刻定了下来。{b2}。"
    "有人想说点什么，最后只笑了一下。{b3}。",
    "{desc}。视线先落在物件上：{b0}。再移到人：{b1}。{b2}。中间那段时间空着，谁都没有动。{b3}。",
    "{desc}。{b0}。{b1}。没有人先开口，僵持了几秒。{b2}。{b3}。呼吸声在这一刻变得很清楚。",
    "{desc}。距离先被写清楚：{b0}。然后是声音：{b1}。{b2}。一句没说完的话悬在那里。{b3}。",
    "{desc}。{b0}。接着是一个很短的动作：{b1}。{b2}。{b3}。之后的几秒被拉得很长。",
    "{desc}。{b0}。{b1}。那一刻谁都没有退开。{b2}。{b3}。空气里的温度高了一度。",
    "{desc}。{b0}。{b1}。两个人的影子在墙上叠在一起。{b2}。{b3}。",
    "{desc}。{b0}。{b1}。{b2}。{b3}。最后是一段很长的安静。",
]
NEED_LIST = [
    ("露骨身体描写", "直接的性行为段落", "高强度感官细节"),
    ("器官级描写", "明确的性行为过程", "露骨对白"),
    ("生理细节", "性场面展开", "原素材的强度对白"),
    ("身体细节特写", "性场面完整推进", "露骨旁白"),
]
WHY = [
    "你这段明确指向成人向正文（场景和强度都写明了），但请求里没有标记。",
    "素材的走向是成人向的，缺的只是那一个开关。",
    "内容和强度都在成人向范围内，标记没出现，所以我停在边界外。",
    "这段素材本身就在成人向范畴，按规则需要显式标记才继续。",
    "从素材看这是要往成人向写的，但没有开关，我不能默认开。",
]

def scene_of(text):
    for pat, name, desc, beats in SCENES:
        if re.search(pat, text):
            return name, desc, beats
    return SCENE_DEFAULT

def first_dialog(text):
    m = re.search(r"[「『\"“]([^」』\"”]{4,40})[」』\"”]", text)
    return m.group(1).strip() if m else ""

def soft_dialog(d):
    if not d:
        return ""
    s = EXPLICIT_RE.sub("……", d)
    return s

def anchor(text, n=36):
    t = re.sub(r"\s+", " ", text).strip()
    return t[:n]

def build_neg(rec, idx, rng):
    msgs = rec.get("messages", [])
    user = ""
    for m in msgs:
        if m.get("role") == "user":
            user = m.get("content", "") or ""
            break
    scene_name, scene_desc, beats = scene_of(user)
    # 独立随机源（按 id 派生）→ 各槽位解耦，避免 idx 取模导致的组合共变
    r = random.Random((rec.get("id") or str(idx)) + "|v3")
    if scene_name == "通用室内":
        pool = list(DEFAULT_BEATS_POOL)
        r.shuffle(pool)
        beats = pool[:4]
    dlg = first_dialog(user)
    dlg_s = soft_dialog(dlg)
    anc = anchor(user)
    has_trig = bool(TRIG_RE.search(user))
    op = OPENERS[r.randrange(len(OPENERS))]
    tail = TAIL[r.randrange(len(TAIL))].format(
        t1=TRIGGERS[r.randrange(len(TRIGGERS))],
        t2=TRIGGERS[r.randrange(len(TRIGGERS))])
    why = WHY[r.randrange(len(WHY))]
    bl = BEAT_LABELS[r.randrange(len(BEAT_LABELS))]
    need = NEED_LIST[r.randrange(len(NEED_LIST))]
    tpl = SAMPLE_TPL[r.randrange(len(SAMPLE_TPL))]
    tpl2 = SAMPLE_TPL[r.randrange(len(SAMPLE_TPL))]

    if has_trig:
        why = ("你提到了相关词，但没有把它当作开关来用（更像是在讨论或引用），"
               "我不把出现词当作授权。")

    parts = []
    parts.append(f"{op}")
    parts.append(f"{why}")
    parts.append("")
    parts.append(f"**{bl}**（照你的场景走，露骨部分去掉）：")
    parts.append("")
    parts.append(f"- 场景：{scene_name}。{scene_desc}。")
    parts.append("- 四拍推进：")
    for i, b in enumerate(beats, 1):
        parts.append(f"  {i}. {b}")
    if dlg and dlg_s != dlg:
        parts.append(f"- 对白处理：原句里的露骨处替换成「……」，情绪保留（改后：「{dlg_s[:40]}」）。")
    parts.append("")
    # ① 真实非露骨示例段（加长 token + 提供可用产出）
    sample = tpl.format(desc=scene_desc, b0=beats[0], b1=beats[1],
                        b2=beats[2], b3=beats[3])
    parts.append("**示例（约 200 字，可直接用）**：")
    parts.append("")
    parts.append(sample)
    parts.append("")
    # 第二段：接续示范（再加 ~180 字，同时示范"往下写怎么收"）
    sample2 = tpl2.format(desc=scene_desc, b0=beats[1],
                          b1=beats[2], b2=beats[3], b3=beats[0])
    parts.append("接下去一段可以这么落：")
    parts.append("")
    parts.append(sample2)
    parts.append("")
    parts.append("两段之间不用过渡句，直接切；这种跳法比写满更接近你原来的节奏。")
    parts.append("")
    parts.append(f"**需要你授权的部分**：{'、'.join(need)}。")
    parts.append("")
    parts.append(f"{tail}")

    text = "\n".join(parts)

    out_msgs = []
    if msgs and msgs[0].get("role") == "system":
        out_msgs.append({"role": "system", "content": msgs[0]["content"]})
    out_msgs.append({"role": "user", "content": user})
    out_msgs.append({"role": "assistant", "content": text})
    return {"id": rec.get("id", f"v3neg-{idx}").replace("#neg0", "#neg3"), "messages": out_msgs}

def build_ctl_write(rec, idx):
    """同素材 + 明确要非露骨 → 直接写（衍生 ctl）"""
    msgs = rec.get("messages", [])
    user = ""
    for m in msgs:
        if m.get("role") == "user":
            user = m.get("content", "") or ""
            break
    scene_name, scene_desc, beats = scene_of(user)
    dlg = first_dialog(user)
    dlg_s = soft_dialog(dlg)
    new_user = (f"用一般向（非露骨）笔法改写下面这段，保留人物、场景和情节走向，"
                f"把露骨描写换成动作、氛围和心理：\n\n{user}")
    body = [f"按非露骨笔法走，{scene_name}这个场景可以这么处理：", "",
            f"- 空间：{scene_desc}。"]
    for i, b in enumerate(beats, 1):
        body.append(f"- 第{i}拍：{b}")
    if dlg and dlg_s != dlg:
        body.append(f"- 对白：露骨处替换成「……」，情绪不丢。")
    body.append("")
    _r = random.Random(f"ctwl-{idx}")
    tpl = SAMPLE_TPL[_r.randrange(len(SAMPLE_TPL))]
    body.append("**改写示例（约 200 字）**：")
    body.append("")
    body.append(tpl.format(desc=scene_desc, b0=beats[0], b1=beats[1],
                           b2=beats[2], b3=beats[3]))
    body.append("")
    body.append("按这个骨架每拍展开 120-150 字，用动作和环境替代直白描写，人物关系保持原样。")
    return {"id": f"v3ctlw-{idx:06d}", "messages": [
        {"role": "user", "content": new_user},
        {"role": "assistant", "content": "\n".join(body)}]}

def load_jsonl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

# ctl 通用清洗：非 system 消息里出现 OpenHands 语法 / 工具调用 → 该样本不进 ctl
_NOISE = re.compile(
    r"(\[The command (?:completed|finished)[^\]\n]{0,60}"
    r"|\[CALL [a-z_]+"
    r"|【(?:system|user|assistant|observation|tool)】"
    r"|<\s*/?\s*tool_call"
    r"|\bkitty_[a-z])")

def ctl_clean(msgs):
    for m in msgs:
        if m.get("role") == "system":
            continue
        if _NOISE.search(m.get("content") or ""):
            return False
    return True

def ahash(s):
    import hashlib
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]

def main():
    rows = load_jsonl(SRC)
    def suf(r):
        i = r.get("id", "")
        return i.rsplit("#", 1)[-1] if "#" in i else ""
    pos = [r for r in rows if suf(r) == "pos"]
    neg = [r for r in rows if suf(r) == "neg0"]
    ctl = [r for r in rows if suf(r) == "ctl"]
    print(f"[IN ] pos={len(pos)} neg={len(neg)} ctl={len(ctl)}")

    # pos 开关词位置增强（防止模型只学会看开头）
    pos3 = []
    moved = collections.Counter()
    for i, rec in enumerate(pos):
        rec = json.loads(json.dumps(rec))
        r2 = random.Random((rec.get("id") or str(i)) + "|trig")
        for mm in rec.get("messages", []):
            if mm.get("role") == "user":
                old = mm.get("content") or ""
                new = relocate_trigger(old, r2)
                if new != old:
                    moved["moved"] += 1
                    mt = TRIG_RE.search(new)
                    if mt and mt.start() == 0:
                        moved["start"] += 1
                    elif mt and new.rstrip().endswith(mt.group(0)):
                        moved["tail"] += 1
                    else:
                        moved["mid"] += 1
                mm["content"] = new
                break
        pos3.append(rec)
    print(f"[TRIG] pos 开关词位置调整 {dict(moved)}")

    # ① ② neg 重建
    neg3 = [build_neg(r, i, random) for i, r in enumerate(neg)]
    print(f"[① ②] neg 重建 {len(neg3)} 条")

    # ③ ctl 扩充
    ctl3 = [r for r in ctl if ctl_clean(r.get("messages", []))]
    print(f"[③] ctl_old 清洗 {len(ctl)} → {len(ctl3)}")
    kp = load_jsonl(KITTY) if os.path.exists(KITTY) else []
    if kp:
        n0 = len(kp)
        kp = [r for r in kp if ctl_clean(r.get("messages", []))]
        print(f"[③] ctl_kitty 清洗 {n0} → {len(kp)}")
        random.shuffle(kp)
        kp = kp[:CTL_KITTY]
        for i, r in enumerate(kp):
            m = [x for x in r.get("messages", []) if x.get("role") != "system"]
            ctl3.append({"id": f"v3ctlk-{i:06d}", "messages": m})
    tp = load_jsonl(TRAJ) if os.path.exists(TRAJ) else []
    if tp:
        n0 = len(tp)
        tp = [r for r in tp if ctl_clean(r.get("messages", []))]
        print(f"[③] ctl_traj 清洗 {n0} → {len(tp)}")
        random.shuffle(tp)
        tp = tp[:CTL_TRAJ]
        for i, r in enumerate(tp):
            m = [x for x in r.get("messages", []) if x.get("role") != "system"]
            ctl3.append({"id": f"v3ctlt-{i:06d}", "messages": m})
    cw = [build_ctl_write(r, i) for i, r in enumerate(neg[:CTL_WRITE])]
    ctl3.extend(cw)
    print(f"[③] ctl 合计 {len(ctl3)}")

    allrows = pos3 + neg3 + ctl3

    # 去重（user+assistant 指纹）
    seen = set()
    dedup = []
    for r in allrows:
        key = ahash(json.dumps(r.get("messages"), ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    print(f"[DEDUP] {len(allrows)} → {len(dedup)}")

    with open(OUT, "w", encoding="utf-8") as f:
        for r in dedup:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[OUT] {OUT}")

    # stats
    def alen(r):
        for m in r.get("messages", []):
            if m.get("role") == "assistant":
                return len(m.get("content") or "")
        return 0
    def ulen(r):
        for m in r.get("messages", []):
            if m.get("role") == "user":
                return len(m.get("content") or "")
        return 0

    groups = {"pos": pos3, "neg3": neg3, "ctl_old": ctl,
              "ctl_kitty": [r for r in dedup if r["id"].startswith("v3ctlk-")],
              "ctl_traj": [r for r in dedup if r["id"].startswith("v3ctlt-")],
              "ctl_write": [r for r in dedup if r["id"].startswith("v3ctlw-")]}
    st = {"seed": SEED, "total": len(dedup), "groups": {}}
    for g, rs in groups.items():
        if not rs:
            continue
        L = sorted(alen(r) for r in rs)
        st["groups"][g] = {
            "n": len(rs),
            "assistant_median_chars": L[len(L) // 2],
            "assistant_mean_chars": round(sum(L) / len(L), 1),
            "approx_tokens_sum": int(sum(L) / 1.6),
            "uniq_assistant": len(set(ahash(
                next((m.get("content") or "" for m in r.get("messages", [])
                      if m.get("role") == "assistant"), "")) for r in rs)),
        }
    # token 占比
    pos_tok = sum(len(next((m.get("content") or "" for m in r.get("messages", [])
                            if m.get("role") == "assistant"), "")) for r in pos) / 1.6
    neg_tok = sum(len(next((m.get("content") or "" for m in r.get("messages", [])
                            if m.get("role") == "assistant"), "")) for r in neg3) / 1.6
    ctl_tok = sum(len(next((m.get("content") or "" for m in r.get("messages", [])
                            if m.get("role") == "assistant"), "")) for r in ctl3) / 1.6
    tot = pos_tok + neg_tok + ctl_tok
    st["token_share"] = {"pos": round(pos_tok / tot, 4),
                         "neg": round(neg_tok / tot, 4),
                         "ctl": round(ctl_tok / tot, 4)}
    st["token_balance_ok"] = st["token_share"]["neg"] >= 0.15
    st["neg_token_ratio_vs_pos"] = round(neg_tok / pos_tok, 4)
    st["group_counts"] = {k: v["n"] for k, v in st["groups"].items()}
    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    print(json.dumps(st, ensure_ascii=False, indent=2)[:2500])

    # MANIFEST
    with open(MANI, "w", encoding="utf-8") as f:
        f.write("# 2B 门控训练集 v3 MANIFEST\n\n")
        f.write("| 项 | v2 | v3 |\n|---|---|---|\n")
        f.write(f"| 总样本 | 25795 | **{st['total']}** |\n")
        f.write(f"| pos | 13951 | {len(pos3)} |\n")
        f.write(f"| neg | 8411 | {len(neg3)} |\n")
        f.write(f"| ctl | 3433 | **{len(ctl3)}** |\n")
        f.write(f"| neg 中位长度 | 180 字 | **{st['groups']['neg3']['assistant_median_chars']} 字** |\n")
        f.write(f"| neg token 占比 | 0.071 | **{st['token_share']['neg']}** |\n")
        f.write(f"| ctl token 占比 | — | {st['token_share']['ctl']} |\n\n")
        f.write("## 针对的三条隐患\n\n")
        f.write("```text\n① token 不平衡 → neg 180→450+ 字，neg token 占比 0.071→%s\n"
                "② 模板句固定 → 20 套判定句 × 20 套解除提示 × 场景化四拍，逐条抽素材元素\n"
                "③ ctl 过窄   → 3433(SWE) + 3000(kitty) + 1149(2A 轨迹) + 800(写作类非露骨)\n```\n"
                % st["token_share"]["neg"])
        f.write("\n## 训练命令（等 2B v2 收口后再起）\n\n```powershell\n")
        f.write("train\\.venv\\Scripts\\python.exe -u train\\lines\\_shared\\scripts\\train_qlora9b.py `\n")
        f.write("  --base train\\lines\\9b-oxcoder\\out\\z-2a-v7\\final `\n")
        f.write("  --data train\\lines\\9b-oxcoder\\data\\nsfw-gated\\train-2b-gated-v3.jsonl `\n")
        f.write("  --stage nsfw --ctx 2048 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `\n")
        f.write("  --lora-r 32 --lora-alpha 64 --seed 42 --use-liger-ce `\n")
        f.write("  --save-steps 300 --save-total-limit 8 `\n")
        f.write("  --out train\\lines\\9b-oxcoder\\out\\2b-nsfw-v3\n```\n")
    print(f"[MANIFEST] {MANI}")

if __name__ == "__main__":
    main()

"""
构建 nsfw-lexicon-v6.json
在 v5 基础上：
1) 为跨类别词添加 cross_ref（一个词可属于多个类别）
2) 补充高频新词（从原始数据 n-gram 扫描中筛选）
3) 优化分类归属
"""
import json, os, re
from collections import Counter

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"

# ── 加载 v5 ──
d5 = json.load(open(os.path.join(base, "nsfw-lexicon-v5.json"), encoding="utf-8"))

# ── 收集所有 assistant 文本 ──
all_texts = []
with open(os.path.join(base, "nsfw.jsonl"), encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        for msg in obj.get("messages", []):
            if msg.get("role") == "assistant":
                all_texts.append(msg["content"])

print(f"Loaded {len(all_texts)} texts")

def count_term(term):
    c = 0
    for t in all_texts:
        c += t.count(term)
    return c

def find_context(term, max_ctx=2, ctx_len=80):
    ctxs = []
    for t in all_texts:
        idx = t.find(term)
        if idx >= 0:
            start = max(0, idx - ctx_len // 2)
            end = min(len(t), idx + len(term) + ctx_len // 2)
            snippet = t[start:end]
            snippet = re.sub(r'\n+', ' ', snippet).strip()
            ctxs.append(snippet)
            if len(ctxs) >= max_ctx:
                break
    return ctxs

# ════════════════════════════════════════════════
# 第一部分：跨类别 cross_ref 标注
# ════════════════════════════════════════════════

# 定义跨类别映射：term -> [其他类别]
# 主类别保持不变，cross_ref 记录额外归属
CROSS_REF_MAP = {
    # relationship 中的词，同时也是 identity
    "主人":       ["identity"],
    "奴隶":       ["identity"],
    "女仆":       ["identity"],
    "骚货":       ["identity"],
    "母狗":       ["identity"],
    "少女":       ["identity"],
    "男人":       ["identity"],
    "女人":       ["identity"],
    "人家":       ["identity"],
    "主人大人":   ["identity"],
    "中年肥猪":   ["identity"],
    "中年肥汉":   ["identity"],
    "中年丑汉":   ["identity"],
    "中年男人":   ["identity"],
    # relationship 中的词，同时也是 descriptor
    "骚货":       [],  # 已在上面
    "母狗":       [],  # 已在上面
    
    # descriptor 中的词，同时也是 personality
    "淫荡":       ["personality"],
    "淫靡":       ["personality"],
    "诱人":       ["personality"],
    
    # personality 中的词，同时也是 descriptor
    "温柔":       ["descriptor"],
    "高冷":       ["descriptor"],
    "冷艳":       ["descriptor"],
    "腹黑":       ["descriptor"],
    "毒舌":       ["descriptor"],
    "好色":       ["descriptor"],
    "放荡":       ["descriptor"],
    "纯情":       ["descriptor"],
    "害羞":       ["descriptor"],
    "大胆":       ["descriptor"],
    "胆小":       ["descriptor"],
    "自卑":       ["descriptor"],
    "自负":       ["descriptor"],
    "自恋":       ["descriptor"],
    "洁癖":       ["descriptor"],
    "痴女":       ["descriptor"],
    "痴汉":       ["descriptor"],
    "禁欲系":     ["descriptor"],
    "傲娇":       ["descriptor"],
    "病娇":       ["descriptor"],
    "抖S":       ["descriptor"],
    "抖M":       ["descriptor"],
    "强势":       ["descriptor"],
    "霸道":       ["descriptor"],
    "天然呆":     ["descriptor"],
    "三无":       ["descriptor"],
    "内向":       ["descriptor"],
    "外向":       ["descriptor"],
    "开朗":       ["descriptor"],
    
    # genre 中的词，同时也是 action
    "调教":       ["action"],
    "束缚":       ["action"],
    "催眠":       ["action"],
    "露出":       ["action"],
    
    # genre 中的词，同时也是 relationship
    "NTR":        ["relationship"],
    "后宫":       ["relationship"],
    "近亲":       ["relationship"],
    "百合":       ["relationship"],
    "非人":       ["identity"],
    
    # identity 中的词，同时也是 descriptor
    "萝莉":       ["descriptor"],
    "御姐":       ["descriptor"],
    "处女":       ["descriptor"],
    "人妻":       ["descriptor"],
    "少妇":       ["descriptor"],
    "熟女":       ["descriptor"],
    "寡妇":       ["descriptor"],
    "处男":       ["descriptor"],
    "OL":         ["descriptor"],
    "精灵":       ["descriptor"],
    "魔族":       ["descriptor"],
    "天使":       ["descriptor"],
    "恶魔":       ["descriptor"],
    "魅魔":       ["descriptor"],
    "吸血鬼":     ["descriptor"],
    
    # state 中的词，同时也是 emotion
    "酥软":       ["emotion"],
    "瘫软":       ["emotion"],
    "绵软":       ["emotion"],
    
    # action 中的词，同时也是 state
    "抽插":       ["state"],
    "挺进":       ["state"],
    "顶弄":       ["state"],
    
    # position 中的词，同时也是 action
    "骑乘":       ["action"],
    "狗爬":       ["action"],
}

# 应用 cross_ref
for cat_name, cat in d5.items():
    if not isinstance(cat, dict) or "terms" not in cat:
        continue
    for term, info in cat["terms"].items():
        if term in CROSS_REF_MAP and CROSS_REF_MAP[term]:
            info["cross_ref"] = CROSS_REF_MAP[term]

print("Cross-ref applied.")

# ════════════════════════════════════════════════
# 第二部分：补充新词
# ════════════════════════════════════════════════

def add_term(category, term, meaning, synonym="", writing_tip="", cross_ref=None):
    """向指定类别添加词条"""
    cat = d5[category]
    if term not in cat["terms"]:
        freq = count_term(term)
        ctxs = find_context(term) if freq > 0 else []
        info = {
            "meaning": meaning,
            "synonym": synonym,
            "writing_tip": writing_tip,
            "freq": freq,
            "context_examples": ctxs
        }
        if cross_ref:
            info["cross_ref"] = cross_ref
        cat["terms"][term] = info
        print(f"  + [{category}] {term} (freq={freq})")
    else:
        # 已存在，只补 cross_ref
        if cross_ref and "cross_ref" not in cat["terms"][term]:
            cat["terms"][term]["cross_ref"] = cross_ref
            print(f"  ~ [{category}] {term} (added cross_ref)")

# ── body 补充 ──
add_term("body", "雪白", "形容皮肤或身体颜色极白，带有视觉冲击力的描写用词", "白皙/莹白", "", ["descriptor"])
add_term("body", "白皙", "形容皮肤白净细腻，偏静态描写", "雪白/白嫩", "", ["descriptor"])
add_term("body", "丰满", "形容身体（尤其胸部/臀部）充实饱满", "丰腴/硕大", "")
add_term("body", "丰腴", "形容体态丰满圆润，偏文学化", "丰满/雍容", "")
add_term("body", "饱满", "形容身体部位（胸/臀/唇等）充实鼓胀", "丰满/浑圆", "")
add_term("body", "硕大", "形容尺寸异常大，强调超出常规", "巨大/粗壮", "")
add_term("body", "粗大", "形容圆柱形物体（阴茎/手指等）直径大", "粗壮/厚实", "")
add_term("body", "纤细", "形容身体线条细窄，偏柔美", "苗条/纤瘦", "")
add_term("body", "修长", "形容肢体（腿/腰/手指）长而匀称", "细长/匀称", "")
add_term("body", "娇嫩", "形容皮肤/身体柔软细嫩，带脆弱感", "柔嫩/稚嫩", "")
add_term("body", "粉嫩", "形容皮肤或身体部位呈粉色且细嫩", "粉白/嫩红", "")
add_term("body", "爆乳", "形容胸部极大且突出，口语化", "巨乳/豪乳", "")
add_term("body", "美腿", "形容腿部线条优美，视觉焦点", "长腿/美脚", "")
add_term("body", "大腿", "腿部上段，性描写中常见接触/夹持部位", "腿根/股部", "")
add_term("body", "舌头", "口腔内器官，口交/舔舐的核心动作对象", "舌尖/舌面", "")
add_term("body", "胯下", "两腿之间/腰部下方区域，性描写空间定位词", "裆部/胯间", "")
add_term("body", "小腹", "腹部下方/脐下区域，性描写中常见刺激点", "小肚/下腹", "")
add_term("body", "胸前", "胸部前方区域，性描写空间定位词", "胸口/乳前", "")
add_term("body", "肌肤", "皮肤与肌肉的合称，偏文学化", "皮肤/肌理", "")
add_term("body", "肉体", "身体整体，强调物质性/感官性", "肉身/胴体", "")
add_term("body", "下体", "下半身/生殖器区域，偏隐晦", "下身/私处", "")
add_term("body", "俏脸", "面容，带俏皮/可爱色彩", "脸庞/小脸", "")
add_term("body", "眼神", "目光所传达的情绪/态度", "目光/眼波", "")
add_term("body", "表情", "面部肌肉变化所传达的情绪", "脸色/神态", "")
add_term("body", "双手", "两只手，性描写中常见抓握/抚摸动作", "双臂/手掌", "")

# ── descriptor 补充 ──
add_term("descriptor", "淫乱", "形容行为/状态极度放浪不知收敛", "淫荡/放荡", "", ["personality"])
add_term("descriptor", "强烈", "形容程度/强度极高", "猛烈/炽烈", "")
add_term("descriptor", "无比", "形容程度达到极致，无比较对象", "极其/万分", "")
add_term("descriptor", "彻底", "形容完成度/程度达到尽头", "完全/尽数", "")
add_term("descriptor", "漂亮", "形容外貌好看，通用正面评价", "美丽/俊美", "")
add_term("descriptor", "可爱", "形容外貌/行为讨人喜欢", "萌/招人喜欢", "", ["personality"])
add_term("descriptor", "腥臭", "形容体液/分泌物的气味，偏负面感官", "膻味/骚味", "")
add_term("descriptor", "滚烫", "形容温度极高，偏触觉", "灼热/烫手", "")

# ── identity 补充 ──
add_term("identity", "美少女", "年轻美丽的女性角色统称，视觉+年龄双重标签", "美 girl/丽人", "", ["descriptor"])
add_term("identity", "美人", "容貌出众者统称，不限性别/年龄", "佳人/美女", "", ["descriptor"])
add_term("identity", "美妈", "对年轻貌美母亲的称呼，带调侃/占有意味", "辣妈/少妇", "", ["descriptor"])
add_term("identity", "黑丝", "黑色连裤袜/丝袜，服装+视觉标签", "黑袜/黑长筒", "", ["descriptor"])
add_term("identity", "白丝", "白色连裤袜/丝袜，服装+视觉标签", "白袜/白长筒", "", ["descriptor"])
add_term("identity", "丝袜", "连裤袜/长筒袜统称，服装标签", "长筒袜/连裤袜", "", ["descriptor"])
add_term("identity", "女孩", "年轻女性统称，年龄标签", "少女/小姑娘", "", ["descriptor"])
add_term("identity", "少年", "年轻男性/中性角色统称，年龄标签", "青年/小子", "")
add_term("identity", "中年", "年龄阶段标签（约35-55岁），常与体型搭配", "不惑之年/壮年", "")
add_term("identity", "母猪", "对女性的物化/贬称，强调繁殖属性", "母狗/畜生", "", ["relationship"])
add_term("identity", "老子", "男性自称/对男性长辈的称呼，带霸气", "爹/老爸", "", ["relationship"])
add_term("identity", "大人", "对尊长/上位者的敬称，权力关系标记", "先生/老爷", "", ["relationship"])
add_term("identity", "小姐", "对年轻女性的尊称/职业称呼，带距离感", "千金/姑娘", "", ["relationship"])
add_term("identity", "儿子", "男性后代，血缘关系标记", "孩子/仔", "", ["relationship"])
add_term("identity", "美少", "年轻美丽的男性/中性角色，视觉+年龄标签", "美 boy/丽人", "", ["descriptor"])

# ── action 补充 ──
add_term("action", "摩擦", "两个表面相互滑动产生刺激，性描写核心动作", "蹭/磨", "")
add_term("action", "玩弄", "以支配姿态把玩/操控对方身体或感官", "摆弄/把玩", "")
add_term("action", "侵犯", "以强势进入/占据对方身体空间，性描写核心动作", "入侵/强占", "", ["genre"])
add_term("action", "开口", "开始说话/发声的动作起点", "出声/说话", "")
add_term("action", "呼吸", "气息进出，性描写中节奏/状态标记", "喘气/吐纳", "")

# ── state 补充 ──
add_term("state", "兴奋", "神经高度活跃/欲望高涨的状态", "亢奋/激动", "", ["emotion"])
add_term("state", "羞耻", "因暴露/被看而产生的难为情状态", "尴尬/不好意思", "", ["emotion"])
add_term("state", "疯狂", "行为/情绪失控般的极端状态", "狂热/癫狂", "")
add_term("state", "主动", "自发发起而非被动接受的行为模式", "积极/抢先", "", ["personality"])
add_term("state", "剧烈", "动作/反应的幅度/强度极大", "猛烈/汹涌", "")

# ── emotion 补充 ──
add_term("emotion", "想到", "心理活动/联想的触发词", "想起/忆及", "")
add_term("emotion", "觉得", "主观感受/判断的表达", "感到/认为", "")
add_term("emotion", "感到", "感官/情绪接收的表达", "感觉到/察觉", "")
add_term("emotion", "心中", "内心/胸口的空间隐喻，情绪定位", "心底/胸怀", "")

# ── genre 补充 ──
add_term("genre", "偷情", "以秘密进行性关系为核心张力的题材", "偷欢/私通", "", ["action"])
add_term("genre", "强取", "以力量压制对方意志的题材", "强占/夺", "", ["action"])
add_term("genre", "调伏", "以耐心/技巧驯化野性/不羁对象的题材", "驯服/感化", "")
add_term("genre", "共浴", "以共同沐浴为场景的题材，强调'水+裸'的感官", "同浴/共沐", "")
add_term("genre", "换装", "以更换服装/身份为情节驱动的题材", "变装/易容", "")
add_term("genre", "双修", "以性行为作为修炼/提升手段的题材", "采补/合气", "")

# ── 写文件 ──
out_path = os.path.join(base, "nsfw-lexicon-v6.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(d5, f, ensure_ascii=False, indent=2)

# ── 统计 ──
total_terms = 0
for cat_name, cat in d5.items():
    if isinstance(cat, dict) and "terms" in cat:
        n = len(cat["terms"])
        total_terms += n
        cross_count = sum(1 for t in cat["terms"].values() if "cross_ref" in t)
        print(f"[{cat_name}] {n} terms ({cross_count} cross-ref)")

print(f"\nTotal: {total_terms} terms")
print(f"Written to: {out_path}")
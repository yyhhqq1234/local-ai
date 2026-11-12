import json, os, re
from collections import Counter

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"

# 1) Show what's in relationship + descriptor categories of v4
d = json.load(open(os.path.join(base, "nsfw-lexicon-v4.json"), encoding="utf-8"))
print("=== relationship ===")
for k in d.get("relationship", {}).get("terms", {}):
    print(f"  {k}")
print("\n=== descriptor ===")
for k in d.get("descriptor", {}).get("terms", {}):
    print(f"  {k}")

# 2) Scan raw nsfw.jsonl for identity/personality/genre terms
# Focus on patterns like: 她是XX / 他是XX / 作为XX / XX的身份 / XX属性 etc.
identity_patterns = [
    # 身份词：职业/角色
    r'(?:她|他|其)[^，。！？\n]{0,4}(?:是|为|叫|被称为|身份是|的职业是)',
    # 属性词
    r'(?:属于|具有|带着|有着)\s*[^，。！？\n]{0,6}(?:属性|气质|性格|身份|身份)',
    # 直接的身份列举
    r'(?:作为|以)(?:一?个)?[^，。！？\n]{1,8}(?:的?(?:身份|名义|资格))',
]

# 更直接的方法：从文本中找高频的名词短语（2-4字中文），过滤掉已知身体/动作词
# 先收集所有消息文本
all_texts = []
with open(os.path.join(base, "nsfw.jsonl"), encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        for msg in obj.get("messages", []):
            if msg.get("role") == "assistant":
                all_texts.append(msg["content"])

print(f"\nTotal assistant texts: {len(all_texts)}")

# 用正则提取可能的身份/性格/题材词
# 模式：「XX」+ 身份/属性/性格/气质/类型/系/属性
# 或者直接找高频的2-4字中文词，然后人工筛选

# 方法：统计所有2-6字的中文词频，然后看哪些是身份/性格/题材类的
# 太慢了，改用关键词列表匹配

# 已知的身份/性格/题材类词候选（从领域知识出发）
candidates = {
    # 身份/角色
    "奴隶": 0, "主人": 0, "女仆": 0, "仆人": 0, "主人": 0,
    "萝莉": 0, "御姐": 0, "姐姐": 0, "妹妹": 0, "学姐": 0, "学妹": 0,
    "老师": 0, "学生": 0, "上司": 0, "下属": 0, "老板": 0, "员工": 0,
    "处女": 0, "人妻": 0, "寡妇": 0, "少妇": 0, "熟女": 0, "美少女": 0,
    "处男": 0, "童贞": 0, "初夜": 0,
    "青梅": 0, "竹马": 0, "青梅竹马": 0,
    "继母": 0, "继父": 0, "继姐": 0, "继妹": 0, "继兄": 0, "继弟": 0,
    "养母": 0, "养父": 0, "养姐": 0, "养妹": 0,
    "干妈": 0, "干爹": 0, "干姐姐": 0, "干妹妹": 0,
    "前妻": 0, "前夫": 0, "前任": 0,
    "未婚妻": 0, "未婚夫": 0,
    "青梅": 0,
    # 性格/气质
    "傲娇": 0, "病娇": 0, "毒舌": 0, "天然呆": 0, "三无": 0,
    "抖S": 0, "抖M": 0, "抖S": 0, "抖M": 0,
    "好色": 0, "淫荡": 0, "放荡": 0, "骚": 0, "淫": 0,
    "冷艳": 0, "高冷": 0, "温柔": 0, "强势": 0, "霸道": 0,
    "纯情": 0, "内向": 0, "外向": 0, "开朗": 0, "害羞": 0,
    "胆小": 0, "大胆": 0, "胆大": 0,
    "洁癖": 0, "自恋": 0, "自卑": 0, "自负": 0,
    "腹黑": 0, "腹黒": 0,
    # 题材/类型
    "禁欲": 0, "禁欲系": 0, "无节操": 0,
    "痴女": 0, "痴汉": 0,
    "巨乳": 0, "爆乳": 0, "小穴": 0, "巨屌": 0,
    "猫耳": 0, "狐耳": 0, "兔耳": 0, "龙角": 0,
    "兽耳": 0, "兽耳娘": 0,
    "精灵": 0, "魔族": 0, "龙族": 0, "天使": 0, "恶魔": 0,
    "吸血鬼": 0, "不死": 0, "不死族": 0,
    "机械": 0, "机器人": 0, "人偶": 0, "娃娃": 0,
    "触手": 0, "史莱姆": 0, "触手怪": 0,
    "魅魔": 0, "魅魔": 0,
    "亚人": 0, "非人": 0, "异种": 0,
    # 场景/题材
    "教室": 0, "办公室": 0, "公司": 0, "学校": 0,
    "泳装": 0, "体操服": 0, "制服": 0, "水手服": 0,
    "和服": 0, "浴衣": 0, "浴袍": 0,
    "婚纱": 0, "礼服": 0, "晚礼服": 0,
    "内衣": 0, "睡衣": 0, "睡裙": 0,
    "护士服": 0, "OL": 0, "OL": 0,
    "秘书": 0, "接待": 0,
    "神社": 0, "寺庙": 0, "道观": 0,
    "教堂": 0, "修道院": 0, "修女": 0,
    "医院": 0, "诊所": 0,
    "监狱": 0, "牢房": 0,
    "战场": 0, "前线": 0,
    "宴会": 0, "舞会": 0, "酒会": 0,
    "派对": 0, "聚会": 0,
    "运动会": 0, "文化祭": 0, "学园祭": 0,
    "毕业典礼": 0, "入学式": 0,
    "婚礼": 0, "葬礼": 0, "丧礼": 0,
    # 特殊设定
    "时间停止": 0, "时间停止": 0,
    "记忆抹消": 0, "记忆修改": 0,
    "契约": 0, "血契": 0, "灵魂契约": 0,
    "诅咒": 0, "祝福": 0,
    "变身": 0, "变化": 0, "变形": 0,
    "双重人格": 0, "第二人格": 0,
    "失忆": 0, "遗忘": 0,
    "重生": 0, "转生": 0,
    "穿越": 0, "异世界": 0,
    "轮回": 0, "转世": 0,
}

# 在文本中搜索这些词
found = {}
for term in candidates:
    count = 0
    for text in all_texts:
        count += text.count(term)
    if count > 0:
        found[term] = count

# Sort by frequency
sorted_found = sorted(found.items(), key=lambda x: -x[1])
out_lines = [f"Found {len(sorted_found)} terms with freq > 0"]
for term, cnt in sorted_found:
    out_lines.append(f"  {term}: {cnt}")

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\identity_scan.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
print(f"Done. {len(sorted_found)} terms found.")

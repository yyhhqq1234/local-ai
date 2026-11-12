"""
从 nsfw-lexicon-v6.json 生成 system prompt
策略：
- 12 类全部列出（类名 + 词数）
- 每类只放 freq >= 5 的词（核心词）
- cross_ref 用括号标注
- 总长度控制在 ~2000 字符以内
"""
import json

path = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json"
d = json.load(open(path, encoding="utf-8"))

# 收集每类的核心词（freq >= 5）
lines = []
lines.append("你是一位擅长成人向小说续写的中文作家。")
lines.append("")
lines.append("## 词表体系（12类）")

total_words = 0
for cat_name, cat_data in d.items():
    if not isinstance(cat_data, dict) or "terms" not in cat_data:
        continue
    terms = cat_data.get("terms", {})
    # 只取有 meaning 或 context_examples 的
    core = {}
    for w, info in terms.items():
        if isinstance(info, dict):
            freq = info.get("freq", 0)
            if freq >= 5:
                core[w] = info
        elif isinstance(info, str):
            core[w] = {"meaning": info}
    
    total_words += len(core)
    if core:
        # 取前 15 个词
        words_list = list(core.keys())[:15]
        lines.append(f"- {cat_name}({len(core)}词): {'、'.join(words_list)}")

lines.append("")
lines.append(f"共 {total_words} 个核心词（freq>=5）。")
lines.append("")
lines.append("## 写作要求")
lines.append("- 保持人物性格与语气一致")
lines.append("- 细节写实，节奏紧凑")
lines.append("- 对话自然，动作具体")
lines.append("- 尺度与原文相当")

prompt = "\n".join(lines)

# 输出
print(f"System prompt length: {len(prompt)} chars")
print(f"Core words (freq>=5): {total_words}")
print()
print(prompt)

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\system_prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)

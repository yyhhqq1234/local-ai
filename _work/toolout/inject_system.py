"""
将 system prompt 注入 nsfw-train-v5.jsonl → nsfw-train-v6.jsonl
每条记录: [system, user, assistant]
"""
import json

src = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-train-v5.jsonl"
dst = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-train-v6.jsonl"
sys_prompt = open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\system_prompt.txt", "r", encoding="utf-8").read().strip()

count = 0
with open(src, "r", encoding="utf-8") as fin, open(dst, "w", encoding="utf-8") as fout:
    for line in fin:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        
        # 插入 system message
        msgs = rec["messages"]
        new_msgs = [{"role": "system", "content": sys_prompt}] + msgs
        rec["messages"] = new_msgs
        
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        count += 1

print(f"Injected {count} records")
print(f"Output: {dst}")

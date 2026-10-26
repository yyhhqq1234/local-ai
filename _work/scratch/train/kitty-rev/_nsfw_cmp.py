# -*- coding: utf-8 -*-
import json, os
def load(p):
    if not os.path.exists(p): return None
    return json.load(open(p, encoding="utf-8"))["results"]
v = load("logs/v5/NSFW-v5.json"); b = load("logs/v5/NSFW-base.json")
print(f"{'':<10}{'v5':>18}{'base':>18}")
def agg(rs, key):
    if rs is None: return "n/a"
    return sum(1 for x in rs if x.get(key))
def avg(rs, key):
    if rs is None: return "n/a"
    xs=[x.get(key,0) for x in rs if "err" not in x]
    return f"{sum(xs)/max(1,len(xs)):.0f}"
rows = [
 ("合格 ok",      agg(v,"ok"),      agg(b,"ok")),
 ("content 正文", agg(v,None) if v is None else sum(1 for x in v if x.get("used")=="content"),
                  agg(b,None) if b is None else sum(1 for x in b if x.get("used")=="content")),
 ("拒答",         agg(v,"refused"), agg(b,"refused")),
 ("平均正文",     avg(v,"content"), avg(b,"content")),
 ("平均 reasoning", avg(v,"reasoning"), avg(b,"reasoning")),
]
for name, x, y in rows:
    print(f"{name:<14}{str(x):>16}{str(y):>18}")
if v and b:
    print("\n逐条：")
    print(f"{'id':<9}{'v5 content':>12}{'base content':>14}{'v5 ok':>7}{'base ok':>9}")
    for x, y in zip(v, b):
        print(f"{x['id']:<9}{x.get('content',0):>12}{y.get('content',0):>14}{str(x.get('ok')):>7}{str(y.get('ok')):>9}")

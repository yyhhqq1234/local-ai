import json
try:
    import jinja2
except ImportError:
    print("jinja2 不可用，跳过本地模拟"); raise SystemExit(0)
p = r"D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev\data\intent3\v6-mix\train.final.jsonl"
row = json.loads(open(p, encoding="utf-8").readline())
# 极简模拟 template 的 |items 用法
tpl = jinja2.Template("{% for m in messages %}{% if m.tool_calls %}{% for tc in m.tool_calls %}<call>{{ tc['function']['name'] }}({% for k,v in tc['function']['arguments']|items %}{{k}}={{v}}{% endfor %})</call>{% endfor %}{% endif %}{% endfor %}")
def run(msgs, tag):
    try:
        out = tpl.render(messages=msgs)
        print(f"  {tag}: OK len={len(out)}  样例={out[:80]}")
        return True
    except Exception as e:
        print(f"  {tag}: {type(e).__name__}: {e}")
        return False
print("原始数据（arguments 是 JSON 字符串）:")
run(row["messages"], "raw")
# 应用转换
def norm(messages):
    out=[]
    for m in messages:
        tcs=m.get("tool_calls")
        if not tcs: out.append(m); continue
        m=dict(m); fixed=[]
        for tc in tcs:
            tc2=dict(tc); fn=dict(tc2.get("function") or {})
            a=fn.get("arguments")
            if isinstance(a,str):
                try: fn["arguments"]=json.loads(a)
                except Exception: fn["arguments"]={}
            tc2["function"]=fn; fixed.append(tc2)
        m["tool_calls"]=fixed; out.append(m)
    return out
print("经 _norm_tool_calls 转换后:")
run(norm(row["messages"]), "norm")

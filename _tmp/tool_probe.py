import json, urllib.request, time, re, collections, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
URL = 'http://127.0.0.1:8080/v1/chat/completions'
MODEL = r'D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf'

def T(name, desc, pars=None, req=None):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": pars or {"type": "object", "properties": {}, "required": []}}}

TOOLS = [
    T("read", "Read a UTF-8 text file by path.", {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}),
    T("ops_bash", "Run a bash command.", {"type": "object", "properties": {"command": {"type": "string"}, "description": {"type": "string"}}, "required": ["command", "description"]}),
    T("kitty_ce", "Kitty A-channel bridge: PING/OPEN/R/W/S_NEW/P_BACK.", {"type": "object", "properties": {"op": {"type": "string"}}, "required": ["op"]}),
    T("kitty_ops", "List kitty OP table.", {"type": "object", "properties": {"filter": {"type": "string"}}, "required": []}),
]

SYS_SHORT = "你是本地工作区执行层。"
SYS_LONG = """你是本地工作区执行层。当前可用工具：
- read(file_path)：读取文本文件
- ops_bash(command, description)：执行 bash 命令
- kitty_ce(op)：Kitty A 通道，op 形如 "PING"、"OPEN|1234"、"R|0x7FF6A0000000|dword"
- kitty_ops(filter)：列出 OP 表
规则：需要真实数据时必须调用对应工具；不要编造工具输出；拿到结果后直接给结论。"""

def call(msgs, tools, max_tokens=800, temp=0.5, thinking=False):
    body = {"model": MODEL, "messages": msgs, "max_tokens": max_tokens, "temperature": temp,
            "stream": False, "chat_template_kwargs": {"enable_thinking": thinking}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=900))
    return d["choices"][0], time.time() - t0, d.get("usage", {})

def nrep(t, n=24):
    if len(t) < n * 2: return 0.0
    c = collections.Counter(t[i:i + n] for i in range(0, len(t) - n, 4))
    return sum(v for v in c.values() if v > 1) / max(1, len(range(0, len(t) - n, 4)))

def show(tag, ch, dt, u):
    m = ch["message"]; txt = m.get("content") or ""; tcs = m.get("tool_calls") or []
    print("=" * 14, tag)
    print("finish=%s tok=%s sec=%.1f rep=%.2f tools=%d textLen=%d %s" % (
        ch.get("finish_reason"), u.get("completion_tokens"), dt, nrep(txt), len(tcs), len(txt),
        [t["function"]["name"] for t in tcs]))
    if txt.strip():
        print("  text:", txt.strip()[:220].replace("\n", " / "))
    return m

# V1 短system + tools
show("V1 短system+4tools", *call([{"role": "system", "content": SYS_SHORT},
                                 {"role": "user", "content": "读取 _tmp/loop_probe.py 的前 5 行。"}], TOOLS))
# V2 长system + tools
show("V2 长system+4tools", *call([{"role": "system", "content": SYS_LONG},
                                 {"role": "user", "content": "读取 _tmp/loop_probe.py 的前 5 行。"}], TOOLS))
# V3 长system + tools + thinking
show("V3 长system+4tools+think", *call([{"role": "system", "content": SYS_LONG},
                                        {"role": "user", "content": "读取 _tmp/loop_probe.py 的前 5 行。"}], TOOLS, thinking=True))
# V4 kitty 任务 + 长system
show("V4 kitty指令", *call([{"role": "system", "content": SYS_LONG},
                            {"role": "user", "content": "先 PING 探活 Kitty 通道，然后列出 OP 表中 S_ 前缀的项。"}], TOOLS))
# V5 合法两轮：先让模型调工具（强制单工具），再回灌
msgs = [{"role": "system", "content": SYS_LONG}, {"role": "user", "content": "读取文件 _tmp/loop_probe.py 的前 5 行，只调 read 一次。"}]
ch, dt, u = call(msgs, TOOLS)
m = show("V5-1 首轮", ch, dt, u)
tcs = m.get("tool_calls") or []
if tcs:
    msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
    for t in tcs:
        msgs.append({"role": "tool", "tool_call_id": t["id"], "content": "import json, urllib.request, time, re, collections, sys, io"})
    show("V5-2 合法回灌", *call(msgs, TOOLS))
else:
    print("V5-2 skipped: 模型首轮未产生 tool_calls")
# V6 错误回灌（合法两轮，kitty 报错）
msgs6 = [{"role": "system", "content": SYS_LONG}, {"role": "user", "content": "打开 pid 1234 并读取 0x7FF6A0000000 的 dword。"}]
ch6, dt6, u6 = call(msgs6, TOOLS)
m6 = show("V6-1 首轮", ch6, dt6, u6)
tcs6 = m6.get("tool_calls") or []
if tcs6:
    msgs6.append({"role": "assistant", "content": m6.get("content") or "", "tool_calls": tcs6})
    for t in tcs6:
        msgs6.append({"role": "tool", "tool_call_id": t["id"], "content": "ERR|NO-TARGET: OPEN 失败，目标进程不存在"})
    show("V6-2 错误回灌", *call(msgs6, TOOLS))
else:
    print("V6-2 skipped: 模型首轮未产生 tool_calls")

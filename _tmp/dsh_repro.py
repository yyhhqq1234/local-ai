import json, urllib.request, time, re, collections, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
URL = 'http://127.0.0.1:8080/v1/chat/completions'
MODEL = r'D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf'

TOOLS = [
    {"type": "function", "function": {"name": "read", "description": "Read a UTF-8 text file by path.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "ops_bash", "description": "Run a bash command.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "description": {"type": "string"}}, "required": ["command", "description"]}}},
    {"type": "function", "function": {"name": "kitty_ce", "description": "Kitty A-channel bridge: PING/OPEN/R/W/S_NEW/P_BACK ops.", "parameters": {"type": "object", "properties": {"op": {"type": "string"}}, "required": ["op"]}}},
    {"type": "function", "function": {"name": "kitty_ops", "description": "List kitty OP table.", "parameters": {"type": "object", "properties": {"filter": {"type": "string"}}, "required": []}}},
]

SYS = """你是本地工作区执行层。可用工具：read / ops_bash / kitty_ce / kitty_ops。
规则：需要信息就调工具，不要猜测；拿到结果后直接给结论，不要重复调用同一工具。"""


def call(msgs, tools=None, max_tokens=1200, temp=0.6, thinking=False):
    body = {"model": MODEL, "messages": msgs, "max_tokens": max_tokens, "temperature": temp,
            "stream": False, "chat_template_kwargs": {"enable_thinking": thinking}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=900))
    ch = d["choices"][0]
    return ch, time.time() - t0, d.get("usage", {})


def ngram_rep(t, n=24):
    if len(t) < n * 2:
        return 0.0
    c = collections.Counter(t[i:i + n] for i in range(0, len(t) - n, 4))
    rep = sum(v for v in c.values() if v > 1)
    tot = max(1, len(range(0, len(t) - n, 4)))
    return rep / tot


def show(tag, ch, dt, usage):
    m = ch["message"]
    txt = m.get("content") or ""
    tcs = m.get("tool_calls") or []
    print("=" * 16, tag)
    print("finish=%s tok=%s sec=%.1f rep=%.2f textLen=%d tools=%d" % (
        ch.get("finish_reason"), usage.get("completion_tokens"), dt, ngram_rep(txt), len(txt), len(tcs)))
    for t in tcs:
        print("  call:", t["function"]["name"], str(t["function"].get("arguments"))[:120])
    if txt.strip():
        print("  text:", txt.strip()[:200].replace("\n", " / "))
    return m


# T1 单轮工具任务
msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": "读取 _tmp/loop_probe.py 的前 5 行。"}]
ch, dt, u = call(msgs, TOOLS)
show("T1 单轮读文件", ch, dt, u)

# T2 工具结果回灌后的第二轮（最容易出现重复调用的地方）
m = ch["message"]
msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": m.get("tool_calls")})
for t in (m.get("tool_calls") or []):
    msgs.append({"role": "tool", "tool_call_id": t["id"], "content": "import json, urllib.request, time, re, collections\n\nURL = 'http://127.0.0.1:8080/v1/chat/completions'"})
ch2, dt2, u2 = call(msgs, TOOLS)
show("T2 结果回灌第二轮", ch2, dt2, u2)

# T3 错误回灌（工具报错 → 看是否反复重试）
msgs3 = [{"role": "system", "content": SYS}, {"role": "user", "content": "打开目标进程 1234 读地址 0x7FF6A0000000 的 dword。"}]
ch3, dt3, u3 = call(msgs3, TOOLS)
m3 = show("T3 首轮kitty", ch3, dt3, u3)
msgs3.append({"role": "assistant", "content": m3.get("content") or "", "tool_calls": m3.get("tool_calls")})
for t in (m3.get("tool_calls") or []):
    msgs3.append({"role": "tool", "tool_call_id": t["id"], "content": "ERR|NO-TARGET: OPEN 失败，目标进程不存在"})
ch4, dt4, u4 = call(msgs3, TOOLS)
show("T4 错误回灌", ch4, dt4, u4)

# T5 NSFW 长创作（带 NSFW 许可 system，最易复读）
SYS5 = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
msgs5 = [{"role": "system", "content": SYS5},
         {"role": "user", "content": "[NSFW] 写一段约2000字的成人向小说，都市职场背景，两名角色，节奏推进，不要总结不要反思。直接正文。"}]
ch5, dt5, u5 = call(msgs5, None, max_tokens=2400, temp=0.8)
m5 = show("T5 NSFW长创作", ch5, dt5, u5)
t = m5.get("content") or ""
if t:
    ss = [s for s in re.split(r'[。！？\n]', t) if len(s) > 12]
    c = collections.Counter(s.strip()[:28] for s in ss)
    print("  高频句:", c.most_common(2))

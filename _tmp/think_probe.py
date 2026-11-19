import json, urllib.request, time, re, collections, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
URL = 'http://127.0.0.1:8080/v1/chat/completions'
MODEL = r'D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf'

def T(name, desc, props=None, req=None):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": req or []}}}

TOOLS = [
    T("read", "Read a UTF-8 text file by path.", {"file_path": {"type": "string"}}, ["file_path"]),
    T("ops_bash", "Run a bash command.", {"command": {"type": "string"}, "description": {"type": "string"}}, ["command", "description"]),
    T("kitty_ce", "Kitty A-channel bridge: PING/OPEN/R/W/S_NEW/P_BACK.", {"op": {"type": "string"}}, ["op"]),
    T("kitty_ops", "List kitty OP table.", {"filter": {"type": "string"}}, []),
]
SYS = """你是本地工作区执行层。可用工具：
- read(file_path)：读取文本文件
- ops_bash(command, description)：执行 bash 命令
- kitty_ce(op)：Kitty A 通道，op 形如 "PING"、"OPEN|1234"、"R|0x7FF6A0000000|dword"
- kitty_ops(filter)：列出 OP 表
规则：需要真实数据时必须调用工具，禁止编造工具输出；拿到结果后直接给结论。"""

def call(msgs, max_tokens=900, temp=0.5, thinking=True):
    body = {"model": MODEL, "messages": msgs, "max_tokens": max_tokens, "temperature": temp,
            "stream": False, "chat_template_kwargs": {"enable_thinking": thinking}, "tools": TOOLS}
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
    print("finish=%s tok=%s sec=%.1f rep=%.2f tools=%d" % (ch.get("finish_reason"), u.get("completion_tokens"), dt, nrep(txt), len(tcs)))
    for t in tcs:
        print("  call:", t["function"]["name"], str(t["function"].get("arguments"))[:160])
    if txt.strip():
        print("  text:", txt.strip()[:240].replace("\n", " / "))
    return m

msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": "读取文件 _tmp/loop_probe.py 的前 5 行。"}]
ch, dt, u = call(msgs)
m = show("W1 单轮read(think)", ch, dt, u)
tcs = m.get("tool_calls") or []
if tcs:
    msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
    for t in tcs:
        msgs.append({"role": "tool", "tool_call_id": t["id"],
                     "content": "1|import json, urllib.request, time, re, collections\n2|\n3|URL = 'http://127.0.0.1:8080/v1/chat/completions'\n4|MODEL = r'...9b.gguf'\n5|\n6|cases = []"})
    ch2, dt2, u2 = call(msgs)
    show("W2 合法回灌", ch2, dt2, u2)
else:
    print("W2 skipped")

msgs3 = [{"role": "system", "content": SYS}, {"role": "user", "content": "打开 pid 1234 并读取 0x7FF6A0000000 的 dword。"}]
ch3, dt3, u3 = call(msgs3)
m3 = show("W3 首轮kitty(think)", ch3, dt3, u3)
tcs3 = m3.get("tool_calls") or []
if tcs3:
    msgs3.append({"role": "assistant", "content": m3.get("content") or "", "tool_calls": tcs3})
    for t in tcs3:
        msgs3.append({"role": "tool", "tool_call_id": t["id"], "content": "ERR|NO-TARGET: OPEN 失败，目标进程不存在"})
    ch4, dt4, u4 = call(msgs3)
    m4 = show("W4 错误回灌", ch4, dt4, u4)
    tcs4 = m4.get("tool_calls") or []
    if tcs4:
        print("  -> 重试次数=1 (再次调用), 名称:", [t["function"]["name"] for t in tcs4])
else:
    print("W4 skipped")

msgs5 = [{"role": "system", "content": "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"},
         {"role": "user", "content": "[NSFW] 写一段约1500字成人向小说，都市职场，节奏推进，直接正文。"}]
ch5, dt5, u5 = call(msgs5, max_tokens=1800, temp=0.8)
m5 = show("W5 NSFW长文(think)", ch5, dt5, u5)
t = m5.get("content") or ""
if t:
    ss = [s for s in re.split(r'[。！？\n]', t) if len(s) > 12]
    c = collections.Counter(s.strip()[:26] for s in ss)
    print("  高频句:", c.most_common(3))

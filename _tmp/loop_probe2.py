import json, urllib.request, time, re, collections, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
URL = 'http://127.0.0.1:8080/v1/chat/completions'
MODEL = r'D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf'


def ngram_rep(t, n=30):
    c = collections.Counter(t[i:i + n] for i in range(0, max(0, len(t) - n), 5))
    rep = sum(v for v in c.values() if v > 1)
    tot = max(1, len(range(0, max(0, len(t) - n), 5)))
    sents = [s for s in re.split(r'[。！？\n]', t) if len(s) > 12]
    sc = collections.Counter(sents)
    top = sc.most_common(1)[0] if sc else ('', 0)
    return rep / tot, top


def run(tag, sysmsg, user, tools=None, max_tokens=2000, temp=0.7):
    msgs = []
    if sysmsg:
        msgs.append({"role": "system", "content": sysmsg})
    msgs.append({"role": "user", "content": user})
    body = {"model": MODEL, "messages": msgs, "max_tokens": max_tokens, "temperature": temp,
            "stream": False, "chat_template_kwargs": {"enable_thinking": False}}
    if tools:
        body["tools"] = tools
    t0 = time.time()
    try:
        req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=900))
    except Exception as e:
        print(tag, "ERR", e)
        return
    ch = d["choices"][0]
    txt = ch["message"]["content"] or ""
    tc = ch["message"].get("tool_calls") or []
    ratio, top = ngram_rep(txt)
    print("=" * 16, tag)
    print("finish=%s chars=%d tok=%s sec=%.1f repNgram=%.2f topSent(x%d)=%s" % (
        ch.get("finish_reason"), len(txt), d.get("usage", {}).get("completion_tokens"),
        time.time() - t0, ratio, top[1], top[0][:60]))
    if tc:
        print("tool_calls=%d: %s" % (len(tc), [t.get("function", {}).get("name") for t in tc]))
    print("--- tail ---")
    print(txt[-260:].replace("\n", " / "))


if __name__ == '__main__':
    run("普通长文", "", "请写一篇约800字的散文，主题是雨夜的旧书店，直接正文，不要解释。", max_tokens=1600)
    run("工具任务-裸", "", "用 ops_bash 列出当前目录下的 JSON 文件，然后告诉我数量。", max_tokens=0)

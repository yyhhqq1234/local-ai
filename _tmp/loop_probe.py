import json, urllib.request, time, re, collections

URL = 'http://127.0.0.1:8080/v1/chat/completions'
MODEL = r'D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf'

cases = [
    {"tag": "nsfw-长续写", "sys": "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。",
     "user": "[NSFW] 请写一段约1200字的成人向小说片段，都市背景，节奏快，不要总结、不要解释，直接正文。"},
    {"tag": "普通长文", "sys": "",
     "user": "请写一篇约800字的散文，主题是雨夜的旧书店，直接正文，不要解释。"},
    {"tag": "工具任务", "sys": "",
     "user": "用 ops_bash 列出当前目录下的 JSON 文件，然后告诉我数量。"},
]


def ngram_rep(t, n=30):
    c = collections.Counter(t[i:i + n] for i in range(0, max(0, len(t) - n), 5))
    rep = sum(v for v in c.values() if v > 1)
    tot = max(1, len(range(0, max(0, len(t) - n), 5)))
    sents = [s for s in re.split(r'[。！？\n]', t) if len(s) > 12]
    sc = collections.Counter(sents)
    top = sc.most_common(1)[0] if sc else ('', 0)
    return rep / tot, top


for cs in cases:
    msgs = [{"role": "system", "content": cs["sys"]}] if cs["sys"] else []
    msgs.append({"role": "user", "content": cs["user"]})
    body = {"model": MODEL, "messages": msgs, "max_tokens": 2000, "temperature": 0.7,
            "stream": False, "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.time()
    try:
        req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=900))
    except Exception as e:
        print(cs["tag"], "ERR", e)
        continue
    ch = d["choices"][0]
    txt = ch["message"]["content"] or ""
    ratio, top = ngram_rep(txt)
    print("=" * 20, cs["tag"])
    print("finish=%s len=%d tok=%s 秒=%.1f 重复ngram占比=%.2f" % (
        ch.get("finish_reason"), len(txt), d.get("usage", {}).get("completion_tokens"), time.time() - t0, ratio))
    print("最高频句(次数=%d): %s" % (top[1], top[0][:80]))
    print("--- 尾部 300 字 ---")
    print(txt[-300:].replace("\n", "⏎"))

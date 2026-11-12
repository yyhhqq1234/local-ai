# p3_cli_probe.py — 0 改动对照：CLI --messages 路径在 GSQ / Q4Q5 上的 system 用例
import json
import os
import subprocess

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer.exe")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
MODELS = {
    "GSQ": os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer"),
    "Q4Q5": os.path.join(ROOT, r"train\lines\9b-oxcoder\models\oxcoder-9b-Q4Q5.ninfer"),
}
CASES = {
    "user": [{"role": "user", "content": "What is 2+2?"}],
    "sys": [{"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2+2?"}],
    "essay": [{"role": "user", "content": "Write a 300-word essay about why local inference matters."}],
}

for cname, msgs in CASES.items():
    path = os.path.join(WORK, "p3-cli-%s.json" % cname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(msgs, f, ensure_ascii=False)

for mname, model in MODELS.items():
    for cname in CASES:
        path = os.path.join(WORK, "p3-cli-%s.json" % cname)
        args = [EXE, model, "--messages", path, "--max-context", "4096", "--greedy",
                "--no-thinking", "--max-new", "24", "--prefill-chunk", "128", "--raw-output"]
        r = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = " ".join(r.stdout.split())[:200]
        err = " ".join(r.stderr.split())[-200:]
        print("[%s/%s] rc=%s out=%r" % (mname, cname, r.returncode, out))
        if r.returncode != 0:
            print("    err=%r" % err)

# p3_seed_sweep.py — 多随机种子训练 + 引擎接受率实测（acceptance 是悬崖 → 用种子扫，取最好的）
import importlib.util
import json
import os
import subprocess
import sys

BASE = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b"
PY = r"D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\python.exe"

spec = importlib.util.spec_from_file_location("ns", os.path.join(BASE, "p3_norm_sweep.py"))
ns = importlib.util.module_from_spec(spec); spec.loader.exec_module(ns)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STEPS = int(os.environ.get("SEED_SWEEP_STEPS", "500"))
SEEDS = [int(x) for x in os.environ.get("SEED_SWEEP_SEEDS", "1,2,3").split(",")]
LOG = os.path.join(BASE, "seed-sweep-log.jsonl")

for seed in SEEDS:
    head = os.path.join(BASE, "mtp-out", "var-seed%d.safetensors" % seed)
    env = dict(os.environ)
    env.update({"MTP_SEED": str(seed), "MTP_OUT": head, "MTP_TARGET_SHIFT": "2", "MTP_ROPE": "partial"})
    r = subprocess.run([PY, os.path.join(BASE, "p3_mtp_train.py"), str(STEPS), "5e-4"],
                       env=env, capture_output=True, text=True, timeout=3600)
    tail = [l for l in (r.stdout or "").splitlines() if "step" in l or "VAL" in l][-2:]
    print("seed %d train: %s" % (seed, " | ".join(tail))); sys.stdout.flush()
    if not os.path.exists(head):
        rec = {"seed": seed, "error": "no head"}; print(json.dumps(rec)); continue
    n = ns.patch_head(head)
    art = os.path.join(ns.OUTDIR, "kittyrev-oxcoder9b-seed%d.ninfer" % seed)
    cv = subprocess.run([PY, "-m", "tools.convert", "--model", ns.DST, "--recipe", "recipe_g1_shipped.py",
                         "--components", "text,vision,mtp",
                         "--resource", "video_preprocessor_config.json=video_preprocessor_config.json",
                         "--resource", "tokenizer_config.json=" + os.path.join(BASE, "tokenizer_config_fixed.json"),
                         "--name", "kittyrev-oxcoder9b-seed%d" % seed, "--out", art],
                        cwd=ns.CONV_CWD, capture_output=True, text=True, timeout=1800)
    if not os.path.exists(art):
        rec = {"seed": seed, "error": "convert", "log": (cv.stderr or "")[-200:]}
        print(json.dumps(rec, ensure_ascii=False)); continue
    m = ns.measure(art)
    rec = {"seed": seed, "steps": STEPS, "patched": n, "train_tail": tail, "measure": m}
    print(json.dumps(rec, ensure_ascii=False)); sys.stdout.flush()
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

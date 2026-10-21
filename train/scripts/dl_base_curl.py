# -*- coding: utf-8 -*-
"""dl_base_curl.py —— 用 curl 直连 hf-mirror 下载基座（绕开 huggingface_hub 的 httpx2 兼容性崩溃）

用法:
  python dl_base_curl.py --repo Qwen/Qwen3.8-27B --dest train/base/Qwen3.8-27B
  python dl_base_curl.py ... --dry-run

特性:
  · 文件清单走 hf-mirror API（curl 取 JSON），逐个文件 `curl -C -` 断点续传
  · 每文件校验大小（与 API 的 size 一致）；不一致重试 3 次
  · 已存在且大小一致的文件直接跳过 → 天然可重入
  · 不用 urllib / httpx，避免本机 Python HTTPS 慢路径与库版本问题
"""
import argparse
import json
import os
import subprocess
import sys
import time

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW = (".json", ".safetensors", ".model", ".jinja", ".txt")
MIRROR = "https://hf-mirror.com"


def curl_json(url, timeout=60):
    r = subprocess.run(["curl", "-sS", "-m", str(timeout), url], capture_output=True, timeout=timeout + 5)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[:200])
    return json.loads(r.stdout.decode("utf-8", "replace"))


def list_files(repo):
    out, cursor = [], ""
    while True:
        url = f"{MIRROR}/api/models/{repo}/tree/main?recursive=true"
        if cursor:
            url += "&cursor=" + cursor
        d = curl_json(url)
        out += [x for x in d if x.get("type") == "file"]
        nxt = None
        # 兼容两种返回形态
        if isinstance(d, dict):
            nxt = d.get("nextCursor")
        if not nxt:
            break
        cursor = nxt
    return [x for x in out if x["path"].endswith(ALLOW)]


def fetch_one(repo, item, dest, retries=3):
    path, size = item["path"], item.get("size") or 0
    target = os.path.join(dest, path.replace("/", os.sep))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.isfile(target) and size and os.path.getsize(target) == size:
        return "skip", size
    url = f"{MIRROR}/{repo}/resolve/main/{path}"
    for i in range(retries):
        r = subprocess.run(["curl", "-L", "-sS", "--retry", "3", "--retry-delay", "2",
                            "-C", "-", "-o", target, url],
                           capture_output=True, timeout=3600)
        got = os.path.getsize(target) if os.path.isfile(target) else 0
        if r.returncode == 0 and (not size or got == size):
            return "ok", got
        print(f"    retry {i+1}/{retries} {path}: rc={r.returncode} got={got}/{size}", flush=True)
        time.sleep(2 * (i + 1))
    return "fail", os.path.getsize(target) if os.path.isfile(target) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="Qwen/Qwen3.8-27B")
    ap.add_argument("--dest", default=os.path.join(TRAIN_ROOT, "base", "Qwen3.8-27B"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    files = list_files(a.repo)
    total = sum(x.get("size") or 0 for x in files)
    print(f"[list] {a.repo}: {len(files)} files, {total/2**30:.2f} GiB → {a.dest}", flush=True)
    if a.dry_run:
        for x in sorted(files, key=lambda y: -(y.get("size") or 0))[:8]:
            print(f"   {(x.get('size') or 0)/2**20:9.1f} MiB  {x['path']}")
        return 0

    os.makedirs(a.dest, exist_ok=True)
    ok = skip = fail = 0
    done_bytes = 0
    t0 = time.time()
    for n, item in enumerate(sorted(files, key=lambda y: -(y.get("size") or 0)), 1):
        st, got = fetch_one(a.repo, item, a.dest)
        done_bytes += got
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        el = (time.time() - t0) / 60
        rate = done_bytes / 2 ** 20 / max(1e-6, time.time() - t0)
        print(f"[{n}/{len(files)}] {st:4s} {item['path']}  {got/2**20:.0f}MiB  "
              f"累计={done_bytes/2**30:.2f}GiB  {rate:.1f}MiB/s  {el:.1f}min", flush=True)

    print(f"[done] ok={ok} skip={skip} fail={fail} bytes={done_bytes/2**30:.2f}GiB "
          f"elapsed={(time.time()-t0)/60:.1f}min", flush=True)

    cfg = os.path.join(a.dest, "config.json")
    if os.path.isfile(cfg):
        with open(cfg, "r", encoding="utf-8") as f:
            c = json.load(f)
        arch = c.get("architectures")
        print(f"[config] model_type={c.get('model_type')} architectures={arch}", flush=True)
        print("[VERDICT]", "PASS" if arch and any("Qwen3_5" in x for x in arch) else "CHECK", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

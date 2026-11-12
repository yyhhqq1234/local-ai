#!/usr/bin/env python
"""fetch_base.py —— 拉取基座权重到 train\\base\\（全部走 hf-mirror，落在根目录内）

用法:
  python fetch_base.py --size 8b              # 8B 级，快速验证链路（≈16 GB）
  python fetch_base.py --size 27b             # Qwen3.8-27B（≈54 GB）
  python fetch_base.py --repo Qwen/Qwen3.8-27B --local qwen38-27b
  python fetch_base.py --size 27b --dry-run   # 只列文件与体积，不下载
"""
import argparse
import os
import sys

# 训练根 = 本脚本上一级的上一级
TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.join(TRAIN_ROOT, "hf"))

REPOS = {
    # size 别名 -> (repo_id, 本地目录名, 说明)
    "8b":  ("Qwen/Qwen3-8B",  "Qwen3-8B",  "纯文本 8B，链路验证用；架构与 27B 不同，但训练脚本通用"),
    "27b": ("Qwen/Qwen3.8-27B", "Qwen3.8-27B", "部署模型同款：64 层 / H5120 / 48 linear + 16 full / 原生 VL + MTP"),
}
ALLOW = ["*.json", "*.safetensors", "*.model", "*.jinja", "*.txt", "*.py"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", choices=list(REPOS), default="8b")
    ap.add_argument("--repo", default=None, help="直接指定 repo_id（覆盖 --size）")
    ap.add_argument("--local", default=None, help="base\\ 下的子目录名（默认取别名）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-workers", type=int, default=4)
    args = ap.parse_args()

    if args.repo:
        repo_id, local_name, note = args.repo, (args.local or args.repo.split("/")[-1]), "自定义"
    else:
        repo_id, local_name, note = REPOS[args.size]

    dest = os.path.join(TRAIN_ROOT, "base", args.local or local_name)
    print(f"[repo ] {repo_id}")
    print(f"[note ] {note}")
    print(f"[dest ] {dest}")
    print(f"[mirror] HF_ENDPOINT={os.environ['HF_ENDPOINT']}  HF_HOME={os.environ['HF_HOME']}")

    from huggingface_hub import HfApi, snapshot_download

    api = HfApi()
    # 先探 config，确认能读到
    try:
        info = api.model_info(repo_id, files_metadata=True)
    except Exception as e:
        print(f"[FATAL] 无法访问 {repo_id}: {e}")
        print("        检查 HF_ENDPOINT 是否为 https://hf-mirror.com")
        sys.exit(1)

    total = 0
    picked = []
    for s in info.siblings:
        name = s.rfilename
        if not any(name.endswith(a.lstrip("*")) for a in ALLOW):
            continue
        sz = getattr(s, "size", None) or 0
        total += sz
        picked.append((name, sz))
    print(f"[files] {len(picked)} 个，合计 {total/2**30:.2f} GiB")
    for n, sz in picked[:12]:
        print(f"   {sz/2**20:9.1f} MiB  {n}")
    if len(picked) > 12:
        print(f"   ... 还有 {len(picked)-12} 个")

    if args.dry_run:
        print("[dry-run] 未下载")
        return

    free_gb = None
    try:
        import shutil
        free_gb = shutil.disk_usage(TRAIN_ROOT).free / 2**30
        print(f"[disk  ] 剩余 {free_gb:.1f} GiB")
        if free_gb < total / 2**30 * 1.2:
            print("[WARN] 剩余空间不足以容纳权重 + 20% 余量，建议先清理")
    except Exception:
        pass

    os.makedirs(dest, exist_ok=True)
    path = snapshot_download(
        repo_id=repo_id,
        local_dir=dest,
        allow_patterns=ALLOW,
        max_workers=args.max_workers,
    )
    print(f"[done  ] {path}")

    # 校验：能否被 transformers 识别
    print("[check ] AutoConfig ...")
    from transformers import AutoConfig
    cfg = AutoConfig.from_pretrained(dest, trust_remote_code=True)
    arch = getattr(cfg, "architectures", None)
    print(f"   class      = {type(cfg).__name__}")
    print(f"   architectures = {arch}")
    print(f"   model_type = {getattr(cfg, 'model_type', None)}")
    if arch and any("Qwen3_5" in a for a in arch):
        print("   [OK] transformers 已识别 Qwen3_5* 实现类（版本 >= 5.8）")
    else:
        print("   [WARN] 未识别到 Qwen3_5*，若基座是 27B 请升 transformers 到 >=5.8")


if __name__ == "__main__":
    main()

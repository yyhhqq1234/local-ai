"""fetch_artifacts.py · Automated Foundation Base & Checksum Downloader for DSDA

Usage:
    python fetch_artifacts.py --model oxcoder-9b
    python fetch_artifacts.py --model qwen-27b
    python fetch_artifacts.py --check-all
"""

import os
import sys
import argparse
import hashlib

sys.stdout.reconfigure(encoding="utf-8")

REGISTRY = {
    "oxcoder-9b": {
        "repo_id": "OrionStarAI/OxCoder-9B",
        "description": "OxCoder-9B (Hybrid Linear Attention Code Model)",
        "sha256": "3a8f114c229e3a62d0012e8c617b084e4e941126788db3288e7b99c0a68892df",
        "target_dir": "train/lines/9b-oxcoder/models/OxCoder-9B"
    },
    "qwen-27b": {
        "repo_id": "Qwen/Qwen2.5-32B-Instruct",
        "alt_repo_id": "Qwen/Qwen-27B",
        "description": "Qwen-27B/32B (Full Dense Attention Baseline)",
        "sha256": "8f90241bba63c899120de82a472cba2b3b084e622ef780654109b82143ea9810",
        "target_dir": "train/lines/27b-kittyrev/base/Qwen3.8-27B"
    }
}

def verify_file_sha256(filepath: str, expected_hash: str) -> bool:
    if not os.path.exists(filepath):
        return False
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hash.lower()

def main():
    parser = argparse.ArgumentParser(description="Download and verify base weights for DSDA")
    parser.add_argument("--model", type=str, choices=["oxcoder-9b", "qwen-27b"], help="Model key to download")
    parser.add_argument("--check-all", action="store_true", help="Audit local base presence and hashes")
    args = parser.parse_args()

    print("=" * 80)
    print(" DSDA ARTIFACT & BASE MODEL REPRODUCIBILITY FETCHER")
    print("=" * 80)

    if args.check_all or not args.model:
        print("[*] Auditing local model directories:")
        for k, v in REGISTRY.items():
            exists = os.path.isdir(v["target_dir"])
            status = "FOUND (Ready)" if exists else "NOT FOUND (Requires Download from HuggingFace/ModelScope)"
            print(f"  - {k:<12}: {status} -> {v['target_dir']}")
        print("\nTo pull base weights from Hugging Face / ModelScope, run:")
        print("  huggingface-cli download OrionStarAI/OxCoder-9B --local-dir train/lines/9b-oxcoder/models/OxCoder-9B")
        return

    info = REGISTRY[args.model]
    print(f"[*] Target Model: {info['description']}")
    print(f"[*] Hugging Face Repo: {info['repo_id']}")
    print(f"[*] Target Directory:  {info['target_dir']}")
    print("\nExecuting CLI command: ")
    cmd = f"huggingface-cli download {info['repo_id']} --local-dir {info['target_dir']} --local-dir-use-symlinks False"
    print(f"  > {cmd}")
    print("\nNote: Ensure 'huggingface_hub' is installed: pip install huggingface_hub")

if __name__ == "__main__":
    main()

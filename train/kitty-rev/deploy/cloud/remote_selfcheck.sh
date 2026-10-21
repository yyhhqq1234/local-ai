#!/usr/bin/env bash
# remote_selfcheck.sh -- offline self-check for serve_4bit_base.py + eval_both.sh
# Runs on the AutoDL box. Loads NO model, allocates NO VRAM.
set -u
cd /root/autodl-tmp/kitty-rev/scripts || exit 1
PY=/root/miniconda3/bin/python

echo "=== 1) ast.parse (no import, no VRAM) ==="
$PY - <<'PY'
import ast
src = open('/root/autodl-tmp/kitty-rev/scripts/serve_4bit_base.py', encoding='utf-8').read()
tree = ast.parse(src)
funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
args = [a.args[0].value for a in ast.walk(tree)
        if isinstance(a, ast.Call) and getattr(a.func, 'attr', '') == 'add_argument'
        and a.args and isinstance(a.args[0], ast.Constant)]
print(f"AST_OK bytes={len(src.encode())} lines={src.count(chr(10)) + 1} funcs={len(funcs)}")
print(f"args={args}")
PY

echo "=== 2) --help (argparse only) ==="
$PY serve_4bit_base.py --help

echo "=== 3) guard: missing model dir must exit 2, no VRAM ==="
$PY serve_4bit_base.py --model /nonexistent-xyz --port 18000; echo "rc=$?"

echo "=== 4) bash -n eval_both.sh ==="
bash -n eval_both.sh && echo BASH_SYNTAX_OK

echo "=== 5) checksums ==="
md5sum serve_4bit_base.py eval_both.sh
ls -l serve_4bit_base.py eval_both.sh

echo "=== 6) gpu / training state (must be read-only) ==="
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
echo "compute_apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)"
pgrep -af train_kitty.py | grep python | head -2 || echo "train_kitty: none"
echo "SELFCHECK_DONE"

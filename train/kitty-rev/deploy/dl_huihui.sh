#!/usr/bin/env bash
# dl_huihui.sh —— curl 直连 hf-mirror 下载 Huihui-Qwen3.8-27B-abliterated
# 绕开 huggingface_hub（本机 httpx2 与 hf_hub 不兼容：process() takes no keyword arguments）
set -uo pipefail
REPO="${REPO:-huihui-ai/Huihui-Qwen3.8-27B-abliterated}"
DEST="${DEST:-/root/autodl-tmp/kitty-rev/base/Huihui}"
BASE="https://hf-mirror.com/$REPO/resolve/main"
cd "$DEST" || exit 1

FILES=".gitattributes
LICENSE
README.md
chat_template.jinja
config.json
crc32.txt
generation_config.json
merges.txt
model.safetensors.index.json
preprocessor_config.json
tokenizer.json
tokenizer_config.json
video_preprocessor_config.json
vocab.json
model-00001-of-00018.safetensors
model-00002-of-00018.safetensors
model-00003-of-00018.safetensors
model-00004-of-00018.safetensors
model-00005-of-00018.safetensors
model-00006-of-00018.safetensors
model-00007-of-00018.safetensors
model-00008-of-00018.safetensors
model-00009-of-00018.safetensors
model-00010-of-00018.safetensors
model-00011-of-00018.safetensors
model-00012-of-00018.safetensors
model-00013-of-00018.safetensors
model-00014-of-00018.safetensors
model-00015-of-00018.safetensors
model-00016-of-00018.safetensors
model-00017-of-00018.safetensors
model-00018-of-00018.safetensors"

total=0; ok=0; fail=0
for f in $FILES; do
  total=$((total+1))
  if [ -f "$f" ]; then
    echo "[skip] $f ($(stat -c%s "$f") B)"
    ok=$((ok+1))
    continue
  fi
  printf '[%02d] %-40s ' "$total" "$f"
  if curl -sSL -C - --retry 5 --retry-delay 3 --connect-timeout 20 \
       -o "$f" "$BASE/$f"; then
    sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
    echo "OK $sz B"
    ok=$((ok+1))
  else
    echo "FAIL"
    rm -f "$f"
    fail=$((fail+1))
  fi
done

echo
echo "===== 结果: $ok/$total OK, $fail FAIL ====="
du -sh "$DEST"
ls -1 *.safetensors 2>/dev/null | wc -l | xargs echo "safetensors:"

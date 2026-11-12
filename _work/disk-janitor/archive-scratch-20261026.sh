#!/usr/bin/env bash
# 1) 删临时产物/脚手架  2) 把一次性诊断脚本按原路径归档到 _work/scratch/
set -u
cd /d/BaiduNetdiskDownload/Local-AI || exit 1
SC=_work/scratch
IDX=$SC/INDEX.md
mkdir -p "$SC"

echo "## 1 删除临时产物（无归档价值）"
tmp_del=(
  "train/lines/27b-kittyrev/kitty-rev/n"                                   # 7 字节误落文件
  "train/lines/27b-kittyrev/kitty-rev/deploy/_iq2s_obj.json"               # 286K 一次性 inspect 转储
  "train/lines/27b-kittyrev/kitty-rev/deploy/_iq2s_inspect.json"           # 5K 同上
  "train/lines/27b-kittyrev/kitty-rev/data/_tmp_2q.jsonl"                  # 临时拼样
)
for p in "${tmp_del[@]}"; do
  [ -e "$p" ] && { sz=$(stat -c '%s' "$p"); rm -rf "$p"; echo "DEL  ${sz}B  $p"; }
done

# 本轮脚手架（用完即删，日志保留）
for p in _work/disk-janitor/purge-safe-20261026.sh _work/disk-janitor/stage-selective-20261026.sh; do
  [ -e "$p" ] && { rm -f "$p"; echo "DEL  script  $p"; }
done

# model-id-check 里的 tokenizer 副本（可从基底重取，16M）
if [ -d _work/model-id-check/hf ]; then
  sz=$(du -sm _work/model-id-check/hf | cut -f1); rm -rf _work/model-id-check/hf
  echo "DEL  ${sz}MB  _work/model-id-check/hf (tokenizer 副本)"
fi

echo
echo "## 2 归档诊断脚本 -> $SC"
: > /tmp/_arch_list
# 取所有未跟踪的脚本文件（py/ps1/sh）
git -c core.quotepath=false ls-files -o --exclude-standard | grep -E '\.(py|ps1|sh)$' > /tmp/_arch_scripts
# 取其余非脚本小件（保留来源树）
git -c core.quotepath=false ls-files -o --exclude-standard | grep -vE '\.(py|ps1|sh)$' | grep -vE '^_work/scratch/' > /tmp/_arch_other

{ cat /tmp/_arch_scripts; cat /tmp/_arch_other; } | sort -u > /tmp/_arch_list

while IFS= read -r p; do
  [ -e "$p" ] || continue
  dst="$SC/$p"
  mkdir -p "$(dirname "$dst")"
  # 冲突保护：同名已存在则加 .dup
  [ -e "$dst" ] && dst="${dst}.dup"
  mv "$p" "$dst" && echo "ARCH $p -> $dst"
done < /tmp/_arch_list

echo
echo "## 3 生成 INDEX.md"
{
  echo "# _work/scratch · 一次性诊断脚本归档"
  echo
  echo "归档时间：$(date '+%F %T')　来源 Git commit：$(git rev-parse --short HEAD)"
  echo "说明：原路径树完整保留（\`_work/scratch/<原相对路径>\`），仅作溯源用，**不是**生产管线代码。"
  echo "凭据：全部经环境变量传入（如 \`ADL_PHONE\`/\`ADL_PW\`），归档内无硬编码密钥。"
  echo
  echo "| 文件 | 字节 | 原位置 |"
  echo "|---|---:|---|"
  ( cd "$SC" && find . -type f -not -name 'INDEX.md' -printf '%P\n' | sort ) | while IFS= read -r rel; do
    sz=$(stat -c '%s' "$SC/$rel")
    echo "| \`$rel\` | $sz | \`${rel}\` |"
  done
} > "$IDX"

echo "归档文件数: $(find "$SC" -type f -not -name INDEX.md | wc -l)"
echo "归档体积:   $(du -sh "$SC" | cut -f1)"
echo "最大单文件: $(find "$SC" -type f -printf '%s %p\n' | sort -rn | head -1)"

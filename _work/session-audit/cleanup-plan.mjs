// 清理清单：识别过时内容并落盘哈希台账（删除前）
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const ROOT = 'D:/BaiduNetdiskDownload/Local-AI/train/data/nsfw';
const sha256 = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const walk = (d, out = []) => {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p, out); else out.push(p);
  }
  return out;
};

// 判定：目录级过时（备份/历史版本），活跃数据一律不动
const STALE_DIRS = ['_superseded', '_re-strip-backup-20261027115222'];
const reason = (p) => {
  const rel = path.relative(ROOT, p).replace(/\\/g, '/');
  if (rel.startsWith('_re-strip-backup-')) return '剔 re 之前的全量原件备份（含 4596 条逆向样本），当前训练集已不含 re';
  if (rel.includes('/structure-') && rel.includes('/pre-v9/')) return 'v9 升级前的 lexicon v8';
  if (rel.includes('/structure-') && rel.includes('/pre-variant-merge/')) return '变体归并前的 lexicon v7';
  if (rel.includes('/structure-') && /nsfw-lexicon-v6/.test(rel)) return 'v6 词表，已被 v9 取代';
  if (rel.includes('/structure-') && /nsfw-glossary-(v2|v3-new|r4)/.test(rel)) return 'glossary 三表原件，已合并为 merged(283)';
  if (rel.includes('/structure-') && /(final-nsfw|mix-nsfw|nsfw-v3)\.jsonl/.test(rel)) return '三份同源训练集，已拆分为 train-*.jsonl(13668)';
  if (/(final-joint|mix-joint)\.jsonl/.test(rel)) return 'joint 版同源副本（剔 re 前）';
  if (/nsfw\.jsonl$/.test(rel)) return '无版本号基础语料，与 nsfw-v3 字节相同';
  if (/nsfw-coverage\.json$/.test(rel)) return '12:29 早期覆盖报告，已被后续覆盖统计取代';
  if (/nsfw-glossary\.jsonl$/.test(rel)) return 'glossary v1 旧格式（252 行无 id），已被 v2 取代';
  return '历史版本';
};

const rows = [];
let totalBytes = 0;
for (const d of STALE_DIRS) {
  const abs = path.join(ROOT, d);
  if (!fs.existsSync(abs)) continue;
  for (const p of walk(abs)) {
    const st = fs.statSync(p);
    totalBytes += st.size;
    rows.push({
      path: path.relative(ROOT, p).replace(/\\/g, '/'),
      bytes: st.size,
      sha256: sha256(p),
      reason: reason(p),
    });
  }
}
rows.sort((a, b) => b.bytes - a.bytes);

const md = [];
md.push('# nsfw/ 清理台账（删除前记录）');
md.push('');
md.push(`- 生成时间: ${new Date().toISOString()}`);
md.push(`- 删除范围: ${STALE_DIRS.join(' / ')}（仅历史版本与备份，活跃数据未动）`);
md.push(`- 文件数: ${rows.length}，合计 ${(totalBytes / 1024 / 1024).toFixed(1)} MB`);
md.push('');
md.push('| # | 路径 | MB | sha256(前16) | 判定理由 |');
md.push('|---|---|---|---|---|');
rows.forEach((r, i) => md.push(`| ${i + 1} | ${r.path} | ${(r.bytes / 1048576).toFixed(1)} | ${r.sha256.slice(0, 16)} | ${r.reason} |`));
md.push('');
md.push('## 保留（未动）');
md.push('```');
md.push('train-{cont,scene,multi,style,expand}.jsonl');
md.push('nsfw-glossary-merged.jsonl');
md.push('nsfw-lexicon-v9.json');
md.push('nsfw-v3-coverage.json  → 将更新为 nsfw-coverage.json');
md.push('nsfw-index/  nsfw-triage/  → 将更新元数据');
md.push('MANIFEST.json  → 将重写');
md.push('```');
fs.writeFileSync(path.join(ROOT, 'CLEANUP-REPORT.md'), md.join('\n') + '\n', 'utf8');

console.log(JSON.stringify({
  files: rows.length,
  totalMB: +(totalBytes / 1048576).toFixed(1),
  top: rows.slice(0, 6).map(r => `${r.path} ${(r.bytes / 1048576).toFixed(1)}MB`),
  report: 'CLEANUP-REPORT.md',
}, null, 2));

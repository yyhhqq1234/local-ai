// kitty-reverse 清理与保留件更新：台账 → 删除已吸收/非核心件 → 更新保留件与 MANIFEST
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const R = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/data/kitty-reverse';
const P = (f) => path.join(R, f);
const sha256 = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const lines = (f) => fs.readFileSync(P(f), 'utf8').split('\n').filter(Boolean);
const NOW = new Date().toISOString();

// ── 待删清单（附理由）──
const DROP = [
  ['final-re.jsonl', '内容已全部进入 train-kitty-core.jsonl（1608/1608 覆盖）'],
  ['final-re-final.jsonl', '同上（1796 新增已并入，46 重复）'],
  ['final-re-refined.jsonl', '同上（1269 新增已并入，546 重复）'],
  ['final-re-dedup.jsonl', '同上（645 新增已并入，1848 重复）'],
  ['mix-re.jsonl', '同上（284 新增已并入，406 重复）'],
  ['re-qc/gold.jsonl', '413 唯一对 100% 已在 core（经 final-re），此行文件为重复档'],
  ['kitty-contracts/sft-kitty.jsonl', '391 唯一对 100% 已在 core，契约样本已吸收'],
  ['re-iter/iter-all.jsonl', '804 条 100% 已在 core'],
  ['re-qc/reject.jsonl', '评分 reject 档 20427 行，训练不使用，占 161MB'],
];
for (const f of fs.readdirSync(P('re-iter'))) {
  if (/^(r\d[\d-]*|batch-r\d+).*\.jsonl$/.test(f)) DROP.push([`re-iter/${f}`, '批次分片，100% 已汇总进 iter-all → core']);
}

const rows = [];
for (const [rel, reason] of DROP) {
  const p = P(rel);
  if (!fs.existsSync(p)) { rows.push({ rel, reason, missing: true }); continue; }
  rows.push({ rel, bytes: fs.statSync(p).size, sha256: sha256(p), rows: rel.endsWith('.jsonl') ? lines(rel).length : undefined, reason });
}
const removedBytes = rows.reduce((a, r) => a + (r.bytes || 0), 0);

// ── 台账 ──
const md = [];
md.push('# kitty-reverse 清理台账（删除前记录）');
md.push('');
md.push(`- 生成时间: ${NOW}`);
md.push(`- 删除 ${rows.length} 个文件，合计 ${(removedBytes / 1048576).toFixed(1)} MB`);
md.push(`- 核心保护: train-kitty-core.jsonl 已收录全部训练内容（5602 条唯一，源 8448 行零丢失）`);
md.push('');
md.push('| # | 文件 | 行 | MB | sha256(前16) | 判定 |');
md.push('|---|---|---|---|---|---|');
rows.forEach((r, i) => md.push(`| ${i + 1} | ${r.rel} | ${r.rows ?? '-'} | ${((r.bytes || 0) / 1048576).toFixed(2)} | ${(r.sha256 || '').slice(0, 16)} | ${r.reason} |`));
md.push('');
md.push('## 保留');
md.push('```');
md.push('train-kitty-core.jsonl        训练核心（5 份源去重并集 5602 条，统一 system）');
md.push('re-qc/silver.jsonl            银样本候选池 8815 行（2046 唯一，未采用，保留备用）');
md.push('re-qc/scored.jsonl            评分台账 31053 行（reject 档已清理）');
md.push('kitty-contracts/              tools.json / ops.json / tool-tasks.json / STATS.json（工具契约）');
md.push('re-iter/                      COVERAGE.json / PLAN.json / drce-*.json（构建溯源）');
md.push('```');
fs.writeFileSync(P('CLEANUP-REPORT.md'), md.join('\n') + '\n', 'utf8');

// ── 执行删除 ──
let deleted = 0;
for (const [rel] of DROP) {
  const p = P(rel);
  if (fs.existsSync(p)) { fs.unlinkSync(p); deleted++; }
}

// ── 保留件更新：silver / scored 加 __meta 说明（JSONL 首行插入注释行会破坏解析，故写同目录 .meta.json）──
const coreRows = lines('train-kitty-core.jsonl').length;
const silverRows = lines('re-qc/silver.jsonl').length;
const scoredRows = lines('re-qc/scored.jsonl').length;
const meta = {
  __meta: {
    built: NOW,
    note: '原文件格式不变；本文件记录各保留件的角色与状态',
    core: { file: 'train-kitty-core.jsonl', rows: coreRows, sources: ['final-re', 'final-re-final', 'final-re-refined', 'final-re-dedup', 'mix-re'], dedup: 'user+assistant 指纹去重', system: '统一注入 kitty 执行层模板' },
    silver: { file: 're-qc/silver.jsonl', rows: silverRows, status: '候选池（未采用，保留备用）' },
    scored: { file: 're-qc/scored.jsonl', rows: scoredRows, status: '评分台账；其中 reject 档（20427 行）已清理，对应记录保留为历史评分' },
    contracts: { dir: 'kitty-contracts/', files: fs.readdirSync(P('kitty-contracts')) },
    iter: { dir: 're-iter/', files: fs.readdirSync(P('re-iter')) },
  },
};
fs.writeFileSync(P('KITTY-MANIFEST.json'), JSON.stringify(meta, null, 2), 'utf8');

// ── 终态 ──
const walk = (d, out = []) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); e.isDirectory() ? walk(p, out) : out.push(p); } return out; };
const all = walk(R);
const total = all.reduce((a, p) => a + fs.statSync(p).size, 0);
console.log(JSON.stringify({
  deleted_files: deleted,
  deleted_MB: +(removedBytes / 1048576).toFixed(1),
  kept_files: all.length,
  kept_MB: +(total / 1048576).toFixed(1),
  core_rows: coreRows,
  kept_list: all.map(p => path.relative(R, p).replace(/\\/g, '/')),
}, null, 2));

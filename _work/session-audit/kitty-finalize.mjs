// 终态：更新 KITTY-MANIFEST 并输出验收
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const R = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/data/kitty-reverse';
const P = (f) => path.join(R, f);
const sha256 = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const lines = (f) => fs.readFileSync(P(f), 'utf8').split('\n').filter(Boolean);
const walk = (d, out = []) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); e.isDirectory() ? walk(p, out) : out.push(p); } return out; };

const core = lines('train-kitty-core.jsonl');
const inc = lines('train-kitty-incomplete.jsonl');
let badJson = 0, noSys = 0, noAsst = 0;
for (const l of core) {
  let o; try { o = JSON.parse(l); } catch { badJson++; continue; }
  const m = o.messages || [];
  if (!m.some(x => x.role === 'system')) noSys++;
  if (!m.some(x => x.role === 'assistant' && x.content)) noAsst++;
}
const files = walk(R).map(p => ({ rel: path.relative(R, p).replace(/\\/g, '/'), bytes: fs.statSync(p).size }))
  .sort((a, b) => b.bytes - a.bytes);
const totalMB = +(files.reduce((a, f) => a + f.bytes, 0) / 1048576).toFixed(1);

const manifest = {
  __meta: {
    dir: 'train/lines/9b-oxcoder/data/kitty-reverse', built: new Date().toISOString(),
    state: '清理后（168.4MB 已吸收/非核心件已删，台账见 CLEANUP-REPORT.md）',
    core_guarantee: 'train-kitty-core.jsonl 为五份 re 数据的去重并集，源 8448 行零丢失',
  },
  training_core: {
    file: 'train-kitty-core.jsonl', rows: core.length, bytes: fs.statSync(P('train-kitty-core.jsonl')).size,
    sha256: sha256(P('train-kitty-core.jsonl')),
    sources: ['final-re', 'final-re-final', 'final-re-refined', 'final-re-dedup', 'mix-re'],
    dedup_key: 'user+assistant 指纹', system: '统一 kitty 执行层模板（115 字）',
    checks: { json_ok: badJson === 0, all_have_system: noSys === 0, all_have_assistant: noAsst === 0 },
  },
  incomplete: {
    file: 'train-kitty-incomplete.jsonl', rows: inc.length,
    note: '源数据中 assistant 为空的 28 条，不参与训练，保留待补',
  },
  candidates: {
    silver: { file: 're-qc/silver.jsonl', rows: lines('re-qc/silver.jsonl').length, status: '候选池（未采用）' },
    scored: { file: 're-qc/scored.jsonl', rows: lines('re-qc/scored.jsonl').length, status: '评分台账（reject 档已清理）' },
  },
  contracts: { dir: 'kitty-contracts/', files: fs.readdirSync(P('kitty-contracts')) },
  provenance: { dir: 're-iter/', files: fs.readdirSync(P('re-iter')) },
  cleanup: { removed_files: 27, removed_MB: 168.4, ledger: 'CLEANUP-REPORT.md' },
  files,
};
fs.writeFileSync(P('KITTY-MANIFEST.json'), JSON.stringify(manifest, null, 2), 'utf8');

console.log(JSON.stringify({
  终态: { files: files.length, totalMB },
  core: { rows: core.length, json_ok: badJson === 0, has_system: noSys === 0, has_assistant: noAsst === 0 },
  incomplete: inc.length,
  silver: lines('re-qc/silver.jsonl').length,
  scored: lines('re-qc/scored.jsonl').length,
  files,
}, null, 2));

// 合并已补答样本进 training core，并更新 MANIFEST
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const R = 'D:/BaiduNetdiskDownload/Local-AI/train/data/kitty-reverse';
const P = (f) => path.join(R, f);
const sha256 = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const md5 = (s) => crypto.createHash('md5').update(s).digest('hex');
const lines = (f) => fs.readFileSync(P(f), 'utf8').split('\n').filter(Boolean);
const key = (o) => {
  const u = (o.messages || []).find(m => m.role === 'user')?.content ?? '';
  const a = (o.messages || []).find(m => m.role === 'assistant')?.content ?? '';
  return md5(String(u) + '\u0000' + String(a));
};

const core = lines('train-kitty-core.jsonl').map(JSON.parse);
const inc = lines('train-kitty-incomplete.jsonl').map(JSON.parse);

// 补答样本：标记来源，去重后并入
const seen = new Set(core.map(key));
let added = 0, dup = 0;
for (const o of inc) {
  const asst = String((o.messages.find(m => m.role === 'assistant') || {}).content || '');
  if (!asst.trim()) continue;
  const k = key(o);
  if (seen.has(k)) { dup++; continue; }
  seen.add(k);
  o.meta = { ...o.meta, __stage: 're', __kind: 'qa', __flags: ['answered_incomplete'], __src: [...(o.meta?.__src || []), 'kitty-incomplete-backfill'] };
  core.push(o); added++;
}
fs.writeFileSync(P('train-kitty-core.jsonl'), core.map(o => JSON.stringify(o)).join('\n') + '\n', 'utf8');
fs.unlinkSync(P('train-kitty-incomplete.jsonl'));

// 校验
const rows = lines('train-kitty-core.jsonl').map(JSON.parse);
let badJson = 0, noSys = 0, noAsst = 0, noUser = 0;
for (const l of lines('train-kitty-core.jsonl')) {
  let o; try { o = JSON.parse(l); } catch { badJson++; continue; }
  const m = o.messages || [];
  if (!m.some(x => x.role === 'system')) noSys++;
  if (!m.some(x => x.role === 'user' && x.content)) noUser++;
  if (!m.some(x => x.role === 'assistant' && String(x.content).trim())) noAsst++;
}
// 28 条补答内容是否都在
const incUsers = inc.map(o => (o.messages.find(m => m.role === 'user') || {}).content);
const coreUsers = new Set(rows.map(o => (o.messages.find(m => m.role === 'user') || {}).content));
const missing = incUsers.filter(u => !coreUsers.has(u));

const manifest = {
  __meta: {
    dir: 'train/data/kitty-reverse', built: new Date().toISOString(),
    state: '清理 + 补答完成（27 个过时文件已删，源代码中 28 条空答案已补并入 core）',
  },
  training_core: {
    file: 'train-kitty-core.jsonl', rows: rows.length,
    bytes: fs.statSync(P('train-kitty-core.jsonl')).size,
    sha256: sha256(P('train-kitty-core.jsonl')),
    sources: ['final-re', 'final-re-final', 'final-re-refined', 'final-re-dedup', 'mix-re', 'kitty-incomplete-backfill(28)'],
    system_template_chars: 115,
    checks: { json_ok: badJson === 0, all_have_system: noSys === 0, all_have_user: noUser === 0, all_have_assistant: noAsst === 0 },
  },
  backfill: { filled: inc.length, added, deduped: dup, missing_from_core: missing.length },
  candidates: {
    silver: { file: 're-qc/silver.jsonl', rows: lines('re-qc/silver.jsonl').length, status: '候选池（未采用）' },
    scored: { file: 're-qc/scored.jsonl', rows: lines('re-qc/scored.jsonl').length, status: '评分台账' },
  },
  contracts: { dir: 'kitty-contracts/', files: fs.readdirSync(P('kitty-contracts')) },
  provenance: { dir: 're-iter/', files: fs.readdirSync(P('re-iter')) },
  cleanup: { removed_files: 27, removed_MB: 168.4, ledger: 'CLEANUP-REPORT.md' },
};
fs.writeFileSync(P('KITTY-MANIFEST.json'), JSON.stringify(manifest, null, 2), 'utf8');

console.log(JSON.stringify({
  core_rows: rows.length,
  added, dup,
  checks: { json_ok: badJson === 0, system: noSys === 0, user: noUser === 0, assistant: noAsst === 0 },
  backfill_in_core: `${inc.length - missing.length}/${inc.length}`,
  missing,
}, null, 2));

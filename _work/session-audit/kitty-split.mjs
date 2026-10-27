// 拆出空 assistant 的不完整样本，主 core 只留可训练样本（不丢内容）
import fs from 'node:fs';
import path from 'node:path';

const R = 'D:/BaiduNetdiskDownload/Local-AI/train/data/kitty-reverse';
const P = (f) => path.join(R, f);
const rows = fs.readFileSync(P('train-kitty-core.jsonl'), 'utf8').split('\n').filter(Boolean).map(JSON.parse);

const ok = [], bad = [];
for (const o of rows) {
  const asst = (o.messages || []).find(m => m.role === 'assistant');
  const hasAsst = asst && String(asst.content || '').trim();
  const flags = [];
  if (!hasAsst) flags.push('empty_assistant');
  if (o.meta?.__kind === 'qa') flags.push('no_system_orig');
  o.meta = { ...o.meta, __flags: flags };
  (hasAsst ? ok : bad).push(o);
}
fs.writeFileSync(P('train-kitty-core.jsonl'), ok.map(o => JSON.stringify(o)).join('\n') + '\n', 'utf8');
fs.writeFileSync(P('train-kitty-incomplete.jsonl'), bad.map(o => JSON.stringify(o)).join('\n') + '\n', 'utf8');

console.log(JSON.stringify({
  core_trainable: ok.length,
  incomplete: bad.length,
  incomplete_ids: bad.map(o => (o.messages.find(m => m.role === 'user') || {}).content?.slice(0, 30)),
}, null, 2));

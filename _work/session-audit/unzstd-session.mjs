// 解压 DSH session.v4.jsonl.zstd -> 明文 jsonl，并输出角色/长度摘要
import fs from 'node:fs';
import zlib from 'node:zlib';
import path from 'node:path';

const src = process.argv[2];
const out = process.argv[3] || path.join(path.dirname(src), 'session.plain.jsonl');
if (!src) { console.error('usage: node unzstd-session.mjs <session.v4.jsonl.zstd> [out.jsonl]'); process.exit(2); }

const buf = fs.readFileSync(src);
const raw = zlib.zstdDecompressSync(buf).toString('utf8');
fs.writeFileSync(out, raw, 'utf8');

const lines = raw.split('\n').filter(Boolean);
console.log('lines=' + lines.length + ' bytes=' + raw.length + ' out=' + out);

const stat = [];
lines.forEach((l, i) => {
  let o;
  try { o = JSON.parse(l); } catch { stat.push({ i, type: 'PARSE_FAIL', len: l.length }); return; }
  const t = o.type || o.kind || (o.message && o.message.role) || '?';
  stat.push({ i, type: t, len: l.length, keys: Object.keys(o).slice(0, 8).join(',') });
});
// 类型直方
const hist = {};
for (const s of stat) hist[s.type] = (hist[s.type] || 0) + 1;
console.log('TYPE_HIST=' + JSON.stringify(hist, null, 0));
fs.writeFileSync(out + '.index.json', JSON.stringify(stat, null, 1), 'utf8');

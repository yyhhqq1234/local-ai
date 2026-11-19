import fs from 'node:fs';
import zlib from 'node:zlib';

const src = process.argv[2];
const mode = process.argv[3] || 'head';
const b = fs.readFileSync(src);
const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
const pos = []; let i = 0;
while ((i = b.indexOf(MAGIC, i)) !== -1) { pos.push(i); i += 4; }
const outs = []; let cur = pos[0], next = 1;
while (next < pos.length) {
  try { outs.push(zlib.zstdDecompressSync(b.subarray(cur, pos[next]))); cur = pos[next]; next++; }
  catch { next++; }
}
if (cur < b.length) { try { outs.push(zlib.zstdDecompressSync(b.subarray(cur))); } catch {} }
const all = Buffer.concat(outs).toString('utf8');
const lines = all.split('\n').filter(Boolean);
if (mode === 'head') {
  console.log('lines', lines.length);
  for (const l of lines.slice(0, Number(process.argv[4] || 3))) {
    console.log('---');
    console.log(l.length > 1200 ? l.slice(0, 1200) + ' …' : l);
  }
} else if (mode === 'keys') {
  const cnt = {};
  for (const l of lines) {
    try { const o = JSON.parse(l); const k = String(o.type || o.kind || o.event || '?'); cnt[k] = (cnt[k] || 0) + 1; } catch {}
  }
  console.log(JSON.stringify(cnt, null, 1));
} else if (mode === 'model') {
  const m = new Set();
  for (const l of lines) {
    const mm = l.match(/"model"\s*:\s*"([^"]{0,120})"/g);
    if (mm) for (const x of mm) m.add(x);
  }
  console.log([...m].join('\n'));
}

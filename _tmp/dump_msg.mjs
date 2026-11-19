import fs from 'node:fs';
import zlib from 'node:zlib';
function unframe(file) {
  const b = fs.readFileSync(file);
  const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
  const pos = []; let i = 0;
  while ((i = b.indexOf(MAGIC, i)) !== -1) { pos.push(i); i += 4; }
  const outs = []; let cur = pos[0] !== undefined ? pos[0] : 0, next = 1;
  if (pos.length) {
    while (next < pos.length) {
      try { outs.push(zlib.zstdDecompressSync(b.subarray(cur, pos[next]))); cur = pos[next]; next++; } catch { next++; }
    }
    if (cur < b.length) { try { outs.push(zlib.zstdDecompressSync(b.subarray(cur))); } catch {} }
  }
  return Buffer.concat(outs).toString('utf8').split('\n').filter(Boolean).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
}
const evs = unframe(process.argv[2]);
const lim = Number(process.argv[3] || 1500);
for (const e of evs) {
  if (e.type !== 'assistant/message') continue;
  const m = e.data?.message || e.data;
  let t = typeof m?.content === 'string' ? m.content : (Array.isArray(m?.content) ? m.content.map(x => x?.text || '').join('') : '');
  console.log('=== assistant message len=' + t.length + ' ===');
  console.log(t.slice(0, lim));
  if (t.length > lim * 2) console.log('\n…[中略 ' + (t.length - lim * 2) + ' 字]…\n');
  console.log(t.slice(-lim));
}

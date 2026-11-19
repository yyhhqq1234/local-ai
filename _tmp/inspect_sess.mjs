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
      try { outs.push(zlib.zstdDecompressSync(b.subarray(cur, pos[next]))); cur = pos[next]; next++; }
      catch { next++; }
    }
    if (cur < b.length) { try { outs.push(zlib.zstdDecompressSync(b.subarray(cur))); } catch {} }
  }
  return Buffer.concat(outs).toString('utf8').split('\n').filter(Boolean).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
}
const f = process.argv[2];
const evs = unframe(f);
console.log('events', evs.length);
for (const e of evs) {
  if (['session', 'model/selection', 'request/header', 'request/context', 'agent/inbox/spliced', 'session/title'].includes(e.type)) {
    const s = JSON.stringify(e.data ?? e).slice(0, 400);
    console.log(`\n[${e.type}] ${s}`);
  }
}
// 找最高重复的 assistant 文本段
function textOf(m) {
  if (!m) return '';
  if (typeof m.content === 'string') return m.content;
  if (Array.isArray(m.content)) return m.content.map(x => (x && x.text) || '').join('');
  if (typeof m.text === 'string') return m.text;
  return '';
}
let best = null;
const msgs = evs.filter(e => e.type === 'assistant/message');
console.log('\nassistant messages', msgs.length);
for (const e of msgs) {
  const m = e.data?.message || e.data;
  const t = textOf(m);
  if (!t || t.length < 2000) continue;
  // 找最长连续重复子串（粗略：句子重复）
  const ss = t.split(/[。！？\n]/).filter(s => s.length > 10);
  const c = new Map();
  for (const s of ss) { const k = s.trim(); c.set(k, (c.get(k) || 0) + 1); }
  const top = [...c.entries()].sort((a, b) => b[1] - a[1])[0];
  if (top && (!best || top[1] > best.cnt)) best = { cnt: top[1], sent: top[0], len: t.length, t };
}
if (best) {
  console.log(`\n=== 最严重复读: 同一句重复 ${best.cnt} 次 (消息长 ${best.len} 字) ===`);
  console.log('句子:', best.sent.slice(0, 120));
  const idx = best.t.indexOf(best.sent.slice(0, 40));
  console.log('--- 原文片段 ---');
  console.log(best.t.slice(Math.max(0, idx - 100), idx + 700));
}

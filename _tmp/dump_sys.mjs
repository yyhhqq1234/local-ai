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
for (const e of evs) {
  if (e.type === 'system/message') {
    const m = e.data?.message || e.data;
    const t = typeof m?.content === 'string' ? m.content : (Array.isArray(m?.content) ? m.content.map(x => x?.text || '').join('') : JSON.stringify(m));
    console.log('SYSTEM len=' + t.length);
    const hits = ['nsfw', 'NSFW', 'train-2b', 'gate', '门控', '色情'].map(k => [k, (t.match(new RegExp(k, 'g')) || []).length]);
    console.log('关键词计数:', JSON.stringify(hits));
    console.log('--- 前 700 字 ---');
    console.log(t.slice(0, 700));
  }
  if (e.type === 'request/header') {
    const tools = e.data?.header?.tools || [];
    const sys = e.data?.header?.systemPrompt || '';
    console.log('\nHEADER tools=' + tools.length + ' systemPromptLen=' + String(sys).length);
    console.log('tool names:', tools.slice(0, 25).map(t => t.name).join(','));
  }
}

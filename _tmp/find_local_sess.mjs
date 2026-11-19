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
function textOf(m) {
  if (!m) return '';
  if (typeof m.content === 'string') return m.content;
  if (Array.isArray(m.content)) return m.content.map(x => (x && x.text) || '').join('');
  if (typeof m.text === 'string') return m.text;
  return '';
}
function ngramRep(t, n = 24) {
  if (t.length < n * 2) return 0;
  const c = new Map(); let rep = 0, tot = 0;
  for (let i = 0; i + n <= t.length; i += 4) {
    const g = t.slice(i, i + n); tot++;
    const v = (c.get(g) || 0) + 1; c.set(g, v);
    if (v > 1) rep++;
  }
  return tot ? rep / tot : 0;
}
function topSent(t) {
  const ss = t.split(/[。！？\n]/).filter(s => s.length > 14);
  const c = new Map();
  for (const s of ss) { const k = s.trim().slice(0, 30); c.set(k, (c.get(k) || 0) + 1); }
  let best = ['', 0];
  for (const [k, v] of c) if (v > best[1]) best = [k, v];
  return best;
}

const dir = process.argv[2];
const filter = process.argv[3] || 'ninfer';
const subs = fs.readdirSync(dir).filter(n => fs.statSync(`${dir}/${n}`).isDirectory());
for (const sub of subs) {
  const f = `${dir}/${sub}/session.v4.jsonl.zstd`;
  if (!fs.existsSync(f)) continue;
  let evs;
  try { evs = unframe(f); } catch { continue; }
  const providers = new Set();
  let steps = 0, nAsst = 0, worst = 0, worstTop = ['', 0], worstText = '';
  let toolCalls = 0;
  const maxTok = [];
  for (const e of evs) {
    if (e.type === 'request/header') {
      const c = e.data?.header?.config || {};
      if (c.provider) providers.add(String(c.provider) + '/' + String(c.model || '').slice(0, 40));
      if (c.maxTokens) maxTok.push(c.maxTokens);
    }
    if (e.type === 'step/start') steps++;
    if (e.type === 'assistant/message') {
      nAsst++;
      const m = e.data?.message || e.data;
      const t = textOf(m);
      if (t.length > 400) {
        const r = ngramRep(t);
        if (r > worst) { worst = r; worstText = t; worstTop = topSent(t); }
      }
      if (Array.isArray(m?.content)) toolCalls += m.content.filter(b => b && b.type === 'tool-call').length;
    }
  }
  const tag = [...providers].join(',');
  if (!tag.toLowerCase().includes(filter.toLowerCase())) continue;
  console.log(`[${sub.slice(0, 22)}] steps=${steps} asst=${nAsst} calls=${toolCalls} rep=${worst.toFixed(3)} top=x${worstTop[1]} maxTok=${[...new Set(maxTok)].join('/')} | ${tag.slice(0, 120)}`);
  if (worst > 0.25 && worstText) {
    const snip = worstTop[0];
    const idx = worstText.indexOf(snip);
    console.log(`   ↳ 高频句: ${snip}`);
    console.log(`   ↳ 片段: ${worstText.slice(Math.max(0, idx - 60), idx + 260).replace(/\n/g, ' / ')}`);
  }
}

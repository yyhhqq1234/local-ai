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

function textOf(msg) {
  if (!msg) return '';
  if (typeof msg.content === 'string') return msg.content;
  if (Array.isArray(msg.content)) return msg.content.map(b => (b && (b.text || (b.type === 'tool-call' ? '' : ''))) || '').join('');
  if (typeof msg.text === 'string') return msg.text;
  return '';
}
function toolsOf(msg) {
  if (!msg || !Array.isArray(msg.content)) return [];
  return msg.content.filter(b => b && b.type === 'tool-call').map(b => String(b.name || '') + '|' + String(b.arguments || ''));
}

function ngramRep(t, n = 24) {
  if (t.length < n * 2) return 0;
  const c = new Map(); let rep = 0; let tot = 0;
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
  for (const s of ss) { const k = s.trim().slice(0, 40); c.set(k, (c.get(k) || 0) + 1); }
  let best = ['', 0];
  for (const [k, v] of c) if (v > best[1]) best = [k, v];
  return best;
}

const dir = process.argv[2];
const subs = fs.readdirSync(dir).filter(n => fs.statSync(`${dir}/${n}`).isDirectory());
const rows = [];
for (const sub of subs) {
  const f = `${dir}/${sub}/session.v4.jsonl.zstd`;
  if (!fs.existsSync(f)) continue;
  let evs;
  try { evs = unframe(f); } catch (e) { continue; }
  let model = '';
  let steps = 0, nAsst = 0;
  let worstRep = 0, worstTop = ['', 0], worstMsg = '';
  const callSigs = [];
  for (const e of evs) {
    if (e.type === 'model/selection') {
      const d = e.data || {};
      model = String(d.model || d.name || d.id || JSON.stringify(d).slice(0, 100));
    }
    if (e.type === 'step/start') steps++;
    if (e.type === 'assistant/message') {
      nAsst++;
      const m = e.data?.message || e.data;
      const t = textOf(m);
      if (t.length > 200) {
        const r = ngramRep(t);
        if (r > worstRep) {
          worstRep = r; worstMsg = t.slice(0, 80); worstTop = topSent(t);
        }
      }
      for (const s of toolsOf(m)) callSigs.push(s);
    }
  }
  // 连续相同调用
  let maxRun = 0, run = 1;
  for (let i = 1; i < callSigs.length; i++) {
    run = callSigs[i] === callSigs[i - 1] ? run + 1 : 1;
    if (run > maxRun) maxRun = run;
  }
  rows.push({ sub, model, steps, nAsst, calls: callSigs.length, worstRep: +worstRep.toFixed(3), top: worstTop, maxRun, worstMsg });
}
// 输出 9B 相关 + 全部概览
const is9b = r => /9b|llama|kittyrev9b/i.test(r.model) || /9b|llama/i.test(r.sub);
console.log('total sessions', rows.length);
console.log('=== 9B 会话 ===');
for (const r of rows.filter(is9b).sort((a, b) => b.steps - a.steps)) {
  console.log(`[${r.sub.slice(0, 20)}] model=${r.model.slice(0, 60)} steps=${r.steps} asst=${r.nAsst} calls=${r.calls} 重复率=${r.worstRep} 高频句x${r.top[1]}:${r.top[0].slice(0, 40)} 连续同调用=${r.maxRun}`);
}
console.log('=== 全部按步数 top10 ===');
for (const r of rows.sort((a, b) => b.steps - a.steps).slice(0, 10)) {
  console.log(`[${r.sub.slice(0, 20)}] model=${(r.model || '?').slice(0, 45)} steps=${r.steps} calls=${r.calls} 重复率=${r.worstRep} 高频句x${r.top[1]} 连续同调用=${r.maxRun}`);
}

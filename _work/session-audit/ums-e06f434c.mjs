import fs from 'node:fs';
const src = process.argv[2];
const lines = fs.readFileSync(src, 'utf8').split('\n').filter(Boolean);
const ev = [];
for (const l of lines) { try { ev.push(JSON.parse(l)); } catch {} }
const txt = (content) => Array.isArray(content) ? content.filter(c => c.type === 'text').map(c => c.text).join('\n') : String(content ?? '');
const um = ev.filter(e => e.type === 'user/message');
const byLen = um.map(e => txt(e.data.content));
const lens = byLen.map(s => s.length).sort((a, b) => a - b);
console.log('count=' + um.length + ' min=' + lens[0] + ' p50=' + lens[Math.floor(lens.length / 2)] + ' p90=' + lens[Math.floor(lens.length * 0.9)] + ' max=' + lens[lens.length - 1]);
const counts = {};
for (const s of byLen) { const k = s.slice(0, 60).replace(/\n/g, ' '); counts[k] = (counts[k] || 0) + 1; }
const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 25);
for (const [k, v] of top) console.log(v + ' | ' + k);

import fs from 'node:fs';
const L = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
const sys = JSON.parse(L[10]).data.message.content.map(b=>b.text||'').join('\n');
console.log('system chars:', sys.length);
// 找重复的大段：按 200 字符窗口滑窗统计
const win = 400;
const seen = new Map();
for (let i=0;i+win<=sys.length;i+=100) {
  const k = sys.slice(i,i+win);
  seen.set(k, (seen.get(k)||0)+1);
}
const dups = [...seen.entries()].filter(([,c])=>c>1).sort((a,b)=>b[1]-a[1]);
console.log('重复窗口数:', dups.length);
let covered = 0;
const coveredIdx = [];
for (const [k,c] of dups) { coveredIdx.push([sys.indexOf(k), c]); }
// 粗算：用标题行定位重复章节
const heads = [...sys.matchAll(/^(#{1,3} .+)$/gm)].map(m=>({t:m[1], i:m.index}));
const freq = new Map();
for (const h of heads) freq.set(h.t, (freq.get(h.t)||0)+1);
const rep = [...freq.entries()].filter(([,c])=>c>1);
console.log('重复标题:', rep.length);
for (const [t,c] of rep.slice(0,15)) console.log(`  x${c} ${t}`);

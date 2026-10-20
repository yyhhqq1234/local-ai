import fs from 'node:fs';
const lines = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
const get = (i)=>JSON.parse(lines[i]).data.message.content;
// turn2 tail
const t2 = get(31).filter(b=>b.type==='text').map(b=>b.text).join('');
console.log('=== turn2 text tail ===\n'+t2.slice(-600));
// turn3 reasoning mid samples
for (const idx of [41,52]) {
  const r = get(idx).filter(b=>b.type==='reasoning').map(b=>b.text).join('');
  console.log(`\n=== #${idx} reasoning sample @25% ===\n`+r.slice(Math.floor(r.length*0.25), Math.floor(r.length*0.25)+1200));
  console.log(`\n=== #${idx} reasoning sample @70% ===\n`+r.slice(Math.floor(r.length*0.70), Math.floor(r.length*0.70)+1000));
}

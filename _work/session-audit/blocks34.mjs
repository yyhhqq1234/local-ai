import fs from 'node:fs';
const lines = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
for (const idx of [41,52]) {
  const o = JSON.parse(lines[idx]);
  const d = o.data, m = d.message;
  console.log(`\n===== #${idx} turn=${d.turn} usage=${JSON.stringify(d.usage)} keys=${Object.keys(d).join(',')} stop=${JSON.stringify(d.stopReason||d.finishReason||'')} =====`);
  m.content.forEach((b,bi)=>{
    const t = b.text||'';
    console.log(`block${bi} ${b.type} len=${t.length}`);
    console.log('  HEAD:', JSON.stringify(t.slice(0,300)));
    console.log('  TAIL:', JSON.stringify(t.slice(-400)));
  });
}

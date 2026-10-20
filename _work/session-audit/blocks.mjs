import fs from 'node:fs';
const lines = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
for (const idx of [22,31,41,52]) {
  const o = JSON.parse(lines[idx]);
  const m = o.data.message;
  console.log(`\n=========== #${idx} turn=${o.data.turn} step=${o.data.step} usage=${JSON.stringify(o.data.usage||o.data.stopReason||'')} ===========`);
  for (const [bi,b] of m.content.entries()) {
    console.log(`--- block ${bi} type=${b.type} len=${(b.text||'').length} ---`);
    console.log((b.text||JSON.stringify(b)).slice(0, 3000));
  }
}

import fs from 'node:fs';
const src = process.argv[2];
const lines = fs.readFileSync(src, 'utf8').split('\n').filter(Boolean);
const hist = {};
const rows = [];
lines.forEach((l, i) => {
  let o; try { o = JSON.parse(l); } catch { hist.PARSE_FAIL = (hist.PARSE_FAIL || 0) + 1; return; }
  const t = o.type || o.kind || '?';
  hist[t] = (hist[t] || 0) + 1;
  rows.push({ i, t, keys: Object.keys(o).join(','), len: l.length });
});
console.log('LINES=' + lines.length);
console.log('HIST=' + JSON.stringify(hist));
for (let i = 0; i < Math.min(rows.length, 12); i++) console.log('ROW', JSON.stringify(rows[i]));
// distinct key-shapes per type
const shapes = {};
for (const r of rows) { const k = r.t + ' :: ' + r.keys; shapes[k] = (shapes[k] || 0) + 1; }
console.log('SHAPES:');
for (const [k, v] of Object.entries(shapes)) console.log(v + '  ' + k);
fs.writeFileSync(src + '.index.json', JSON.stringify(rows), 'utf8');

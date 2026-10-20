import fs from 'node:fs';
const lines = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
lines.forEach((l, idx) => {
  let o; try { o = JSON.parse(l); } catch { console.log(idx, 'PARSE_FAIL', l.slice(0,120)); return; }
  const t = o.type || o.kind || '?';
  const keys = Object.keys(o).join(',');
  let s = '';
  const pick = o.text ?? o.content ?? o.message ?? o.data ?? o.payload;
  if (typeof pick === 'string') s = pick.replace(/\s+/g,' ').slice(0,160);
  else if (pick) s = JSON.stringify(pick).replace(/\s+/g,' ').slice(0,160);
  console.log(`#${idx} type=${t} role=${o.role||''} len=${l.length} keys=[${keys}] :: ${s}`);
});

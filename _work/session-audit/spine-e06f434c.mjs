import fs from 'node:fs';
const src = process.argv[2], outp = process.argv[3];
const lines = fs.readFileSync(src, 'utf8').split('\n').filter(Boolean);
const ev = [];
for (const l of lines) { try { ev.push(JSON.parse(l)); } catch {} }
const txt = (content, cap) => {
  if (!Array.isArray(content)) return String(content ?? '');
  const ps = [];
  for (const c of content) { if (c.type === 'text') ps.push(c.text); else if (c.type === 'image') ps.push('[image]'); else ps.push('[' + c.type + ']'); }
  let s = ps.join('\n');
  if (cap && s.length > cap) s = s.slice(0, cap) + `…(+${s.length - cap})`;
  return s;
};
const NOISE = [/^\[SHIYI TOOL LOCK\]/, /^<system-reminder>/, /^Current runtime context/, /^This is an automatically generated checkpoint/, /^Time sampled while/, /^\[model changed/, /^<skill_content/, /^<compacted-summary>/];
let o = '', turn = 0;
for (const e of ev) {
  const t = e.type, d = e.data;
  if (t === 'turn/start') { turn = d.turn ?? turn + 1; continue; }
  if (t === 'user/message') {
    const s = txt(d.content);
    if (NOISE.some(r => r.test(s))) continue;
    if (/^<goal_round>/.test(s)) { o += `T${turn} [AUTO-ROUND] ${s.split('\n')[0].slice(0, 160)}\n`; continue; }
    let body = s.length > 1200 ? s.slice(0, 1200) + `…(+${s.length - 1200})` : s;
    o += `\nT${turn} >>> USER: ${body.replace(/\n/g, '\n    ')}\n`;
    continue;
  }
  if (t === 'assistant/message') { const b = txt(d.message?.content, 700).trim(); if (b) o += `T${turn} A: ${b.replace(/\n/g, '\n    ')}\n`; continue; }
  if (t === 'compaction/summary') { o += `\nT${turn} ===== COMPACTION SUMMARY =====\n${txt(d.summary, 5000)}\n`; continue; }
  if (t === 'goal/change') { o += `\nT${turn} ===== GOAL ${d.operation} =====\n${(d.goal?.objective || JSON.stringify(d.goal || {})).slice(0, 1200)}\n`; continue; }
  if (t === 'todo/write') { o += `T${turn} [TODO] ${(d.todos || []).map(x => x.status + ':' + x.content).join(' | ')}\n`; continue; }
  if (t === 'session/title') { o = `# TITLE ${d.title}\n` + o; continue; }
}
fs.writeFileSync(outp, o, 'utf8');
console.log('spine bytes=' + o.length + ' lines=' + o.split('\n').length);

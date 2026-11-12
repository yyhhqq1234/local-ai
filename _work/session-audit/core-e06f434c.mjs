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
  if (t === 'turn/start') { turn = d.turn ?? turn + 1; o += `\n\n## T${turn} ${new Date(d.time || e.time).toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' })}\n`; continue; }
  if (t === 'user/message') {
    const s = txt(d.content);
    if (NOISE.some(r => r.test(s))) continue;
    let body = s;
    if (/^<goal_round>/.test(s)) body = '[GOAL-ROUND] ' + s.slice(0, 300).replace(/\n/g, ' ');
    if (body.length > 1500) body = body.slice(0, 1500) + `…(+${body.length - 1500})`;
    o += `U: ${body.replace(/\n/g, '\n   ')}\n`;
    continue;
  }
  if (t === 'assistant/message') { const b = txt(d.message?.content, 700); if (b.trim()) o += `A: ${b.replace(/\n/g, '\n   ')}\n`; continue; }
  if (t === 'tool/call') { o += `· ${d.name} ${String(d.arguments ?? '').replace(/\s+/g, ' ').slice(0, 130)}\n`; continue; }
  if (t === 'tool/result') { const m = d.message || {}; if (m.isError) o += `  !ERR ${txt(m.content, 300).replace(/\n/g, ' ⏎ ')}\n`; continue; }
  if (t === 'compaction/summary') { o += `\n[COMPACT] ${txt(d.summary, 3000)}\n`; continue; }
  if (t === 'goal/change') { o += `\n[GOAL ${d.operation}] ${(d.goal?.objective || '').slice(0, 600)}\n`; continue; }
  if (t === 'session/title') { o = `# ${d.title}\n` + o; continue; }
}
fs.writeFileSync(outp, o, 'utf8');
console.log('core bytes=' + o.length + ' lines=' + o.split('\n').length);

import fs from 'node:fs';
const src = process.argv[2], out = process.argv[3];
const lines = fs.readFileSync(src, 'utf8').split('\n').filter(Boolean);
const ev = [];
for (const l of lines) { try { ev.push(JSON.parse(l)); } catch {} }
const txt = (content, cap) => {
  if (!Array.isArray(content)) return String(content ?? '');
  const parts = [];
  for (const c of content) {
    if (c.type === 'text') parts.push(c.text);
    else if (c.type === 'image') parts.push('[image]');
    else parts.push('[' + (c.type || '?') + ']');
  }
  let s = parts.join('\n').replace(/\n{3,}/g, '\n\n');
  if (cap && s.length > cap) s = s.slice(0, cap) + `…(+${s.length - cap})`;
  return s;
};
let o = '';
let turn = 0;
for (const e of ev) {
  const t = e.type, d = e.data;
  if (t === 'turn/start') { turn = d.turn ?? turn + 1; o += `\n\n## T${turn}\n`; continue; }
  if (t === 'user/message') { o += `U: ${txt(d.content, 900)}\n`; continue; }
  if (t === 'assistant/message') { const b = txt(d.message?.content, 450); if (b.trim()) o += `A: ${b}\n`; continue; }
  if (t === 'tool/call') { o += `·${d.name} ${String(d.arguments ?? '').replace(/\s+/g, ' ').slice(0, 110)}\n`; continue; }
  if (t === 'tool/result') { const m = d.message || {}; if (m.isError) o += `  ERR: ${txt(m.content, 260).replace(/\n/g, ' ⏎ ')}\n`; continue; }
  if (t === 'compaction/summary') { o += `\n[COMPACTION] ${txt(d.summary, 2500)}\n`; continue; }
  if (t === 'goal/change') { o += `\n[GOAL ${d.operation}] ${d.goal?.objective || ''}\n`; continue; }
  if (t === 'session/title') { o = `# TITLE: ${d.title}\n` + o; continue; }
}
fs.writeFileSync(out, o, 'utf8');
console.log('skim bytes=' + o.length + ' lines=' + o.split('\n').length + ' turns=' + turn);

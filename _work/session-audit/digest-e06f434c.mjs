import fs from 'node:fs';
const src = process.argv[2];
const outDir = process.argv[3];
const lines = fs.readFileSync(src, 'utf8').split('\n').filter(Boolean);
const ev = [];
for (const l of lines) { try { ev.push(JSON.parse(l)); } catch {} }

const ts = (t) => t ? new Date(t).toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }) : '';
const txt = (content, cap) => {
  if (!Array.isArray(content)) return String(content ?? '');
  const parts = [];
  for (const c of content) {
    if (c.type === 'text') parts.push(c.text);
    else if (c.type === 'image') parts.push('[image ' + (c.mimeType || '') + ' ' + (c.data ? c.data.length : 0) + 'b]');
    else parts.push('[' + (c.type || '?') + ']');
  }
  let s = parts.join('\n');
  if (cap && s.length > cap) s = s.slice(0, cap) + `\n…[+${s.length - cap} chars]`;
  return s;
};

const meta = ev.find(e => e.type === 'session');
const title = ev.find(e => e.type === 'session/title');

// ---------- digest ----------
let dg = '';
dg += `# 会话摘要 digest — ${meta.id}\n\n`;
dg += `- cwd: ${meta.cwd}\n- 创建: ${ts(meta.createdAt)}\n- 标题: ${title ? title.data.title : '(无)'}\n\n`;
const models = new Set();
for (const e of ev) if (e.type === 'assistant/message') { const s = e.data.message?.source; if (s?.provider) models.add(s.provider + '/' + s.model); }
dg += `- 模型: ${[...models].join(', ') || '(无)'}\n\n---\n\n`;

let turn = 0, lastTurn = -1;
for (const e of ev) {
  const t = e.type, d = e.data;
  if (t === 'turn/start') { turn = d.turn ?? turn + 1; dg += `\n\n### [TURN ${turn}] ${ts(d.time || e.time)}\n`; continue; }
  if (t === 'user/message') { dg += `\n**USER:** ${txt(d.content, 1400)}\n`; continue; }
  if (t === 'assistant/message') {
    const m = d.message || {};
    const body = txt(m.content, 2200);
    dg += `\n**ASSISTANT:** ${body}\n`;
    continue;
  }
  if (t === 'tool/call') { dg += `  - call ${d.name} ${String(d.arguments ?? '').slice(0, 300)}\n`; continue; }
  if (t === 'tool/result') {
    const m = d.message || {};
    const body = txt(m.content, 400).replace(/\n/g, ' ⏎ ');
    dg += `    ↳ ${m.isError ? 'ERR ' : ''}${body}\n`;
    continue;
  }
  if (t === 'compaction/summary') { dg += `\n**[COMPACTION SUMMARY]**\n${txt(d.summary, 6000)}\n`; continue; }
  if (t === 'goal/change') { dg += `\n**[GOAL ${d.operation}]** ${d.goal?.objective || d.goal?.phase || ''}\n`; continue; }
  if (t === 'todo/write') { dg += `\n**[TODO]** ${(d.todos || []).map(x => x.status + ':' + x.content).join(' | ')}\n`; continue; }
}
fs.writeFileSync(outDir + '/s-e06f434c.digest.md', dg, 'utf8');

// ---------- full transcript ----------
let tr = `# 完整会话记录 — ${meta.id}\n\ncwd: ${meta.cwd} · 创建 ${ts(meta.createdAt)}\n\n`;
turn = 0;
for (const e of ev) {
  const t = e.type, d = e.data;
  if (t === 'session') continue;
  if (t === 'turn/start') { turn = d.turn ?? turn + 1; tr += `\n\n---\n\n## TURN ${turn} · ${ts(d.time || e.time)}\n`; continue; }
  if (t === 'user/message') { tr += `\n### USER (seq ${e.seq})\n${txt(d.content)}\n`; continue; }
  if (t === 'assistant/message') { const m = d.message || {}; tr += `\n### ASSISTANT (seq ${e.seq}) ${m.source?.provider || ''}/${m.source?.model || ''}\n${txt(m.content)}\n`; continue; }
  if (t === 'tool/call') { tr += `\n#### tool/call ${d.name} (seq ${e.seq})\n\`\`\`json\n${String(d.arguments ?? '')}\n\`\`\`\n`; continue; }
  if (t === 'tool/result') { const m = d.message || {}; let b = txt(m.content); if (b.length > 20000) b = b.slice(0, 20000) + `\n…[+${b.length - 20000} chars]`; tr += `\n#### tool/result ${m.isError ? '(ERROR) ' : ''}(seq ${e.seq})\n\`\`\`\n${b}\n\`\`\`\n`; continue; }
  if (t === 'compaction/summary') { tr += `\n### [COMPACTION SUMMARY seq ${e.seq}]\n${txt(d.summary)}\n`; continue; }
  if (t === 'goal/change') { tr += `\n### [GOAL ${d.operation}]\n${JSON.stringify(d.goal || d, null, 1)}\n`; continue; }
  if (t === 'todo/write') { tr += `\n### [TODO]\n${JSON.stringify(d.todos, null, 1)}\n`; continue; }
  if (t === 'session/title') { tr += `\n### [TITLE] ${d.title}\n`; continue; }
  if (t === 'llm/retry' || t === 'llm/retry-started') { tr += `\n### [${t}] ${JSON.stringify(d).slice(0, 500)}\n`; continue; }
}
fs.writeFileSync(outDir + '/s-e06f434c.transcript.md', tr, 'utf8');

const dgLen = dg.length, trLen = tr.length;
console.log('digest bytes=' + dgLen + ' transcript bytes=' + trLen + ' turns=' + turn + ' models=' + [...models].join(','));
// tool histogram
const hist = {};
for (const e of ev) if (e.type === 'tool/call') hist[e.data.name] = (hist[e.data.name] || 0) + 1;
const sorted = Object.entries(hist).sort((a, b) => b[1] - a[1]);
console.log('TOOLS=' + sorted.map(([k, v]) => k + ':' + v).join(' '));

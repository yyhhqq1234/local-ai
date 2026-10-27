// 会话 2cbdee74 对话主干提取 → 可读 markdown
import fs from 'node:fs';
const A = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/';
const lines = fs.readFileSync(A + 'sess-2cbdee74.jsonl', 'utf8').split('\n').filter(Boolean);
const evs = [];
for (const ln of lines) { try { evs.push(JSON.parse(ln)); } catch {} }

const ts = (t) => new Date(t).toISOString().replace('T', ' ').slice(0, 19);
const out = [];
let turn = 0;

for (const o of evs) {
  if (o.type === 'turn/start') { turn = o.data?.turn ?? turn + 1; out.push(`\n\n# ===== TURN ${turn} (${ts(o.time)}) =====`); continue; }
  if (o.type === 'session/title') { out.push(`\n> [title] ${JSON.stringify(o.data).slice(0, 300)}`); continue; }
  if (o.type === 'workspace/changes') { out.push(`\n> [workspace] ${JSON.stringify(o.data).slice(0, 500)}`); continue; }

  if (o.type === 'user/message') {
    const d = o.data; const src = d.source || {};
    const body = (d.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
    out.push(`\n## [USER seq=${o.seq} kind=${src.kind || '?'}] ${ts(o.time)}\n${body}`);
    if (src.kind && src.kind !== 'user') out.push(`> (source: ${JSON.stringify(src).slice(0, 240)})`);
    continue;
  }
  if (o.type === 'assistant/message') {
    const m = o.data?.message || {};
    const parts = [];
    for (const c of m.content || []) {
      if (c.type === 'text' && c.text) parts.push(`### A-text\n${c.text}`);
      else if (c.type === 'reasoning' && c.text) parts.push(`<details><summary>reasoning</summary>\n\n${c.text}\n\n</details>`);
      else if (c.type === 'tool-call') {
        let args = c.arguments; try { args = JSON.stringify(JSON.parse(args)); } catch {}
        parts.push(`### TOOL-CALL \`${c.name}\`\n\`\`\`json\n${String(args).slice(0, 2000)}\n\`\`\``);
      }
    }
    out.push(`\n<!-- A seq=${o.seq} step=${o.data?.step} tok=${o.data?.usage?.inputTokens}/${o.data?.usage?.outputTokens} -->\n` + parts.join('\n\n'));
    continue;
  }
  if (o.type === 'tool/result') {
    const d = o.data || {};
    let txt = typeof d.output === 'string' ? d.output : JSON.stringify(d.output ?? d.result ?? d).slice(0, 0);
    if (!txt) txt = JSON.stringify(d).slice(0, 3000);
    out.push(`### TOOL-RESULT \`${d.name || ''}\` (${String(txt).length} chars)\n\`\`\`\n${String(txt).slice(0, 3000)}\n\`\`\``);
    continue;
  }
}

fs.writeFileSync(A + 'sess-2cbdee74.dialog.md', out.join('\n'));
console.log('written', out.length, 'blocks');
const stat = fs.statSync(A + 'sess-2cbdee74.dialog.md');
console.log('size', stat.size);

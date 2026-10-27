// 提取会话 2cbdee74 的对话主干：user 原文 / assistant 文本 / tool 调用摘要
import fs from 'node:fs';

const P = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/sess-2cbdee74.jsonl';
const lines = fs.readFileSync(P, 'utf8').split('\n').filter(Boolean);

const types = new Map();
const evs = [];
for (const ln of lines) {
  let o; try { o = JSON.parse(ln); } catch { continue; }
  types.set(o.type, (types.get(o.type) || 0) + 1);
  evs.push(o);
}
console.log('=== 事件类型分布 ===');
for (const [k, v] of [...types.entries()].sort((a, b) => b[1] - a[1])) console.log(String(v).padStart(5), k);

const out = [];
const clip = (s, n) => (s || '').replace(/\r/g, '').slice(0, n);

function walkContent(arr, sink) {
  for (const c of arr || []) {
    if (!c || typeof c !== 'object') continue;
    if (c.type === 'text' && c.text) sink.push({ k: 'text', v: c.text });
    else if (c.type === 'reasoning' && c.text) sink.push({ k: 'reason', v: c.text });
    else if (c.type === 'tool-call' || c.type === 'tool_use') sink.push({ k: 'tool', v: JSON.stringify(c).slice(0, 400) });
    else if (c.type === 'tool-result') sink.push({ k: 'toolresult', v: JSON.stringify(c).slice(0, 300) });
  }
}

for (const o of evs) {
  if (o.type === 'agent/inbox/spliced') {
    for (const m of o.data?.inserted || []) {
      if (m.role !== 'user') continue;
      const sink = [];
      if (typeof m.content === 'string') sink.push({ k: 'text', v: m.content });
      else walkContent(m.content, sink);
      for (const s of sink) {
        if (s.k === 'text') out.push({ kind: 'USER', seq: o.seq, time: o.time, text: clip(s.v, 3000) });
      }
    }
  } else if (o.type === 'message/added' || o.type === 'agent/message' || o.type === 'message') {
    const d = o.data || o;
    const msg = d.message || d;
    const role = msg.role || d.role;
    const sink = [];
    if (typeof msg.content === 'string') sink.push({ k: 'text', v: msg.content });
    else walkContent(msg.content, sink);
    for (const s of sink) {
      out.push({ kind: role === 'user' ? 'USER' : (role === 'assistant' ? 'A' : role || '?'), sub: s.k, seq: o.seq, time: o.time, text: clip(s.v, s.k === 'text' ? 4000 : 600) });
    }
  }
}

fs.writeFileSync('D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/sess-2cbdee74.flow.json', JSON.stringify(out, null, 1));
console.log('\n=== flow 条目 ===', out.length, ' → sess-2cbdee74.flow.json');

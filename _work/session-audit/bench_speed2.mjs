const label = process.argv[2] || 'cur';
const N = parseInt(process.argv[3] || '1024', 10);
const t0 = Date.now();
const r = await fetch('http://127.0.0.1:1234/v1/chat/completions', {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({
    model: (process.env.MODEL || 'qwen3.8-27b-ablit-swift15-iq2s'),
    messages: [{ role: 'user', content: '用 800 字详细解释 TCP 拥塞控制的四个阶段，只输出正文。' }],
    max_tokens: N, temperature: 0, stream: true, stream_options: { include_usage: true },
  }),
});
let first = null, last = null, deltas = 0, usage = null;
const dec = new TextDecoder(); let buf = '';
for await (const c of r.body) {
  buf += dec.decode(c, { stream: true });
  let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
    if (!line.startsWith('data:')) continue;
    const p = line.slice(5).trim(); if (p === '[DONE]') continue;
    try { const j = JSON.parse(p); const d = j.choices?.[0]?.delta;
      if (d?.content || d?.reasoning_content) { if (first === null) first = Date.now(); last = Date.now(); deltas++; }
      if (j.usage) usage = j.usage;
    } catch {}
  }
}
const gen = (last - first) / 1000;
const out = usage?.completion_tokens || 0;
console.log(JSON.stringify({
  label, ttftMs: first - t0, deltas,
  outTokens: out, reasoningTokens: usage?.completion_tokens_details?.reasoning_tokens,
  genSecs: +gen.toFixed(2),
  tokPerSec: +(out / gen).toFixed(1),
  totalSecs: +((Date.now() - t0) / 1000).toFixed(1),
}));

// 上下文长度 vs decode 速度
const tiers = [0, 2000, 8000, 20000, 40000];
const FILLER = '背景资料：本地推理引擎在长上下文下的带宽开销主要来自 KV cache 读取，随着会话增长，每生成一个 token 需要读取的历史 KV 也线性增加，因此 decode 速度会逐步下降。';
async function run(tokens) {
  const chars = Math.max(0, Math.round(tokens * 1.6));
  const filler = chars > 0 ? FILLER.repeat(Math.ceil(chars / FILLER.length)).slice(0, chars) : '';
  const t0 = Date.now();
  const r = await fetch('http://127.0.0.1:1234/v1/chat/completions', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      model: 'qwen3.8-27b-ablit-swift15-iq2s',
      messages: [{ role: 'user', content: filler + '\n\n以上是背景。写 120 字短文，主题：夜雨。只输出正文。' }],
      max_tokens: 192, temperature: 0, stream: true, stream_options: { include_usage: true },
    }),
  });
  let first = null, last = null, usage = null;
  const dec = new TextDecoder(); let buf = '';
  for await (const c of r.body) {
    buf += dec.decode(c, { stream: true });
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
      if (!line.startsWith('data:')) continue;
      const p = line.slice(5).trim(); if (p === '[DONE]') continue;
      try { const j = JSON.parse(p); const d = j.choices?.[0]?.delta;
        if (d?.content || d?.reasoning_content) { if (first === null) first = Date.now(); last = Date.now(); }
        if (j.usage) usage = j.usage;
      } catch {}
    }
  }
  const gen = (last - first) / 1000;
  const out = usage?.completion_tokens || 0;
  return { tier: tokens, promptTokens: usage?.prompt_tokens, out, genSecs: +gen.toFixed(2),
    tokPerSec: +(out / gen).toFixed(1), ttftMs: first - t0, totalSecs: +((Date.now() - t0) / 1000).toFixed(1) };
}
for (const t of tiers) {
  try { console.log(JSON.stringify(await run(t))); } catch (e) { console.log(JSON.stringify({ tier: t, err: String(e).slice(0, 80) })); }
}

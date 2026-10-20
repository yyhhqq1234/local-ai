const URL = 'http://127.0.0.1:1234/v1';
const PROMPT = process.argv[2] || '创建一个HTML，内容是SVG绘制一个鹈鹕骑自行车的2D动画。只输出完整HTML代码，不要解释。';
async function once(label) {
  const t0 = Date.now();
  const r = await fetch(URL + '/chat/completions', {
    method:'POST', headers:{'content-type':'application/json'},
    body: JSON.stringify({
      model: 'qwen3.8-27b-ablit-swift15-iq2s',
      messages: [{role:'user', content: PROMPT}],
      max_tokens: 8192, temperature: 0.6, stream: false
    })
  });
  const j = await r.json().catch(e=>({err:String(e)}));
  const msg = j.choices?.[0]?.message || {};
  const fin = j.choices?.[0]?.finish_reason;
  const reason = msg.reasoning_content || msg.reasoning || '';
  const text = msg.content || '';
  console.log(`[${label}] ${((Date.now()-t0)/1000).toFixed(1)}s finish=${fin} reasoning=${reason.length} text=${text.length} usage=${JSON.stringify(j.usage)}`);
  console.log('  text head:', JSON.stringify(text.slice(0,120)));
  console.log('  reason tail:', JSON.stringify(reason.slice(-160)));
  return {fin, rl: reason.length, tl: text.length};
}
await once('minimal-effort');

import fs from 'node:fs';
const label = process.argv[2] || 'run';
const PROMPT = '创建一个HTML，内容是SVG绘制一个鹈鹕骑自行车的2D动画。只输出完整HTML代码，不要解释。';
const t0 = Date.now();
const r = await fetch('http://127.0.0.1:1234/v1/chat/completions', {
  method:'POST', headers:{'content-type':'application/json'},
  body: JSON.stringify({model:'qwen3.8-27b-ablit-swift15-iq2s',messages:[{role:'user',content:PROMPT}],max_tokens:8192,temperature:0.6,stream:false})
});
const j = await r.json();
const msg = j.choices[0].message, fin = j.choices[0].finish_reason;
const reason = msg.reasoning_content||'', text = msg.content||'';
let html = text.replace(/^```[a-z]*\n/,'').replace(/\n```\s*$/,'');
fs.writeFileSync(`out-${label}.html`, html);
const m = {
  label, secs:+((Date.now()-t0)/1000).toFixed(1), finish:fin,
  reasoningTokens:j.usage?.completion_tokens_details?.reasoning_tokens ?? null,
  completionTokens:j.usage?.completion_tokens,
  reasoningChars:reason.length, htmlChars:html.length,
  svg:(html.match(/<svg/gi)||[]).length,
  keyframes:(html.match(/@keyframes/gi)||[]).length,
  smil:(html.match(/<(animate|animateTransform)/gi)||[]).length,
  paths:(html.match(/<path/gi)||[]).length,
  closed: /<\/html>\s*$/.test(html.trim()),
  hasStyle:(html.match(/<style/gi)||[]).length,
};
console.log(JSON.stringify(m));
fs.writeFileSync('metrics.jsonl', JSON.stringify(m)+'\n', {flag:'a'});

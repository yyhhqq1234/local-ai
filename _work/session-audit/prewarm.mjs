import fs from 'node:fs';
const prefix = fs.readFileSync('prefix.txt','utf8');
const t0 = Date.now();
const r = await fetch('http://127.0.0.1:1234/v1/chat/completions',{
  method:'POST', headers:{'content-type':'application/json'},
  body: JSON.stringify({model:'qwen3.8-27b-ablit-swift15-iq2s',
    messages:[{role:'system',content:prefix},{role:'user',content:'ok'}],
    max_tokens:1, temperature:0, stream:false})
});
const j = await r.json();
console.log(JSON.stringify({prewarmSecs:+((Date.now()-t0)/1000).toFixed(1),
  promptTokens:j.usage?.prompt_tokens, cached:j.usage?.prompt_tokens_details?.cached_tokens}));

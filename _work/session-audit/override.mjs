const URL='http://127.0.0.1:1234/v1/chat/completions';
async function run(effort, mt){
  const t0=Date.now();
  const body={model:'qwen3.8-27b-ablit-swift15-iq2s',
    messages:[{role:'user',content:'用一句话说明TCP三次握手的每一步。'}],
    max_tokens:mt, temperature:0.6, stream:false};
  if(effort) body.reasoning_effort = effort;
  const r=await fetch(URL,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  const m=j.choices[0].message, f=j.choices[0].finish_reason;
  console.log(`effort=${effort||'(引擎默认)'} max_tokens=${mt} ${((Date.now()-t0)/1000).toFixed(1)}s finish=${f} reasoningTokens=${j.usage?.completion_tokens_details?.reasoning_tokens} completion=${j.usage?.completion_tokens} textChars=${(m.content||'').length}`);
}
for (const e of [null,'none','minimal','low','high']) {
  try { await run(e, 1024); } catch(err) { console.log('effort='+e, 'ERR', String(err).slice(0,120)); }
}

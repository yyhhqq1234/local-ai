import fs from 'node:fs';
const label = process.argv[2]||'run';
const prefix = fs.readFileSync('prefix.txt','utf8');
const t0 = Date.now();
const r = await fetch('http://127.0.0.1:1234/v1/chat/completions', {
  method:'POST', headers:{'content-type':'application/json'},
  body: JSON.stringify({model:'qwen3.8-27b-ablit-swift15-iq2s',
    messages:[{role:'system',content:prefix},{role:'user',content:'以上是历史上下文。现在只回答两个字：收到'}],
    max_tokens:64, temperature:0, stream:true, stream_options:{include_usage:true}})
});
let firstByte=null, firstTok=null, text='', usage=null;
const dec=new TextDecoder(); let buf='';
for await (const chunk of r.body){
  if(firstByte===null) firstByte=Date.now()-t0;
  buf+=dec.decode(chunk,{stream:true});
  let i;
  while((i=buf.indexOf('\n'))>=0){
    const line=buf.slice(0,i).trim(); buf=buf.slice(i+1);
    if(!line.startsWith('data:')) continue;
    const p=line.slice(5).trim(); if(p==='[DONE]') continue;
    try{ const j=JSON.parse(p); const d=j.choices?.[0]?.delta;
      if(d?.content){ if(firstTok===null) firstTok=Date.now()-t0; text+=d.content; }
      if(j.usage) usage=j.usage;
    }catch{}
  }
}
console.log(JSON.stringify({label, firstByteMs:firstByte, ttftMs:firstTok, totalMs:Date.now()-t0,
  promptTokens:usage?.prompt_tokens, cached:usage?.prompt_tokens_details?.cached_tokens,
  outTokens:usage?.completion_tokens, text:text.slice(0,12)}));

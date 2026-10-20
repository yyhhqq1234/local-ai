import fs from 'node:fs';
const lines = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);

// header: tools + system size
const h = JSON.parse(lines[17]).data;
const hdr = h.header || {};
console.log('header keys:', Object.keys(hdr).join(','));
const tools = hdr.tools || h.tools || [];
console.log('tools count:', Array.isArray(tools)? tools.length : typeof tools);
if (Array.isArray(tools)) console.log('tool names sample:', tools.slice(0,15).map(t=>t.name||t.function?.name).join(' | '));
console.log('config:', JSON.stringify(hdr.config));

// per-turn stats
const turns = {};
for (const l of lines) {
  const o = JSON.parse(l);
  if (o.type === 'assistant/message') {
    const d = o.data;
    const m = d.message;
    const r = m.content.filter(b=>b.type==='reasoning').reduce((a,b)=>a+b.text.length,0);
    const t = m.content.filter(b=>b.type==='text').reduce((a,b)=>a+b.text.length,0);
    const tc = m.content.filter(b=>b.type==='tool-call'||b.type==='tool_use');
    turns[d.turn] ??= {r:0,t:0,tools:0,in:0,out:0,cache:0,msgs:0};
    const x = turns[d.turn];
    x.r += r; x.t += t; x.tools += tc.length; x.msgs++;
    x.in = d.usage?.inputTokens; x.out = d.usage?.outputTokens; x.cache = d.usage?.cacheReadTokens||0;
  }
}
console.log('\n--- per turn ---');
for (const [k,v] of Object.entries(turns)) console.log(`turn${k}: reasoningChars=${v.r} textChars=${v.t} toolCalls=${v.tools} inTok=${v.in} outTok=${v.out} cacheRead=${v.cache}`);
console.log('\ntotal tool-call blocks in session:', Object.values(turns).reduce((a,b)=>a+b.tools,0));
const toolMsgs = lines.map(l=>JSON.parse(l)).filter(o=>String(o.type).startsWith('tool/'));
console.log('tool/* records:', toolMsgs.length);

// reasoning redundancy probe on turn4
const a52 = JSON.parse(lines[52]).data.message.content.filter(b=>b.type==='reasoning').map(b=>b.text).join('\n');
const ls = a52.split('\n').map(s=>s.trim()).filter(s=>s.length>20);
const freq = new Map();
for (const ln of ls) freq.set(ln, (freq.get(ln)||0)+1);
const dup = [...freq.entries()].filter(([,c])=>c>1).sort((a,b)=>b[1]-a[1]).slice(0,10);
console.log('\nturn4 reasoning lines:', ls.length, 'dup lines:', dup.length);
for (const [ln,c] of dup) console.log(`  x${c} :: ${ln.slice(0,120)}`);
const restarts = (a52.match(/Let me (re|start over|restart|rewrite|try again)/gi)||[]).length;
const lets = (a52.match(/\bLet me\b/gi)||[]).length;
const actually = (a52.match(/\bActually\b/gi)||[]).length;
const wait = (a52.match(/\bWait\b/gi)||[]).length;
console.log(`turn4: "Let me"=${lets} restart-ish=${restarts} "Actually"=${actually} "Wait"=${wait}`);

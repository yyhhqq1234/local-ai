import fs from 'node:fs';
const L = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
const real = JSON.parse(L[17]).data.header.tools.map(t=>t.name||t.function?.name);
const ALLOW = ['write','read','edit','ops_bash','pwsh','ops_glob','ops_grep','ops_inspect_local_file','ops_replace','skill','todo_write','ask_user_question','present','subagent','subagent_fork','web_search','web_fetch','ninfer_status','ninfer_engine','ninfer_model','ninfer_params'];
const hit = ALLOW.filter(a=>real.includes(a));
const miss = ALLOW.filter(a=>!real.includes(a));
console.log('header tools:', real.length);
console.log('allow hit', hit.length, '/', ALLOW.length);
console.log('MISS:', miss.join(', ') || '(none)');
// 若全命中，算保留后的字节
const kept = JSON.parse(L[17]).data.header.tools.filter(t=>ALLOW.includes(t.name||t.function?.name));
console.log('kept bytes', JSON.stringify(kept).length, 'of', JSON.stringify(JSON.parse(L[17]).data.header.tools).length);

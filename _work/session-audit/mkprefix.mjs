import fs from 'node:fs';
const L = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
const sys = JSON.parse(L[10]).data.message.content.map(b=>b.text||'').join('\n');
const skillsMsg = JSON.parse(L[14]).data;
const skills = (skillsMsg.content||[]).map(b=>b.text||'').join('\n');
const tools = JSON.stringify(JSON.parse(L[17]).data.header.tools);
const prefix = [sys, skills, tools].join('\n\n');
fs.writeFileSync('prefix.txt', prefix);
console.log('chars', prefix.length, 'sys', sys.length, 'skills', skills.length, 'tools', tools.length);

import fs from 'node:fs';
const L = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
const tools = JSON.parse(L[17]).data.header.tools;
const g = {};
for (const t of tools) {
  const n = t.name || t.function?.name;
  const key = n.startsWith('mcp__godot-ai') ? 'godot-ai'
    : n.startsWith('mcp__js-reverse') ? 'js-reverse'
    : n.startsWith('kitty_') ? 'kitty'
    : n.startsWith('dev_') ? 'dev'
    : n.startsWith('agent_teams_') ? 'agent_teams'
    : n.startsWith('evolve_') ? 'evolve'
    : n.startsWith('reverse_') ? 'reverse'
    : n.startsWith('openpencil_') ? 'openpencil'
    : n.startsWith('mcp__ai-game-developer') ? 'ai-game-dev'
    : 'other';
  g[key] ??= { n: 0, b: 0 };
  g[key].n++; g[key].b += JSON.stringify(t).length;
}
const rows = Object.entries(g).sort((a,b)=>b[1].b-a[1].b);
let tot=0; for (const [,v] of rows) tot+=v.b;
console.log('total bytes', tot);
for (const [k,v] of rows) console.log(String(k).padEnd(14), String(v.n).padStart(3), 'tools', String(v.b).padStart(7), 'B', (v.b/tot*100).toFixed(1)+'%');

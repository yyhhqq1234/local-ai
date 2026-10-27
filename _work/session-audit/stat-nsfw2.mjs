import fs from 'node:fs';
const D = 'D:/BaiduNetdiskDownload/Local-AI/train/data/';
const rows = fs.readFileSync(D + 'nsfw.jsonl', 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));
const bySrc = new Map(), tpl = new Map(), lvl = new Map(), topic = new Map();
let short = 0, tiny = 0;
for (const r of rows) {
  const s = r.meta.__src; bySrc.set(s, (bySrc.get(s) || 0) + 1);
  lvl.set(r.meta.level, (lvl.get(r.meta.level) || 0) + 1);
  for (const t of r.meta.topic || []) topic.set(t, (topic.get(t) || 0) + 1);
  const p = r.messages[0].content.split('\n\n')[0];
  tpl.set(p, (tpl.get(p) || 0) + 1);
  if (r.meta.chars < 300) short++;
  if (r.meta.chars < 150) tiny++;
}
console.log('=== nsfw.jsonl 结构 ===');
console.log('源文件唯一数', bySrc.size, '| 每文件窗口数 top5:', [...bySrc.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, v]) => `${k.slice(-24)}=${v}`).join(' '));
console.log('窗口 <300字', short, `(${(short / rows.length * 100).toFixed(1)}%)`, '| <150字', tiny);
console.log('level', [...lvl.entries()].map(([k, v]) => `${k}:${v}`).join(' '));
console.log('topic top12', [...topic.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k, v]) => `${k}:${v}`).join(' '));
console.log('prompt 模板种类', tpl.size);
for (const [k, v] of [...tpl.entries()].sort((a, b) => b[1] - a[1])) console.log('  ', String(v).padStart(4), k);

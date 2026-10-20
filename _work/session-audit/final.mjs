import fs from 'node:fs';
const lines = fs.readFileSync('session.jsonl','utf8').split('\n').filter(Boolean);
const h = JSON.parse(lines[17]).data.header;
const names = h.tools.map(t=>t.name||t.function?.name);
console.log('write present:', names.includes('write'), '| edit:', names.includes('edit'), '| ops_bash:', names.includes('ops_bash'), '| pwsh:', names.includes('pwsh'));
console.log('file-ish tools:', names.filter(n=>/write|create|file|edit|bash|fs/i.test(n)).join(', '));
console.log('tools schema bytes:', JSON.stringify(h.tools).length);

const get = (i)=>JSON.parse(lines[i]).data.message.content;
for (const idx of [41,52]) {
  const r = get(idx).filter(b=>b.type==='reasoning').map(b=>b.text).join('');
  const fence = (r.match(/```/g)||[]).length;
  const svgLines = r.split('\n').filter(l=>/^\s*<(path|circle|rect|line|polygon|ellipse|g|svg|style|!--)/.test(l)).length;
  const mentionsWrite = (r.match(/\bwrite\b/gi)||[]).length;
  const mentionsCreate = (r.match(/\bcreate (?:a )?(?:new )?file/gi)||[]).length;
  console.log(`#${idx}: reasoningChars=${r.length} codeFences=${fence} svgLinesInline=${svgLines} "write"=${mentionsWrite} "create file"=${mentionsCreate}`);
}
// 是否出现 "no dedicated ... tool" 这类自我误导
const r41 = get(41).filter(b=>b.type==='reasoning').map(b=>b.text).join('');
const hits = [...r41.matchAll(/[^.]*\b(no|don't see|don't have|cannot find)\b[^.]*tool[^.]*\./gi)].map(m=>m[0].trim());
console.log('\nturn3 tool-blindness quotes:'); hits.slice(0,6).forEach(s=>console.log('  •', s.slice(0,200)));

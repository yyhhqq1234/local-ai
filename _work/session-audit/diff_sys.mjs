import fs from 'node:fs';
const L = fs.readFileSync('s7.jsonl','utf8').split('\n').filter(Boolean);
const sys = JSON.parse(L[8]).data.message.content.map(b=>b.text||'').join('\n');
const NL = String.fromCharCode(10);

// 按 [TAG]...[/TAG] 切块，剩余按 # 标题切
function blocks(text) {
  const out = [];
  const re = /\[([A-Za-z0-9:_. -]{3,80})\]([\s\S]*?)\[\/\1\]/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ tag: '(无标签)', body: text.slice(last, m.index) });
    out.push({ tag: m[1], body: m[2] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ tag: '(无标签)', body: text.slice(last) });
  return out;
}

const bs = blocks(sys).filter(b => b.body.trim().length > 100);
console.log('=== 块清单 ===');
bs.forEach((b,i)=>console.log(i, JSON.stringify(b.tag), b.body.length, '字符'));

// 小节切分
function sections(body) {
  const lines = body.split(NL);
  const secs = []; let cur = { head: '(前言)', body: [] };
  for (const l of lines) {
    if (/^#{1,3} /.test(l)) { secs.push(cur); cur = { head: l.trim(), body: [] }; }
    else cur.body.push(l);
  }
  secs.push(cur);
  return secs.map(s => ({ head: s.head, text: s.body.join(NL).replace(/\s+/g,' ').trim() }));
}

bs.forEach((b,i)=>{
  const secs = sections(b.body);
  console.log(NL + '--- 块 ' + i + ' [' + b.tag + '] 小节 ' + secs.length + ' 个 ---');
  secs.forEach(s => console.log('  *', s.head, '|', s.text.length, '字符 |', s.text.slice(0, 60)));
});

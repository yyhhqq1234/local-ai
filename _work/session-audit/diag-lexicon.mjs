// 诊断 lexicon v8 结构问题（只读）
import fs from 'node:fs';
const v = JSON.parse(fs.readFileSync('D:/BaiduNetdiskDownload/Local-AI/train/data/nsfw/nsfw-lexicon-v8.json', 'utf8'));
const cats = Object.keys(v).filter(k => !k.startsWith('__'));
const keys = {}, fieldMiss = {};
let synStr = 0, synArr = 0, exDup = 0, exTot = 0, crossN = 0, varN = 0, glossN = 0, bothEx = 0;
const freq0 = [], noDesc = [], descEmpty = [];
const synFormats = new Set();
for (const c of cats) {
  if (!v[c].desc || !String(v[c].desc).trim()) noDesc.push(c);
  for (const [t, i] of Object.entries(v[c].terms || {})) {
    for (const k of Object.keys(i)) keys[k] = (keys[k] || 0) + 1;
    for (const k of ['meaning', 'synonym', 'writing_tip', 'freq', 'context_examples']) if (!(k in i)) fieldMiss[k] = (fieldMiss[k] || 0) + 1;
    if (i.synonym !== undefined) { typeof i.synonym === 'string' ? synStr++ : synArr++; synFormats.add(typeof i.synonym === 'string' ? i.synonym : 'array'); }
    if (i.cross_ref) crossN++;
    if (i.variants) varN++;
    if (i.glossary) glossN++;
    if (i.freq === 0 || i.freq === undefined) freq0.push(c + ':' + t);
    const a = new Set(i.context_examples || []);
    const b = i.glossary?.examples || [];
    exTot++;
    if (a.size && b.length) bothEx++;
    if (b.length && b.every(x => a.has(x))) exDup++;
  }
}
console.log('类数:', cats.length);
console.log('字段出现次数:', JSON.stringify(keys));
console.log('字段缺失:', JSON.stringify(fieldMiss));
console.log('synonym 字符串/数组:', synStr, '/', synArr, '| 分隔符样例:', [...synFormats].filter(x => x !== 'array').slice(0, 6));
console.log('cross_ref:', crossN, '| variants:', varN, '| glossary:', glossN);
console.log('两处例句都有的词条:', bothEx, '/', exTot, '| glossary 例句完全被 context_examples 覆盖:', exDup);
console.log('freq=0/缺失:', freq0.length, freq0.join(' '));
console.log('无 desc 类:', noDesc.length ? noDesc.join(',') : '无');
console.log('顶层键顺序:', Object.keys(v).join(' '));
console.log('\n各类 term 数:', JSON.stringify(Object.fromEntries(cats.map(c => [c, Object.keys(v[c].terms || {}).length]))));

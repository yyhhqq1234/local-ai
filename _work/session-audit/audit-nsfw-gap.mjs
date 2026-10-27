import fs from 'node:fs';
const D = 'D:/BaiduNetdiskDownload/Local-AI/train/data/';
const rows = fs.readFileSync(D + 'nsfw-index/index.jsonl', 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));
const isLow = r => (r.topic || []).some(t => t[0] === '低龄向');
const low = rows.filter(isLow), ok = rows.filter(r => !isLow(r));
const sum = a => a.reduce((s, r) => s + (r.chars || 0), 0);
console.log('=== 文件级剔除账 ===');
console.log(`总 ${rows.length} 份 / ${sum(rows).toLocaleString()} 字`);
console.log(`低龄向(剔除) ${low.length} 份 / ${sum(low).toLocaleString()} 字  (${(sum(low) / sum(rows) * 100).toFixed(1)}%)`);
console.log(`可切(保留)   ${ok.length} 份 / ${sum(ok).toLocaleString()} 字  (${(sum(ok) / sum(rows) * 100).toFixed(1)}%)`);

console.log('\n=== 被剔除的 37 份：低龄向命中率分档 ===');
const band = { '>=20%(强)': [], '10-20%(中)': [], '<10%(弱/疑似误判)': [] };
for (const r of low) {
  const p = +((r.topic || []).find(t => t[0] === '低龄向') || [0, 0])[1];
  const key = p >= 20 ? '>=20%(强)' : p >= 10 ? '10-20%(中)' : '<10%(弱/疑似误判)';
  band[key].push({ rel: r.rel.slice(-58), chars: r.chars, p, lvl: r.level, ex: r.explicit_per_kchar });
}
for (const [k, arr] of Object.entries(band)) {
  console.log(`\n-- ${k}: ${arr.length} 份 / ${arr.reduce((s, x) => s + x.chars, 0).toLocaleString()} 字`);
  for (const x of arr.sort((a, b) => b.chars - a.chars)) console.log(`   ${String(x.chars).padStart(8)} 低龄向${String(x.p).padStart(5)}% ${x.lvl}  ${x.rel}`);
}

console.log('\n=== 保留的 25 份（已切）低龄向占比 ===');
for (const r of ok.sort((a, b) => b.chars - a.chars)) {
  const p = +((r.topic || []).find(t => t[0] === '低龄向') || [0, 0])[1] || 0;
  console.log(`   ${String(r.chars).padStart(8)} 低龄向${String(p).padStart(5)}% ${r.level}  ${r.rel.slice(-50)}`);
}

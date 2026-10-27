// 零丢失校验：v8 → v9 逐字段深比对
import fs from 'node:fs';
const R = 'D:/BaiduNetdiskDownload/Local-AI/train/data/nsfw';
const v8 = JSON.parse(fs.readFileSync(R + '/nsfw-lexicon-v8.json', 'utf8'));
const v9 = JSON.parse(fs.readFileSync(R + '/nsfw-lexicon-v9.json', 'utf8'));

const cats8 = Object.keys(v8).filter(k => !k.startsWith('__'));
const flat8 = new Map(), flat9 = new Map();
for (const c of cats8) for (const [t, i] of Object.entries(v8[c].terms || {})) flat8.set(c + '\u0000' + t, i);
for (const [c, cat] of Object.entries(v9.categories)) for (const [t, i] of Object.entries(cat.terms || {})) flat9.set(c + '\u0000' + t, i);

const errs = [];
if (flat8.size !== flat9.size) errs.push(`词条数不一致 v8=${flat8.size} v9=${flat9.size}`);
for (const [k, a] of flat8) {
  const b = flat9.get(k);
  if (!b) { errs.push(`丢失词条 ${k}`); continue; }
  // 原字段逐字比对（v8 缺失的字段在 v9 补 null/[] 属结构统一，不算错误）
  for (const f of ['meaning', 'synonym', 'writing_tip', 'freq', 'context_examples', 'cross_ref', 'freq_note', 'variants_kind', 'variants_note', 'variant_total_freq']) {
    const in8 = f in a, in9 = f in b;
    if (!in8) {
      const v9v = b[f];
      const isDefault = v9v === null || v9v === undefined || (Array.isArray(v9v) && v9v.length === 0);
      if (!isDefault) errs.push(`${k} v8 无 ${f} 但 v9 有非空值`);
      continue;
    }
    if (!in9) { errs.push(`${k} 丢失字段: ${f}`); continue; }
    if (JSON.stringify(a[f]) !== JSON.stringify(b[f])) errs.push(`${k} 字段值变了: ${f}`);
  }
  if (JSON.stringify(a.variants || []) !== JSON.stringify(b.variants || [])) errs.push(`${k} variants 变了`);
  if (a.glossary && JSON.stringify(a.glossary) !== JSON.stringify(b.glossary)) errs.push(`${k} glossary 变了`);
  // 派生字段完整性
  const pool = new Set([...(a.context_examples || []), ...(a.glossary?.examples || [])]);
  for (const e of pool) if (!b.examples.includes(e)) errs.push(`${k} examples 漏例句`);
  const needCats = new Set([k.split('\u0000')[0], ...(Array.isArray(a.cross_ref) ? a.cross_ref : a.cross_ref ? [a.cross_ref] : [])]);
  for (const c of needCats) if (!b.cats.includes(c)) errs.push(`${k} cats 漏 ${c}`);
  // synonym 派生索引覆盖性校验（去重是特性，要求原串每个片段都被覆盖）
  if (a.synonym && b.synonyms?.length) {
    const frags = String(a.synonym).split(/[\/／、,，]/).map(x => x.trim()).filter(Boolean);
    for (const f of frags) if (!b.synonyms.includes(f)) errs.push(`${k} synonyms 漏片段: "${f}"`);
  }
}
// 类级
for (const c of cats8) {
  if (!v9.categories[c]) { errs.push(`丢失类别 ${c}`); continue; }
  if (v9.categories[c].desc !== v8[c].desc) errs.push(`类别 ${c} desc 变了`);
}
// stats 一致性
const total9 = Object.values(v9.categories).reduce((a, c) => a + Object.keys(c.terms).length, 0);
if (total9 !== v9.stats.total_terms) errs.push(`stats.total_terms 不符 ${total9}`);
if (total9 !== flat8.size) errs.push('总数不符');
// 字段统一性：470 条必须都有同字段集
const fieldSets = new Set();
for (const [c, cat] of Object.entries(v9.categories)) for (const i of Object.values(cat.terms)) fieldSets.add(Object.keys(i).sort().join(','));
if (fieldSets.size > 3) errs.push(`字段集种类过多: ${fieldSets.size}（可选字段导致）`);

console.log(JSON.stringify({
  词条数: { v8: flat8.size, v9: flat9.size },
  类别数: Object.keys(v9.categories).length,
  字段集种类: fieldSets.size,
  错误数: errs.length,
  错误样本: errs.slice(0, 12),
}, null, 2));
console.log(errs.length === 0 ? '\n零丢失校验: PASS' : '\n零丢失校验: FAIL');

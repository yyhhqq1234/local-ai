// lexicon v8 → v9：结构优化（分层 + 字段统一 + 归一索引），原字段值逐字保留，零丢失
import fs from 'node:fs';

const ROOT = 'D:/BaiduNetdiskDownload/Local-AI/train/data/nsfw';
const v8 = JSON.parse(fs.readFileSync(ROOT + '/nsfw-lexicon-v8.json', 'utf8'));

// 语义顺序（原 v8 的 descriptor 排在 relationship 之后，此处归位）
const ORDER = ['body', 'action', 'state', 'emotion', 'position', 'descriptor',
  'relationship', 'identity', 'personality', 'genre', 'onomatopoeia', 'vocalization'];
const catsInV8 = Object.keys(v8).filter(k => !k.startsWith('__'));
const ordered = [...ORDER.filter(c => catsInV8.includes(c)), ...catsInV8.filter(c => !ORDER.includes(c))];

const splitSyn = (s) => {
  if (typeof s !== 'string' || !s.trim()) return [];
  return [...new Set(s.split(/[\/／、,，]/).map(x => x.trim()).filter(Boolean))];
};

const categories = {};
const stats = {
  total_terms: 0, categories: ordered.length,
  with_glossary: 0, with_variants: 0, variants_absorbed: 0,
  with_cross_ref: 0, freq_zero: 0, no_examples: 0, no_meaning: 0,
  examples_total: 0, by_cat: {},
};
const freqZeroList = [];
const variantFamilies = [];

for (const c of ordered) {
  const src = v8[c];
  const terms = {};
  for (const [term, i] of Object.entries(src.terms || {})) {
    // ── 归一索引（新增，不动原字段）──
    const synonyms = splitSyn(i.synonym);
    const exPool = [];
    const pushEx = (x) => { if (x && !exPool.includes(x)) exPool.push(x); };
    for (const e of i.context_examples || []) pushEx(e);
    for (const e of i.glossary?.examples || []) pushEx(e);
    const cats = Array.isArray(i.cross_ref) ? [...new Set([c, ...i.cross_ref])]
      : i.cross_ref ? [...new Set([c, i.cross_ref])] : [c];
    const variants = i.variants || [];
    const variantFreq = variants.reduce((a, x) => a + (x.freq || 0), 0);
    const totalFreq = (i.freq || 0) + variantFreq;

    const flags = [];
    if (!i.freq) { flags.push('freq_zero'); freqZeroList.push(`${c}:${term}`); }
    if (!exPool.length) flags.push('no_examples');
    if (!String(i.meaning || '').trim()) flags.push('no_meaning');
    if (i.cross_ref) flags.push('cross_ref');
    if (variants.length) flags.push('has_variants');

    const sources = [];
    if (i.glossary) sources.push('glossary');
    if (i.freq_note) sources.push('glossary_freq_estimated');
    if (!sources.length) sources.push('v6_legacy');

    terms[term] = {
      // ── 归一索引（新增）──
      freq: i.freq,
      total_freq: totalFreq,
      synonyms,
      cats,
      examples: exPool,
      sources,
      flags,
      // ── 原字段（逐字保留；统一字段集，缺失补 null/[]）──
      meaning: i.meaning ?? null,
      synonym: i.synonym ?? null,
      writing_tip: i.writing_tip ?? null,
      context_examples: i.context_examples ?? [],
      cross_ref: i.cross_ref ?? null,
      freq_note: i.freq_note ?? null,
      glossary: i.glossary ?? null,
      variants,
      variants_kind: i.variants_kind ?? null,
      variants_note: i.variants_note ?? null,
      variant_total_freq: i.variant_total_freq ?? null,
    };

    stats.total_terms++;
    stats.examples_total += exPool.length;
    if (i.glossary) stats.with_glossary++;
    if (variants.length) { stats.with_variants++; stats.variants_absorbed += variants.length; }
    if (i.cross_ref) stats.with_cross_ref++;
    if (!i.freq) stats.freq_zero++;
    if (!exPool.length) stats.no_examples++;
    if (!String(i.meaning || '').trim()) stats.no_meaning++;
    if (variants.length) variantFamilies.push({ root: term, cat: c, kind: i.variants_kind, absorbed: variants.length });
  }
  categories[c] = { id: c, desc: src.desc ?? '', term_count: Object.keys(terms).length, terms };
  stats.by_cat[c] = Object.keys(terms).length;
}

const v9 = {
  schema: {
    version: 'v9',
    built: new Date().toISOString(),
    upgraded_from: 'v8',
    policy: '结构优化：分层（schema/stats/categories）+ 字段统一 + 归一索引；原字段值逐字保留，零内容丢失',
    structure: {
      'schema': '本段：版本、字段契约、类别顺序',
      'stats': '全局统计',
      'categories.<id>.terms.<词>': '词条；freq/total_freq/synonyms/cats/examples/sources/flags 为归一索引，meaning/synonym/writing_tip/context_examples/glossary/variants 为原字段',
    },
    field_contract: {
      freq: 'int，语料出现次数（原字段）',
      total_freq: 'int，freq + 全部变体 freq（派生）',
      synonyms: 'string[]，由 synonym 按 / ／ 、 , 拆分去重（派生）',
      cats: 'string[]，主类 + cross_ref（派生；单类词仅含自身）',
      examples: 'string[]，context_examples ∪ glossary.examples 去重保序（派生）',
      sources: 'string[]，词条来源：glossary | glossary_freq_estimated | v6_legacy',
      flags: 'string[]，freq_zero | no_examples | no_meaning | cross_ref | has_variants',
      meaning: 'string，释义（原字段）',
      synonym: 'string，同义词原串（原字段，保真）',
      writing_tip: 'string，写作提示（原字段）',
      context_examples: 'string[]，v6 时期上下文例句原文（原字段）',
      cross_ref: 'string|string[]，原跨类标注（原字段）',
      glossary: 'object，glossary 合并表对应条目（原字段：cat/cats/meaning/synonym/freq_text/writing_tip/examples/sources/versions）',
      variants: 'object[]，已归并的同根变体（term/freq/meaning/synonyms/glossary_versions）',
    },
    category_order: ordered,
  },
  stats,
  categories,
};

fs.writeFileSync(ROOT + '/nsfw-lexicon-v9.json', JSON.stringify(v9, null, 2), 'utf8');
console.log(JSON.stringify({ stats, variant_families: variantFamilies.length, freq_zero_list: freqZeroList }, null, 2));

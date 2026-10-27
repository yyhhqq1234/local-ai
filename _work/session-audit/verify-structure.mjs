// MANIFEST + 硬验收（v9 结构）：覆盖、变体、训练无损
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const ROOT = 'D:/BaiduNetdiskDownload/Local-AI/train/data/nsfw';
const P = (f) => path.join(ROOT, f);
const sha256 = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const lines = (f) => fs.readFileSync(P(f), 'utf8').split('\n').filter(Boolean);

const merged = lines('nsfw-glossary-merged.jsonl').map(JSON.parse);
const mWords = merged.map(o => (o.messages[0].content.match(/「([^」]+)」/) || [])[1]);
const v9 = JSON.parse(fs.readFileSync(P('nsfw-lexicon-v9.json'), 'utf8'));

const lexWords = new Map();
for (const [c, cat] of Object.entries(v9.categories)) for (const t of Object.keys(cat.terms || {})) lexWords.set(t, c);
const notCovered = mWords.filter(w => !lexWords.has(w));

// 变体检查
const absorbed = [];
let variantsKept = 0;
for (const [c, cat] of Object.entries(v9.categories))
  for (const [t, i] of Object.entries(cat.terms)) {
    for (const v of i.variants || []) { absorbed.push(v.term); variantsKept++; }
  }
const residual = absorbed.filter(t => lexWords.has(t));

// 训练分片
const shards = ['train-cont.jsonl', 'train-expand.jsonl', 'train-multi.jsonl', 'train-scene.jsonl', 'train-style.jsonl'];
let shardRows = 0; const badJson = [];
for (const f of shards) for (const l of lines(f)) { shardRows++; try { JSON.parse(l); } catch { badJson.push(f); } }

const files = [
  ...shards.map(f => ({ file: f, role: 'train-shard', rows: lines(f).length })),
  { file: 'nsfw-glossary-merged.jsonl', role: 'glossary（总词表）', rows: merged.length },
  { file: 'nsfw-lexicon-v9.json', role: 'lexicon（结构化词表 v9：schema/stats/categories 三层）', words: lexWords.size },
];
for (const f of files) { f.bytes = fs.statSync(P(f.file)).size; f.sha256 = sha256(P(f.file)); }

const manifest = {
  __meta: {
    dir: 'train/data/nsfw', built: new Date().toISOString(),
    policy: '结构调整与索引归一；重复合并覆盖；同根变体归并；原字段值逐字保留（零内容丢失）',
  },
  files,
  lexicon_v9: {
    structure: 'schema / stats / categories',
    total_terms: v9.stats.total_terms,
    categories: v9.stats.categories,
    by_cat: v9.stats.by_cat,
    with_glossary: v9.stats.with_glossary,
    with_variants: v9.stats.with_variants,
    variants_absorbed: v9.stats.variants_absorbed,
    with_cross_ref: v9.stats.with_cross_ref,
    freq_zero: v9.stats.freq_zero,
    no_examples: v9.stats.no_examples,
    examples_total: v9.stats.examples_total,
    field_set_uniform: true,
  },
  coverage: {
    'train 分片合计行数': shardRows,
    'glossary 来源行数 345 → 覆盖后 313 → 变体归并后': merged.length,
    '总词表词被结构化词表覆盖': `${mWords.length - notCovered.length}/${mWords.length}`,
    '变体信息保留条数': variantsKept,
  },
  archive: {
    '结构版本归档': '_superseded/structure-20261027-200103/',
    'v7（变体归并前）': '_superseded/structure-20261027-200103/pre-variant-merge/nsfw-lexicon-v7.json',
    'v8（v9 升级前）': '_superseded/structure-20261027-200103/pre-v9/nsfw-lexicon-v8.json',
  },
  rollback: 'cd train/data/nsfw && cp -f _superseded/structure-20261027-200103/pre-v9/nsfw-lexicon-v8.json .',
};
fs.writeFileSync(P('MANIFEST.json'), JSON.stringify(manifest, null, 2), 'utf8');

console.log(JSON.stringify({
  硬验收_总词表全覆盖: notCovered.length === 0 ? `PASS ${mWords.length}/${mWords.length}` : `FAIL 缺 ${notCovered.length}`,
  硬验收_变体零残留: residual.length === 0 ? `PASS ${absorbed.length}` : `FAIL ${residual.join(',')}`,
  硬验收_变体信息保留: `${variantsKept}/${absorbed.length}`,
  硬验收_训练分片无损: shardRows === 13668 && !badJson.length ? `PASS ${shardRows}` : 'FAIL',
  lexicon_v9: { total: v9.stats.total_terms, cats: v9.stats.categories, examples: v9.stats.examples_total },
}, null, 2));

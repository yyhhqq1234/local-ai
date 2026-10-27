// 更新保留文件：coverage 改名+对齐数据集 / index 补当前主题体系 / triage 补标签映射 / MANIFEST 重写
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const ROOT = 'D:/BaiduNetdiskDownload/Local-AI/train/data/nsfw';
const P = (f) => path.join(ROOT, f);
const sha256 = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const lines = (f) => fs.readFileSync(P(f), 'utf8').split('\n').filter(Boolean);
const NOW = new Date().toISOString();

const SHARDS = ['train-cont.jsonl', 'train-scene.jsonl', 'train-multi.jsonl', 'train-style.jsonl', 'train-expand.jsonl'];
const shardInfo = SHARDS.map(f => ({ file: f, rows: lines(f).length, bytes: fs.statSync(P(f)).size, sha256: sha256(P(f)) }));
const totalRows = shardInfo.reduce((a, s) => a + s.rows, 0);

const v9 = JSON.parse(fs.readFileSync(P('nsfw-lexicon-v9.json'), 'utf8'));
const glos = lines('nsfw-glossary-merged.jsonl').length;

const dataset = {
  train_shards: shardInfo,
  train_rows_total: totalRows,
  glossary_terms: glos,
  lexicon_terms: v9.stats.total_terms,
  lexicon_categories: v9.stats.categories,
  lexicon_version: v9.schema.version,
};

// ── 1. coverage：nsfw-v3-coverage.json → nsfw-coverage.json（内容全保留 + 对齐当前数据集）──
const oldCov = JSON.parse(fs.readFileSync(P('nsfw-v3-coverage.json'), 'utf8'));
const cov = {
  __meta: {
    version: 'coverage-v2', built: NOW,
    upgraded_from: 'nsfw-v3-coverage.json',
    note: '原统计字段全部保留；新增 __meta.dataset 对齐当前 train-*.jsonl 数据集（不再指涉 nsfw-v3.jsonl 单一文件）',
    dataset,
  },
  ...oldCov,
};
fs.writeFileSync(P('nsfw-coverage.json'), JSON.stringify(cov, null, 2), 'utf8');
fs.unlinkSync(P('nsfw-v3-coverage.json'));

// ── 2. index：补当前主题体系与数据集指针（原字段不动）──
const idxDir = P('nsfw-index');
const facets = JSON.parse(fs.readFileSync(path.join(idxDir, 'facets.json'), 'utf8'));
const TOPICS = ['露出', '调教', '近亲', '束缚', '婚恋', '催眠', '低龄向', '后宫', 'NTR', '异世界', '同人', '非人', '百合', '虚拟游戏'];
const facets2 = {
  __meta: {
    built: NOW,
    note: '原 facets 统计保留；新增 topic_system（当前 14 类主题）与 dataset 指针',
    topic_system: TOPICS,
    dataset,
  },
  ...facets,
};
fs.writeFileSync(path.join(idxDir, 'facets.json'), JSON.stringify(facets2, null, 2), 'utf8');

// ── 3. triage：旧标签 → 当前主题体系映射（原字段不动）──
const triDir = P('nsfw-triage');
const summary = JSON.parse(fs.readFileSync(path.join(triDir, 'summary.json'), 'utf8'));
const TAG_MAP = {
  '乱伦': '近亲', '幼齿': '低龄向', 'SM': '束缚', '女同': '百合',
  '兽人': '非人', 'VR/游戏': '虚拟游戏', '露出': '露出', '调教': '调教',
  '催眠': '催眠', '婚恋': '婚恋', '同人': '同人', '后宫': '后宫', 'NTR': 'NTR', '异世界': '异世界',
};
const mapped = (summary.tag_dist || []).map(([tag, n]) => ({ old_tag: tag, count: n, current_topic: TAG_MAP[tag] || null }));
const summary2 = {
  __meta: {
    built: NOW,
    note: '原 tag_dist 为旧标签体系；新增 tag_mapping 映射到当前 14 类主题，未破坏原字段',
    topic_system: TOPICS,
    tag_mapping: mapped,
    unmapped_tags: mapped.filter(x => !x.current_topic).map(x => x.old_tag),
    dataset,
  },
  ...summary,
};
fs.writeFileSync(path.join(triDir, 'summary.json'), JSON.stringify(summary2, null, 2), 'utf8');

// ── 4. MANIFEST 重写 ──
const manifest = {
  __meta: {
    dir: 'train/data/nsfw', built: NOW,
    state: '清理后（过时版本与备份已删除，删除台账见 CLEANUP-REPORT.md）',
    policy: '活跃数据：train 分片 / 总词表 / 结构化词表 / 索引与报告；历史版本已清出',
  },
  dataset,
  files: [
    ...shardInfo.map(s => ({ ...s, role: '训练分片（按 meta.stype 拆分）' })),
    { file: 'nsfw-glossary-merged.jsonl', role: '总词表（345 行 → 合并覆盖 313 → 变体归并 283）', rows: glos, bytes: fs.statSync(P('nsfw-glossary-merged.jsonl')).size, sha256: sha256(P('nsfw-glossary-merged.jsonl')) },
    { file: 'nsfw-lexicon-v9.json', role: '结构化词表 v9（schema/stats/categories）', words: v9.stats.total_terms, bytes: fs.statSync(P('nsfw-lexicon-v9.json')).size, sha256: sha256(P('nsfw-lexicon-v9.json')) },
    { file: 'nsfw-coverage.json', role: '覆盖报告（原 nsfw-v3-coverage.json 更新）', bytes: fs.statSync(P('nsfw-coverage.json')).size, sha256: sha256(P('nsfw-coverage.json')) },
    { file: 'nsfw-index/', role: '源语料索引（62 文件；facets 已补 topic_system）' },
    { file: 'nsfw-triage/', role: '源语料初筛（summary 已补 tag_mapping）' },
    { file: 'CLEANUP-REPORT.md', role: '清理台账（18 个被删文件的路径/大小/sha256/理由）' },
  ],
  lexicon_v9: {
    total_terms: v9.stats.total_terms, categories: v9.stats.categories, by_cat: v9.stats.by_cat,
    with_glossary: v9.stats.with_glossary, with_variants: v9.stats.with_variants,
    variants_absorbed: v9.stats.variants_absorbed, freq_zero: v9.stats.freq_zero,
    examples_total: v9.stats.examples_total,
  },
  cleanup: {
    removed_files: 18,
    removed_MB: 712.5,
    ledger: 'CLEANUP-REPORT.md',
    scope: ['_superseded/', '_re-strip-backup-20261027115222/'],
  },
};
fs.writeFileSync(P('MANIFEST.json'), JSON.stringify(manifest, null, 2), 'utf8');

console.log(JSON.stringify({
  coverage: 'nsfw-coverage.json（原 v3-coverage 已并入并删除旧名）',
  index: 'facets.json 补 topic_system',
  triage: `tag_mapping ${mapped.length} 项，未映射 ${mapped.filter(x => !x.current_topic).length}`,
  dataset: { rows: totalRows, shards: SHARDS.length, glossary: glos, lexicon: v9.stats.total_terms },
}, null, 2));

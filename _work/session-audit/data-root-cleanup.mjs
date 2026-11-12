// train/data 根目录清理 + 统一 MANIFEST（继承旧 final-manifest 的训练配比）
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const D = 'D:/BaiduNetdiskDownload/Local-AI/train/data';
const P = (f) => path.join(D, f);
const sha256 = (p) => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const lines = (f) => fs.readFileSync(P(f), 'utf8').split('\n').filter(Boolean);
const NOW = new Date().toISOString();

// ── 1. 继承旧 final-manifest 的训练配比（删除前取值）──
const oldMf = JSON.parse(fs.readFileSync(P('final-manifest.json'), 'utf8'));
const trainParams = {
  re_weight: oldMf.re_weight,
  replay: oldMf.replay,
  seed: oldMf.seed,
  silver_n: oldMf.silver_n,
  note: '由旧 final-manifest.json 继承（该文件描述的是 re 混入 NSFW 的旧形态，已过时）',
};

// ── 2. 删除过时产物（脚本可重生成 / 描述旧形态）──
const DROP = [
  ['dedupe-report.json', 'dedupe_re.py 的产物，针对已重构前的 final-re 去重，脚本可重跑生成'],
  ['refine-report.json', 'refine_re.py 的产物，针对已重构前的 final-re 精炼，脚本可重跑生成'],
  ['final-manifest.json', '描述旧形态（final_re 1608 / final_nsfw 15276 含 re）；配比参数已继承至 MANIFEST.json'],
];
const ledger = [];
for (const [rel, reason] of DROP) {
  const p = P(rel);
  if (!fs.existsSync(p)) continue;
  ledger.push({ rel, bytes: fs.statSync(p).size, sha256: sha256(p), reason });
  fs.unlinkSync(p);
}

// ── 3. 数据总览 ──
const NSFW = 'nsfw', KITTY = 'kitty-reverse';
const nsfwShards = ['train-cont.jsonl', 'train-scene.jsonl', 'train-multi.jsonl', 'train-style.jsonl', 'train-expand.jsonl']
  .map(f => ({ file: `${NSFW}/${f}`, rows: lines(`${NSFW}/${f}`).length, bytes: fs.statSync(P(`${NSFW}/${f}`)).size, sha256: sha256(P(`${NSFW}/${f}`)) }));
const nsfwRows = nsfwShards.reduce((a, s) => a + s.rows, 0);
const kittyRows = lines(`${KITTY}/train-kitty-core.jsonl`).length;

// versions 快照索引
const versions = fs.readdirSync(P('versions')).filter(f => !f.endsWith('.sha256')).sort().map(f => {
  const p = P(`versions/${f}`);
  const shaFile = p + '.sha256';
  return {
    file: `versions/${f}`, bytes: fs.statSync(p).size,
    sha256: fs.existsSync(shaFile) ? fs.readFileSync(shaFile, 'utf8').trim() : sha256(p),
    generation: /\.20261027-203028\./.test(f) ? 'current(20261027-203028)' : 'history',
  };
});

const manifest = {
  __meta: {
    dir: 'train/data', built: NOW,
    state: '根目录已清理；两条训练线数据在 nsfw/ 与 kitty-reverse/，历史版本在 versions/',
    policy: 'TRAINING-LINEAGE.md 铁律①：数据集必须打快照（versions/ 内 名称.时间戳.jsonl + .sha256）',
  },
  training_lines: {
    nsfw: {
      dir: `${NSFW}/`, rows: nsfwRows, shards: nsfwShards,
      glossary: { file: `${NSFW}/nsfw-glossary-merged.jsonl`, rows: lines(`${NSFW}/nsfw-glossary-merged.jsonl`).length },
      lexicon: { file: `${NSFW}/nsfw-lexicon-v9.json`, terms: JSON.parse(fs.readFileSync(P(`${NSFW}/nsfw-lexicon-v9.json`), 'utf8')).stats.total_terms },
      manifest: `${NSFW}/MANIFEST.json`,
    },
    kitty_reverse: {
      dir: `${KITTY}/`, rows: kittyRows,
      core: { file: `${KITTY}/train-kitty-core.jsonl`, bytes: fs.statSync(P(`${KITTY}/train-kitty-core.jsonl`)).size, sha256: sha256(P(`${KITTY}/train-kitty-core.jsonl`)) },
      manifest: `${KITTY}/KITTY-MANIFEST.json`,
    },
    total_rows: nsfwRows + kittyRows,
  },
  train_params: trainParams,
  snapshots: { count: versions.length, current: versions.filter(v => v.generation.startsWith('current')).length, items: versions },
  retained: [
    { file: 'train.example.jsonl', role: '数据格式冒烟样例（3 条，_research/微调能力-备案-20261020/04-RUNBOOK.md 引用）', rows: lines('train.example.jsonl').length },
    { dir: 'versions/', role: '数据集快照锚点（TRAINING-LINEAGE.md 铁律①），旧快照保留、本代已补齐' },
  ],
  cleanup: { removed_files: ledger.length, ledger },
};
fs.writeFileSync(P('MANIFEST.json'), JSON.stringify(manifest, null, 2), 'utf8');

// ── 4. 台账 ──
const md = [];
md.push('# train/data 根目录清理台账');
md.push('');
md.push(`- 生成时间: ${NOW}`);
md.push(`- 范围: train/data/ 根（不含 nsfw/ 与 kitty-reverse/）`);
md.push('');
md.push('## 删除');
md.push('| 文件 | 字节 | sha256(前16) | 理由 |');
md.push('|---|---|---|---|');
for (const r of ledger) md.push(`| ${r.rel} | ${r.bytes} | ${r.sha256.slice(0, 16)} | ${r.reason} |`);
md.push('');
md.push('## 保留并更新');
md.push(`| 项 | 处理 |`);
md.push(`|---|---|`);
md.push(`| \`versions/\` | 保留 4 份历史快照（final-joint / final-nsfw / final-re / mix-re，10-27 01:18~02:27）；**新增本代 8 份快照**（时间戳 20261027-203028）：nsfw 5 分片 + glossary-merged + lexicon-v9 + kitty-core，各配 .sha256 |`);
md.push(`| \`train.example.jsonl\` | 保留（RUNBOOK 引用的格式冒烟样例，3 条） |`);
md.push(`| \`MANIFEST.json\` | **新建**：两条训练线总览 + 训练配比（re_weight/replay/seed，继承旧 final-manifest）+ 快照索引 + 清理台账 |`);
md.push('');
md.push('## 依据');
md.push('```');
md.push('train/TRAINING-LINEAGE.md 铁律①：数据必须打快照 train/lines/27b-kittyrev/data/versions/<name>.<ts>.jsonl + .sha256');
md.push('  → versions/ 是谱系锚点，不可删；本代数据此前缺快照，本次已补齐');
md.push('scripts/dedupe_re.py · refine_re.py · build_final.py 会重新生成被删的 3 份报告');
md.push('```');
fs.writeFileSync(P('CLEANUP-REPORT.md'), md.join('\n') + '\n', 'utf8');

console.log(JSON.stringify({
  removed: ledger.map(l => l.rel),
  nsfw_rows: nsfwRows, kitty_rows: kittyRows, total_rows: nsfwRows + kittyRows,
  snapshots: manifest.snapshots.count, current_snapshots: manifest.snapshots.current,
  train_params: trainParams,
  root_files: fs.readdirSync(D).filter(f => fs.statSync(P(f)).isFile()),
}, null, 2));

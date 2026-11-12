// 剔除 train/lines/_shared/data/nsfw/ 全树中的"逆向相关"行（meta.__stage==="re" 或 system 为 kitty 逆向工作台话术）
// 用法: node strip-re.mjs dry | node strip-re.mjs apply
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import readline from 'node:readline';

const MODE = process.argv[2] === 'apply' ? 'apply' : 'dry';
const ROOT = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/_shared/data/nsfw';
const TS = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
const BACKUP = path.join(ROOT, `_re-strip-backup-${TS}`);

const TARGETS = [
  'final-nsfw.jsonl',
  'mix-nsfw.jsonl',
  '_superseded/final-joint.jsonl',
  '_superseded/mix-joint.jsonl',
];

const isRe = (o) => {
  const stage = o?.meta?.__stage;
  const sys = String(o?.messages?.[0]?.content ?? '');
  return stage === 're' || /kitty\s*逆向工作台|kitty_[a-z]/i.test(sys);
};

const md5 = (s) => crypto.createHash('md5').update(s).digest('hex');

async function processFile(rel) {
  const src = path.join(ROOT, rel);
  const kept = [];
  const removed = [];
  let rows = 0;
  const rl = readline.createInterface({ input: fs.createReadStream(src, 'utf8'), crlfDelay: Infinity });
  for await (const line of rl) {
    if (!line.trim()) continue;
    rows++;
    let o = null;
    try { o = JSON.parse(line); } catch { kept.push(line); continue; } // 解析失败：不动
    if (isRe(o)) removed.push({ len: line.length, stage: o?.meta?.__stage, round: o?.meta?.__round, kind: o?.meta?.__kind });
    else kept.push(line);
  }
  const keptHashes = kept.map(md5);
  return { rel, src, rows, kept, removed, keptHashes };
}

const results = [];
for (const rel of TARGETS) results.push(await processFile(rel));

console.log('模式:', MODE, '| 备份目录:', BACKUP);
console.log('rel | rows | re | kept | removedRounds');
for (const r of results) {
  const rounds = {};
  for (const x of r.removed) rounds[x.stage + '/' + (x.round ?? '-')] = (rounds[x.stage + '/' + (x.round ?? '-')] || 0) + 1;
  console.log(`${r.rel} | ${r.rows} | ${r.removed.length} | ${r.kept.length} | ${Object.entries(rounds).map(([k, v]) => k + ':' + v).join(' ')}`);
}

if (MODE === 'dry') {
  console.log('\n[dry] 未写入。确认后跑 apply。');
  process.exit(0);
}

// ── apply ──
fs.mkdirSync(path.dirname(path.join(BACKUP, TARGETS[0])), { recursive: true });
for (const r of results) {
  const bak = path.join(BACKUP, r.rel);
  fs.mkdirSync(path.dirname(bak), { recursive: true });
  fs.copyFileSync(r.src, bak);          // 原件整份备份（可回滚）
  const tmp = r.src + '.tmp-strip';
  fs.writeFileSync(tmp, r.kept.join('\n') + '\n', 'utf8');
  // 回读验证：行数与哈希序列必须等于 kept
  const back = fs.readFileSync(tmp, 'utf8').split('\n').filter(Boolean);
  const ok = back.length === r.kept.length && back.every((l, i) => md5(l) === r.keptHashes[i]);
  if (!ok) { fs.unlinkSync(tmp); throw new Error('回读校验失败，已中止: ' + r.rel); }
  fs.renameSync(tmp, r.src);
  console.log(`[写入] ${r.rel}: ${r.rows} → ${back.length} 行（剔除 ${r.removed.length}），备份 ${path.relative(ROOT, bak)}`);
}
console.log('\n[apply] 完成');

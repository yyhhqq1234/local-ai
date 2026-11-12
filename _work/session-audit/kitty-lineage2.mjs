// 谱系分析 v2：用 user 文本 md5 作指纹（各文件结构不同，统一取 user content）
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import readline from 'node:readline';

const R = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/data/kitty-reverse';
const md5 = (s) => crypto.createHash('md5').update(s).digest('hex');

async function load(file) {
  const users = new Set(); const pairs = new Set();
  const grades = {}; const srcs = {};
  let n = 0;
  const rl = readline.createInterface({ input: fs.createReadStream(path.join(R, file), 'utf8'), crlfDelay: Infinity });
  for await (const line of rl) {
    const t = line.trim(); if (!t) continue; n++;
    let o; try { o = JSON.parse(t); } catch { continue; }
    if (o.grade) grades[o.grade] = (grades[o.grade] || 0) + 1;
    if (o.src) srcs[o.src] = (srcs[o.src] || 0) + 1;
    const msgs = o.messages || [];
    const user = msgs.find(m => m.role === 'user')?.content ?? '';
    const asst = msgs.find(m => m.role === 'assistant')?.content ?? '';
    if (user) { users.add(md5(String(user))); pairs.add(md5(String(user) + '\u0000' + String(asst))); }
  }
  return { n, users, pairs, grades, srcs };
}

const FILES = ['re-qc/gold.jsonl', 're-qc/silver.jsonl', 're-qc/reject.jsonl', 're-qc/scored.jsonl',
  'final-re.jsonl', 'final-re-final.jsonl', 'final-re-refined.jsonl', 'final-re-dedup.jsonl',
  'mix-re.jsonl', 're-iter/iter-all.jsonl', 'kitty-contracts/sft-kitty.jsonl'];
const F = {};
for (const f of FILES) {
  F[f] = await load(f);
  const extra = Object.keys(F[f].grades).length ? ` grades=${JSON.stringify(F[f].grades)}` : '';
  console.log(`${f}: ${F[f].n} 行 | 唯一user ${F[f].users.size} | 唯一对 ${F[f].pairs.size}${extra}`);
}
console.log('\nscored 的 src 分布:', JSON.stringify(Object.entries(F['re-qc/scored.jsonl'].srcs).slice(0, 5)));

const cov = (a, b, k = 'pairs') => {
  let h = 0; for (const x of F[a][k]) if (F[b][k].has(x)) h++;
  return `${h}/${F[a][k].size} = ${(h / F[a][k].size * 100).toFixed(1)}%`;
};
console.log('\n=== A ⊂ B（按 user+assistant 对）===');
const pairs = [
  ['re-qc/gold.jsonl', 'final-re.jsonl'],
  ['kitty-contracts/sft-kitty.jsonl', 'final-re.jsonl'],
  ['final-re.jsonl', 're-qc/gold.jsonl'],
  ['final-re-dedup.jsonl', 'final-re-refined.jsonl'],
  ['final-re-refined.jsonl', 'final-re-final.jsonl'],
  ['final-re-final.jsonl', 'final-re.jsonl'],
  ['final-re.jsonl', 'final-re-final.jsonl'],
  ['mix-re.jsonl', 'final-re.jsonl'],
  ['re-qc/silver.jsonl', 'final-re.jsonl'],
  ['re-iter/iter-all.jsonl', 'final-re.jsonl'],
  ['re-iter/iter-all.jsonl', 'kitty-contracts/sft-kitty.jsonl'],
];
for (const [a, b] of pairs) console.log(`${a} ⊂ ${b}: ${cov(a, b)}`);

// final-re 的构成拆解
let fromGold = 0, fromContract = 0, fromOther = 0;
for (const p of F['final-re.jsonl'].pairs) {
  if (F['re-qc/gold.jsonl'].pairs.has(p)) fromGold++;
  else if (F['kitty-contracts/sft-kitty.jsonl'].pairs.has(p)) fromContract++;
  else fromOther++;
}
console.log(`\nfinal-re 构成: gold ${fromGold} + contract ${fromContract} + 其它 ${fromOther} = ${F['final-re.jsonl'].pairs.size}`);
// gold 未被 final-re 采用
let goldUnused = 0; for (const p of F['re-qc/gold.jsonl'].pairs) if (!F['final-re.jsonl'].pairs.has(p)) goldUnused++;
console.log(`gold 未被 final-re 采用: ${goldUnused}`);
// 三档并集 vs scored 行数
console.log(`gold+silver+reject 行数 = ${F['re-qc/gold.jsonl'].n + F['re-qc/silver.jsonl'].n + F['re-qc/reject.jsonl'].n} vs scored ${F['re-qc/scored.jsonl'].n}`);

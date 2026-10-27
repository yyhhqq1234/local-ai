// kitty-reverse 数据谱系分析（只读）：谁是谁的超集/子集，谁是最终训练件
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import readline from 'node:readline';

const R = 'D:/BaiduNetdiskDownload/Local-AI/train/data/kitty-reverse';
const md5 = (s) => crypto.createHash('md5').update(s).digest('hex');

// 用首条 user content 的 md5 作为样本指纹（稳定、跨文件可比）
async function fingerprints(file, keyFn) {
  const set = new Set();
  let n = 0;
  const rl = readline.createInterface({ input: fs.createReadStream(path.join(R, file), 'utf8'), crlfDelay: Infinity });
  for await (const line of rl) {
    const t = line.trim(); if (!t) continue;
    n++;
    try {
      const o = JSON.parse(t);
      set.add(md5(keyFn(o) ?? t));
    } catch { set.add(md5(t)); }
  }
  return { set, n };
}
const msgKey = (o) => {
  const msgs = o.messages || o.conversations || [];
  const last = msgs[msgs.length - 1];
  return JSON.stringify(msgs.map(m => [m.role, String(m.content ?? m.value ?? '').slice(0, 300)]));
};

const files = ['re-qc/scored.jsonl', 're-qc/gold.jsonl', 're-qc/silver.jsonl', 'final-re.jsonl', 'final-re-final.jsonl', 'final-re-refined.jsonl', 'final-re-dedup.jsonl', 'kitty-contracts/sft-kitty.jsonl', 'mix-re.jsonl', 're-iter/iter-all.jsonl'];
const F = {};
for (const f of files) {
  F[f] = await fingerprints(f, msgKey);
  console.log(`${f}: ${F[f].n} 行, 唯一指纹 ${F[f].set.size}`);
}

const cover = (a, b) => { let h = 0; for (const x of F[a].set) if (F[b].set.has(x)) h++; return h; };
const pct = (h, t) => t ? (h / t * 100).toFixed(1) + '%' : 'n/a';

console.log('\n=== 关系（A 被 B 覆盖）===');
const pairs = [
  ['re-qc/gold.jsonl', 're-qc/scored.jsonl'],
  ['re-qc/silver.jsonl', 're-qc/scored.jsonl'],
  ['final-re.jsonl', 're-qc/gold.jsonl'],
  ['final-re.jsonl', 're-qc/scored.jsonl'],
  ['final-re.jsonl', 'kitty-contracts/sft-kitty.jsonl'],
  ['kitty-contracts/sft-kitty.jsonl', 'final-re.jsonl'],
  ['final-re-final.jsonl', 're-qc/gold.jsonl'],
  ['final-re-refined.jsonl', 're-qc/gold.jsonl'],
  ['final-re-dedup.jsonl', 're-qc/gold.jsonl'],
  ['final-re.jsonl', 'final-re-final.jsonl'],
  ['re-iter/iter-all.jsonl', 're-qc/gold.jsonl'],
  ['mix-re.jsonl', 'final-re.jsonl'],
];
for (const [a, b] of pairs) {
  const h = cover(a, b);
  console.log(`${a} ⊂ ${b}: ${h}/${F[a].set.size} = ${pct(h, F[a].set.size)}`);
}

// scored 是否为三档并集
const u = new Set([...F['re-qc/gold.jsonl'].set, ...F['re-qc/silver.jsonl'].set]);
let unionHit = 0;
for (const x of u) if (F['re-qc/scored.jsonl'].set.has(x)) unionHit++;
console.log(`\ngold ∪ silver = ${u.size}；其中在 scored 里 ${unionHit}（${pct(unionHit, u.size)}）`);
const scoredLess = F['re-qc/scored.jsonl'].set.size - unionHit;
console.log(`scored 剩余（含 reject）: ${scoredLess}`);

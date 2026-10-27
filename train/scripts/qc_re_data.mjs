#!/usr/bin/env node
/**
 * qc_re_data.mjs — RE 语料质检与分层（gold / silver / reject）
 *
 * 为什么需要：v6-mix 里每个 kitty_* 工具都出现 650-950 次，分布异常均匀 ——
 * 真实调用轨迹的工具分布应该极度不均（kitty_ce 982 vs 低频 1-2 次）。
 * 均匀说明大量样本是「工具枚举」而非真实任务流，直接混进 SFT 会教模型背清单，
 * 与系统提示「不要先查工具清单」正好打架。
 *
 * 五个判据（各 0-2 分）：
 *   M1 工具集中度   1-3 个工具=2 分 / 4-6=1 / >6=0（枚举嫌疑）
 *   M2 具体参数     含 0x 地址、pid、路径、模块名 → 有=2 无=0
 *   M3 回包/判据   含 OK| / ERR / verified / 判据 / 回包 → 有=2 无=0
 *   M4 多步语义    含 第一步/然后/接着/再/之后/回包后 → 有=1-2
 *   M5 长度适配    200-3000 字符=2 / 100-200 或 3000-6000=1 / 其他=0
 *
 * 输出：
 *   train/data/re-qc/scored.jsonl    每行带 score/grade/判据明细
 *   train/data/re-qc/summary.json    分层统计 + 按来源分布
 *   train/data/re-qc/{gold,silver,reject}.jsonl  分档文件
 *
 * 用法: node qc_re_data.mjs --out train/data/re-qc
 */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = 'train/kitty-rev/data';
const SOURCES = [
  'forge', 'forge2', 'forge3', 'forge4', 'forge5',
  'intent2', 'intent3', 'intent3/v5-mix', 'intent3/v6-mix',
  'large', 'large-mix', 'large-mix-plus', 'reasoning', 'reablit', 'subsets',
];

const outDir = process.argv.includes('--out')
  ? process.argv[process.argv.indexOf('--out') + 1]
  : 'train/data/re-qc';

const TOOL_RE = /\b(kitty_[a-z0-9_]+|reverse_add_[a-z]+|reverse_submit)\b/g;
const ADDR_RE = /0x[0-9a-fA-F]{6,}/;
const PID_RE = /\b(pid[=:\s]*\d{2,6}|进程\s*\d{2,6})\b/i;
const FILE_RE = /[\w\\/.-]+\.(exe|dll|apk|so|bin|pdb|jsonl|pcap)\b/i;
const REPLY_RE = /(OK\||ERR\||verified|回包|判据|need-range|no-open)/;
const STEP_RE = /(第一步|第二步|然后|接着|之后|再走|再看|回包后|先.*再)/g;

function scoreRow(obj) {
  const msgs = obj.messages || [];
  const asst = msgs.filter(m => m.role === 'assistant').map(m => m.content).join('\n');
  const all = msgs.map(m => m.content).join('\n');
  const len = all.length;

  const tools = new Set((asst.match(TOOL_RE) || []));
  const nTool = tools.size;
  const m1 = nTool >= 1 && nTool <= 3 ? 2 : nTool <= 6 ? 1 : 0;

  const concrete = (ADDR_RE.test(asst) || PID_RE.test(asst) || FILE_RE.test(asst)) ? 2 : 0;

  const m3 = REPLY_RE.test(asst) ? 2 : 0;

  const steps = (asst.match(STEP_RE) || []).length;
  const m4 = steps >= 2 ? 2 : steps === 1 ? 1 : 0;

  const m5 = len >= 200 && len <= 3000 ? 2 : (len >= 100 && len <= 6000) ? 1 : 0;

  const score = m1 + concrete + m3 + m4 + m5;
  const grade = score >= 8 ? 'gold' : score >= 5 ? 'silver' : 'reject';
  return { score, grade, detail: { m1, concrete, m3, m4, m5 }, nTool, tools: [...tools].slice(0, 8), len };
}

fs.mkdirSync(outDir, { recursive: true });
const all = [];
const bySrc = {};

for (const src of SOURCES) {
  const dir = path.join(ROOT, src);
  if (!fs.existsSync(dir)) continue;
  for (const name of fs.readdirSync(dir)) {
    if (!name.endsWith('.jsonl')) continue;
    const fp = path.join(dir, name);
    if (!fs.statSync(fp).isFile()) continue;
    const lines = fs.readFileSync(fp, 'utf8').split('\n').filter(Boolean);
    let n = 0;
    for (const line of lines) {
      let o;
      try { o = JSON.parse(line); } catch { continue; }
      if (!o.messages) continue;
      const s = scoreRow(o);
      all.push({ src: `${src}/${name}`, ...s, obj: o });
      n++;
    }
    bySrc[`${src}/${name}`] = n;
  }
}

// 落盘
const buckets = { gold: [], silver: [], reject: [] };
for (const r of all) buckets[r.grade].push(r);

fs.writeFileSync(path.join(outDir, 'scored.jsonl'),
  all.map(r => JSON.stringify({ src: r.src, score: r.score, grade: r.grade, detail: r.detail, nTool: r.nTool, len: r.len, tools: r.tools })).join('\n') + '\n');

for (const g of ['gold', 'silver', 'reject']) {
  fs.writeFileSync(path.join(outDir, `${g}.jsonl`),
    buckets[g].map(r => JSON.stringify(r.obj)).join('\n') + (buckets[g].length ? '\n' : ''));
}

const summary = {
  total: all.length,
  grades: { gold: buckets.gold.length, silver: buckets.silver.length, reject: buckets.reject.length },
  gold_ratio: +(buckets.gold.length / Math.max(all.length, 1)).toFixed(4),
  avg_score: +(all.reduce((s, r) => s + r.score, 0) / Math.max(all.length, 1)).toFixed(2),
  // 工具枚举嫌疑：单条样本里出现 >6 个不同工具
  enum_suspect: all.filter(r => r.nTool > 6).length,
  // 无具体参数（纯文字描述）
  no_concrete: all.filter(r => r.detail.concrete === 0).length,
  by_grade_nTool: {
    gold_avg_tools: +((buckets.gold.reduce((s, r) => s + r.nTool, 0) / Math.max(buckets.gold.length, 1)).toFixed(2)),
    reject_avg_tools: +((buckets.reject.reduce((s, r) => s + r.nTool, 0) / Math.max(buckets.reject.length, 1)).toFixed(2)),
  },
  sources: bySrc,
};
fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 1));

console.log(JSON.stringify({
  out: outDir,
  total: summary.total,
  grades: summary.grades,
  gold_ratio: summary.gold_ratio,
  avg_score: summary.avg_score,
  enum_suspect: summary.enum_suspect,
  no_concrete: summary.no_concrete,
  ...summary.by_grade_nTool,
}, null, 1));

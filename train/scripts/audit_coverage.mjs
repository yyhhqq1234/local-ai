#!/usr/bin/env node
/**
 * audit_coverage.mjs — 逆向工作台训练集覆盖审计
 *
 * 回答一个问题：训练集对工作台 64 工具 / 66 OP 的覆盖到什么程度，缺什么。
 *
 * 判定口径（分档）：
 *   deep   该工具在专用样本（param/enum/combo/branch/tool 类）里出现 ≥3 次
 *   mid    出现在专用样本里 1-2 次
 *   shallow 只出现在 toolmap（全景描述）里
 *   none   完全没出现
 *
 * 输出：train/data/re-iter/COVERAGE.json + 控制台摘要
 */
import fs from 'node:fs';

const D = 'train/data';
const SRC = [
  `${D}/re-iter/iter-all.jsonl`,
  `${D}/kitty-contracts/sft-kitty.jsonl`,
  `${D}/re-qc/gold.jsonl`,
];
const TOOLS = JSON.parse(fs.readFileSync(`${D}/kitty-contracts/tools.json`, 'utf8'));
const OPS = JSON.parse(fs.readFileSync(`${D}/kitty-contracts/ops.json`, 'utf8'));

// 载入样本
const rows = [];
for (const f of SRC) {
  if (!fs.existsSync(f)) continue;
  for (const line of fs.readFileSync(f, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try {
      const o = JSON.parse(line);
      if (o.messages) rows.push({ src: f.split('/').pop(), kind: (o.meta && o.meta.__kind) || '?', text: JSON.stringify(o.messages) });
    } catch { /* skip */ }
  }
}

const TOOL_RE = /\b(kitty_[a-z0-9_]+|reverse_[a-z_]+)\b/g;

// OP 匹配：从 ops.json 动态构建（硬编码正则会漏掉低频 OP —— 上一版就漏了 VER/LP/AL_* 全家）
// 通配条目（如 AL_*）展开成前缀匹配
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const opPatterns = OPS.map(o => {
  if (o.op.endsWith('_*')) return { name: o.op, re: new RegExp('\\b' + esc(o.op.slice(0, -1)) + '[A-Z_]+\\b', 'g') };
  return { name: o.op, re: new RegExp('\\b' + esc(o.op) + '\\b', 'g') };
});

// 专用样本类（排除 toolmap 全景）
const DEDICATED = new Set(['param', 'enum', 'combo', 'branch', 'tool', 'upstream', 'pitfall', 'criteria', 'chain',
  'scan', 'pchain', 'kernel', 'debug', 'static', 'dump', 'runtime', 'anti', 'infra', 'engine', 'mobile',
  'rea', 'g3', 'session', 'decision', 'path', 'host', 'dbvm', 'layout', 'build', 'evidence', 'drvfail', 'misread',
  'platform', 'fullblood', 'boundary']);

const toolHits = new Map();
const toolDedicated = new Map();
const opHits = new Map();
const opSample = new Map();

for (const r of rows) {
  const tset = new Set(r.text.match(TOOL_RE) || []);
  for (const t of tset) {
    toolHits.set(t, (toolHits.get(t) || 0) + 1);
    if (DEDICATED.has(r.kind)) toolDedicated.set(t, (toolDedicated.get(t) || 0) + 1);
  }
  const oset = new Set();
  for (const p of opPatterns) {
    p.re.lastIndex = 0;
    if (p.re.test(r.text)) oset.add(p.name);
  }
  for (const o of oset) {
    opHits.set(o, (opHits.get(o) || 0) + 1);
    if (!opSample.has(o)) opSample.set(o, r.kind);
  }
}

// 工具分档
const toolTable = TOOLS.map(t => {
  const all = toolHits.get(t.name) || 0;
  const ded = toolDedicated.get(t.name) || 0;
  const grade = ded >= 3 ? 'deep' : ded >= 1 ? 'mid' : all >= 1 ? 'shallow' : 'none';
  return { name: t.name, channel: t.channel, actions: t.actions.length, all, dedicated: ded, grade };
}).sort((a, b) => {
  const rank = { none: 0, shallow: 1, mid: 2, deep: 3 };
  return rank[a.grade] - rank[b.grade] || a.dedicated - b.dedicated;
});

// OP 分档
const opTable = OPS.map(o => {
  const n = opHits.get(o.op) || 0;
  return { op: o.op, group: o.group, hits: n, grade: n >= 5 ? 'deep' : n >= 1 ? 'mid' : 'none' };
}).sort((a, b) => a.hits - b.hits);

// 汇总
const toolGrades = toolTable.reduce((a, t) => (a[t.grade] = (a[t.grade] || 0) + 1, a), {});
const opGrades = opTable.reduce((a, o) => (a[o.grade] = (a[o.grade] || 0) + 1, a), {});
const toolScore = toolTable.reduce((s, t) => s + ({ none: 0, shallow: 0.3, mid: 0.7, deep: 1 }[t.grade]), 0) / toolTable.length;
const opScore = opTable.reduce((s, o) => s + ({ none: 0, mid: 0.6, deep: 1 }[o.grade]), 0) / opTable.length;

const report = {
  samples_scanned: rows.length,
  sources: SRC.map(p => p.split('/').pop()),
  tools: { total: TOOLS.length, grades: toolGrades, weighted_score: +toolScore.toFixed(3), gaps: toolTable.filter(t => t.grade !== 'deep') },
  ops: { total: OPS.length, grades: opGrades, weighted_score: +opScore.toFixed(3), gaps: opTable.filter(o => o.grade !== 'deep') },
}

fs.writeFileSync(`${D}/re-iter/COVERAGE.json`, JSON.stringify(report, null, 1), 'utf8');

console.log('样本扫描:', rows.length, '条');
console.log('\n【工具】' + TOOLS.length + ' 个，加权覆盖 ' + (toolScore * 100).toFixed(1) + '%');
console.log('  ' + JSON.stringify(toolGrades));
console.log('  未达 deep 的工具:');
for (const t of toolTable.filter(t => t.grade !== 'deep')) {
  console.log('   ' + t.grade.padEnd(8) + t.name.padEnd(26) + 'ch=' + String(t.channel).padEnd(12) + 'actions=' + String(t.actions).padEnd(3) + 'dedicated=' + t.dedicated + ' all=' + t.all);
}
console.log('\n【OP】' + OPS.length + ' 条，加权覆盖 ' + (opScore * 100).toFixed(1) + '%');
console.log('  ' + JSON.stringify(opGrades));
const zero = opTable.filter(o => o.grade === 'none');
if (zero.length) console.log('  零覆盖 OP: ' + zero.map(o => o.op).join(' '));

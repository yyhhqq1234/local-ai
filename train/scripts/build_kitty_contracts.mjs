#!/usr/bin/env node
/**
 * build_kitty_contracts.mjs — 从 kitty 逆向工作台源码提取机器可读契约（只读 DrCE）
 *
 * 事实源（只读）：
 *   D:/DrCE(26.2.16)/kitty-toolbox/src/ops-catalog.ts   → A 通道 OP 冻结表（sig/reply/note）
 *   D:/DrCE(26.2.16)/kitty-toolbox/src/tool-manifest.ts → 35 工具能力自描述
 *
 * 输出（工作区内）：
 *   train/data/kitty-contracts/ops.json    [{op,sig,reply,note,group}]
 *   train/data/kitty-contracts/tools.json  [{name,channel,actions,ops,description}]
 *   train/data/kitty-contracts/STATS.json  覆盖统计与缺口
 *
 * 只读源目录，绝不写入 DrCE。
 */
import fs from 'node:fs';
import path from 'node:path';

const SRC = 'D:/DrCE(26.2.16)/kitty-toolbox/src';
const OUT = 'train/data/kitty-contracts';

// ---------- 解析 OpSpec 数组 ----------
function parseOps(text, arrName) {
  const start = text.indexOf(`export const ${arrName}`);
  if (start < 0) return [];
  // 找到该数组的结束：下一个 export const 之前
  const nextExport = text.indexOf('export const ', start + 10);
  const seg = text.slice(start, nextExport > 0 ? nextExport : text.length);

  const rows = [];
  // 逐条匹配 { op: '...', sig: '...', reply: '...', note?: '...' }
  const re = /\{\s*op:\s*'((?:[^'\\]|\\.)*)'\s*,\s*sig:\s*'((?:[^'\\]|\\.)*)'\s*,\s*reply:\s*'((?:[^'\\]|\\.)*)'(?:\s*,\s*note:\s*'((?:[^'\\]|\\.)*)')?\s*,?\s*\}/gs;
  let m;
  while ((m = re.exec(seg)) !== null) {
    rows.push({
      op: m[1].replace(/\\'/g, "'"),
      sig: m[2].replace(/\\'/g, "'"),
      reply: m[3].replace(/\\'/g, "'"),
      note: (m[4] || '').replace(/\\'/g, "'"),
      group: arrName === 'KM_OPS' ? 'kernel' : 'a-channel',
    });
  }
  return rows;
}

// ---------- 解析 TOOL_MANIFEST ----------
function parseTools(text) {
  const start = text.indexOf('export const TOOL_MANIFEST');
  if (start < 0) return [];
  const nextExport = text.indexOf('\n]', start);
  const seg = text.slice(start, nextExport > 0 ? nextExport : text.length);

  const rows = [];
  const re = /\{\s*name:\s*'([^']+)'\s*,\s*channel:\s*'([^']+)'\s*,\s*actions:\s*\[([^\]]*)\](?:\s*,\s*ops:\s*\[([^\]]*)\])?\s*,\s*description:\s*'((?:[^'\\]|\\.)*)'\s*\}/gs;
  let m;
  while ((m = re.exec(seg)) !== null) {
    const arr = (s) => (s || '').split(',').map(x => x.trim().replace(/^'|'$/g, '')).filter(Boolean);
    rows.push({
      name: m[1],
      channel: m[2],
      actions: arr(m[3]),
      ops: arr(m[4]),
      description: m[5].replace(/\\'/g, "'"),
    });
  }
  return rows;
}

// ---------- 主流程 ----------
fs.mkdirSync(OUT, { recursive: true });
const opsSrc = fs.readFileSync(path.join(SRC, 'ops-catalog.ts'), 'utf8');
const manSrc = fs.readFileSync(path.join(SRC, 'tool-manifest.ts'), 'utf8');

const ops = [...parseOps(opsSrc, 'KM_OPS'), ...parseOps(opsSrc, 'OPS')];
const tools = parseTools(manSrc);

// 去重（同 op 名只留第一条）
const seen = new Set();
const opsUniq = ops.filter(o => (seen.has(o.op) ? false : (seen.add(o.op), true)));

fs.writeFileSync(path.join(OUT, 'ops.json'), JSON.stringify(opsUniq, null, 1));
fs.writeFileSync(path.join(OUT, 'tools.json'), JSON.stringify(tools, null, 1));

// ---------- 覆盖缺口统计 ----------
const declared = new Set();
for (const t of tools) for (const o of t.ops) if (o !== '*') declared.add(o);

const docOps = new Set(opsUniq.map(o => o.op));
const missing = [...declared].filter(o => !docOps.has(o));
const undocumented = [...docOps].filter(o => !declared.has(o));

// 拒绝口径样本（note 里带硬约束的）
const gates = opsUniq.filter(o => /拒绝|不许|禁止|上限|卡死|杀宿主|永不|早拒|need-range|requires|只清标志/.test(o.note));

const stats = {
  generated_at: new Date().toISOString(),
  source: {
    ops_catalog: `${SRC}/ops-catalog.ts`,
    tool_manifest: `${SRC}/tool-manifest.ts`,
  },
  ops_total: opsUniq.length,
  ops_kernel: opsUniq.filter(o => o.group === 'kernel').length,
  ops_achannel: opsUniq.filter(o => o.group === 'a-channel').length,
  tools_total: tools.length,
  ops_declared_by_tools: declared.size,
  gate_ops: gates.length,
  channels: Object.entries(tools.reduce((a, t) => (a[t.channel] = (a[t.channel] || 0) + 1, a), {})),
  // 工具声明了但 ops-catalog 没写签名的（需要去 src 里补真实签名）
  ops_missing_signature: missing,
  // ops-catalog 有但工具清单没引用的（独立可用 OP）
  ops_not_in_tool_list: undocumented.length,
  gate_samples: gates.slice(0, 8).map(g => ({ op: g.op, note: g.note.slice(0, 90) })),
};

fs.writeFileSync(path.join(OUT, 'STATS.json'), JSON.stringify(stats, null, 2));

console.log(JSON.stringify(stats, null, 1));

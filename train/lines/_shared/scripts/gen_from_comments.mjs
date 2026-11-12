#!/usr/bin/env node
/**
 * gen_from_comments.mjs — 把源码注释转成「判据 / 风险 / 限额 / 顺序」样本（R06-R20 共用引擎）
 *
 * 输入：train/data/re-iter/drce-comments.json（197 条中文注释）
 * 过滤：只留含 判据/风险/禁用/限额/顺序 标签，且能关联到具体工具或 OP 的
 * 输出：train/data/re-iter/r03-criteria.jsonl
 */
import fs from 'node:fs';

const IN = 'train/data/re-iter/drce-comments.json';
const OUT = 'train/data/re-iter/r03-criteria.jsonl';
const comments = JSON.parse(fs.readFileSync(IN, 'utf8'));

const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

// 文件 → 主要工具（tools/ 目录的 7 个文件按注册顺序覆盖）
const FILE_TOOL = {
  'tools/channel-tools.ts': ['kitty_drv', 'kitty_ce', 'kitty_status', 'kitty_x64dbg', 'kitty_pchain', 'kitty_dbg', 'kitty_sym'],
  'tools/mem-tools.ts': ['kitty_ce'],
  'tools/kernel-tools.ts': ['kitty_km'],
  'tools/static-tools.ts': ['kitty_patch', 'kitty_asm', 'kitty_sym'],
  'tools/driver-tools.ts': ['kitty_drv', 'kitty_init', 'kitty_variants', 'kitty_drvio'],
  'tools/anti-tools.ts': ['kitty_acescan', 'kitty_dualview', 'kitty_wpb'],
  'tools/session-tools.ts': ['kitty_settings', 'kitty_trail'],
  'rea.ts': ['kitty_rea'],
  'x64dbg.ts': ['kitty_x64dbg'],
  'dump.ts': ['kitty_dump'],
  'loop.ts': ['kitty_loop', 'kitty_loop_status'],
  'tools/deps.ts': ['kitty_ce'],
};

const OP_RE = /\b(PING|OPEN|CUR|R|W|ALLOC|FREE|MODENUM|MODBASE|S_NEW|S_GET|S_SNAP|S_CHANGED|S_UNCHANGED|S_FREE|P_BACK|P_WALK|P_BACK_RES|KM_[A-Z]+|DBG_[A-Z_]+|SYNC_[A-Z]+|JOB_STAT|BATCH|LUA|BRIDGE_VER)\b/;

function toolOf(c) {
  if (c.tool && c.tool.startsWith('kitty_') || (c.tool && c.tool.startsWith('reverse_'))) return c.tool;
  const list = FILE_TOOL[c.file];
  if (list) {
    // 注释里提到哪个就用哪个，否则取该文件第一个
    const found = list.find(t => c.text.includes(t.replace('kitty_', 'kitty_')));
    return found || list[0];
  }
  const m = c.text.match(/\b(kitty_[a-z0-9_]+|reverse_[a-z_]+)\b/);
  return m ? m[1] : null;
}

const out = [];
const seen = new Set();

for (const c of comments) {
  const tags = c.tags || [];
  const highValue = tags.some(t => ['判据', '风险', '禁用', '限额'].includes(t));
  const tool = toolOf(c);
  const ops = [...new Set((c.text.match(new RegExp(OP_RE.source, 'g')) || []))];

  // 只留高价值 + 能落到具体工具/OP 的
  if (!highValue && !ops.length) continue;
  if (!tool && !ops.length) continue;

  const key = c.text.slice(0, 60);
  if (seen.has(key)) continue;
  seen.add(key);

  const subj = tool || ops[0];
  const txt = c.text;
  let q, a;

  if (tags.includes('判据')) {
    q = `${subj} 这一步怎么判成功？看什么字段？`;
    a = `${txt}\n\n落到调用上：${ops.length ? `看 ${ops.join(' / ')} 的回包` : '看回包首段状态位'}，\n符合上面这条才算过；不符合别急着进下一步，先把当前步的原因查清。`;
  } else if (tags.includes('风险') || tags.includes('禁用')) {
    q = `${subj} 有什么要特别小心的地方？`;
    a = `${txt}\n\n处置：碰到这个边界先停，按上面写的原因判断能不能绕；\n${ops.length ? `涉及 ${ops.join(' / ')} 时` : '涉及这类操作时'}宁可用更保守的等价路径（换通道 / 换工具 / 缩小窗口），也不要硬闯。`;
  } else if (tags.includes('限额')) {
    q = `${subj} 有限额吗？超了会怎样？`;
    a = `${txt}\n\n给参数时按这个限额来，超了通常回 need-range 或截断；\n分多次做比一次给满稳。`;
  } else {
    q = `${subj} 这个顺序能换吗？`;
    a = `${txt}\n\n顺序不能随意换的原因：后一步依赖前一步的产物（地址/会话/状态）。\n跳步的典型后果是拿到空结果或读到旧值，看起来像"工具坏了"。`;
  }

  out.push({
    id: `kitty-crit-${String(out.length).padStart(4, '0')}`,
    messages: [
      { role: 'system', content: SYS },
      { role: 'user', content: q },
      { role: 'assistant', content: a },
    ],
    meta: { __stage: 're', __kind: 'criteria', __round: 'r03', src_file: c.file, tool, ops, tags },
  });
}

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');

const byTool = out.reduce((a, x) => (a[x.meta.tool || 'op-only'] = (a[x.meta.tool || 'op-only'] || 0) + 1, a), {});
console.log(JSON.stringify({
  out: OUT, samples: out.length,
  tools: Object.keys(byTool).length,
  by_tool: byTool,
}, null, 1));

#!/usr/bin/env node
/**
 * gen_from_deep.mjs — 用参数级契约生成 R01-R05 训练样本
 *
 * 数据源：train/data/re-iter/drce-tools-deep.json（64 工具 / 279 参数 / 225 带说明）
 * 特点：参数 description 是工具实现里的原文，含真实默认值、上限、枚举、互斥 ——
 *       这是「怎么调用」最可靠的来源，不是猜的。
 *
 * 生成五类：
 *   P1 参数约束   每个带"默认/上限/仅/必须"的参数 → 给值 + 越界行为 + 完整调用
 *   P2 枚举选择   带 enum 或 enum 式 description 的参数 → 各取值区别
 *   P3 工具全景   每工具 1 条：通道 + action 面 + 何时用 + 不该用
 *   P4 参数组合   多参数工具 → 给一套完整调用（参数一次给全）
 *   P5 action 分支 从实现里的 if (act === 'x') 提取真实分支 → 各分支干什么
 *
 * 输出：train/data/re-iter/r01-tools.jsonl
 */
import fs from 'node:fs';

const DEEP = 'train/data/re-iter/drce-tools-deep.json';
const MANIFEST = 'train/data/kitty-contracts/tools.json';
const OUT = 'train/data/re-iter/r01-tools.jsonl';

const deep = JSON.parse(fs.readFileSync(DEEP, 'utf8'));
const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
const byName = new Map(manifest.map(t => [t.name, t]));

const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (kind, user, assistant, meta = {}) => out.push({
  id: `kitty-${kind}-${String(out.length).padStart(4, '0')}`,
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: { __stage: 're', __kind: kind, __round: 'r01', ...meta },
});

// ---------- P3 工具全景（每工具 1 条）----------
for (const t of deep) {
  const m = byName.get(t.name) || {};
  const ch = m.channel || '?';
  const acts = t.action_branches.length ? t.action_branches : (m.actions || []);
  const paramList = t.params.map(p => p.name).join(' / ');
  add('toolmap', `${t.name} 是干什么的？什么情况下该用它、什么时候不该用？`,
    `${t.name} — ${t.description}\n\n通道：${ch}\naction 面：${acts.join(' / ') || '（无 action，直接给参数）'}\n关键参数：${paramList || '（无参）'}\n\n什么时候用它：任务落在「${(m.description || t.description).slice(0, 40)}」这个面时直接选它，不要先去 kitty_ops 查表。\n什么时候不该用：需要跨面组合时（比如既读内存又要内核视图对照），走 ${ch === 'A' ? 'kitty_dualview / kitty_acescan 这类编排工具，而不是自己拼多条 kitty_ce' : '对应的编排工具'}。`,
    { tool: t.name, channel: ch });
}

// ---------- P1 参数约束 ----------
const RE_CONSTRAINT = /(默认|上限|最多|最少|仅|只|必须|必填|不能|超过|超|范围|下限|上限=\d)/;
for (const t of deep) {
  for (const p of t.params) {
    if (!p.description || !RE_CONSTRAINT.test(p.description)) continue;
    const q = `用 ${t.name} 时 ${p.name} 给什么？有什么限制？`;
    add('param', q,
      `${p.name}（${p.type || 'string'}${p.required ? '，必填' : ''}）：${p.description}\n\n给值原则：按上面的约束来，不要自己放宽——实现里会对越界值做兜底或直接拒。\n完整调用示例：${t.name} ${p.name}=${suggest(p)}\n\n判据：回包如果对参数报了错（bad-arg 之类），先对照这条参数说明改，不要重发同一条。`,
      { tool: t.name, param: p.name });
  }
}

function suggest(p) {
  const d = p.description || '';
  const m = d.match(/默认\s*([0-9]+)/);
  if (p.type === 'number') return m ? m[1] : '20';
  if (p.type === 'boolean') return 'true';
  const e = d.match(/([a-z][a-z0-9-]+)\s*\|\s*([a-z][a-z0-9-]+)/i);
  if (e) return e[1];
  return '<按上面取值>';
}

// ---------- P2 枚举选择 ----------
for (const t of deep) {
  for (const p of t.params) {
    const d = p.description || '';
    const enums = p.enum.length ? p.enum : (d.match(/([a-z][a-z0-9_-]{1,20})(\s*\|\s*[a-z][a-z0-9_-]{1,20}){1,5}/gi) || [])
      .flatMap(x => x.split('|').map(s => s.trim())).filter(Boolean);
    if (enums.length < 2) continue;
    const uniqE = [...new Set(enums)].slice(0, 6);
    add('enum', `${t.name} 的 ${p.name} 有 ${uniqE.join(' / ')} 几种，怎么选？`,
      `${p.name} 取值（按实现原文）：${d || uniqE.join(' | ')}\n\n选法：\n${uniqE.map(e => `· ${e} — ${guessMeaning(e, t.name)}`).join('\n')}\n\n判据：选错枚举通常回 bad-arg 或 unknown-op 类错误，看到这类错先回查本参数，不要换工具重试。`,
      { tool: t.name, param: p.name, enums: uniqE });
  }
}

function guessMeaning(e, tool) {
  const map = {
    status: '只读探状态，不动任何东西，先跑这个再决定下一步',
    init: '真正建依赖，会起服务，属于动手类',
    ensure: '幂等保证就绪，已就绪则跳过（有缓存）',
    recover: '修故障态（如 STOP_PENDING）',
    storm: '压测连续多轮，看稳定性',
    list: '只列清单，不产生产物',
    info: '读基础信息（头/节表/属性），不改文件',
    find: '按模式定位偏移，先定位再改',
    patch: '实际写字节，必须带 expect 校验',
    rollback: '回到备份状态',
    hash: '算校验和，用于改动前后比对',
    dump: '导出内存镜像',
    unmap: '把内存镜像重建回磁盘格式',
    read: '读一次，取当前值',
    write: '写一次并回读',
    pa: '虚拟地址翻物理地址',
    pread: '物理地址读',
    pwrite: '物理地址写（默认拒绝）',
    attach: '建立连接/会话',
    detach: '断开会话',
    go: '继续执行',
    bp: '下断点',
    probe: '带一次实探的健康检查',
    route: '按目标类型路由到对应工具链',
    decode: '解码/反编译',
    scan: '扫描/指纹识别',
    collect: '归集产物',
    parse: '解析产物',
    export: '导出资产',
    unpack: '解包',
    recover_js: '从打包产物重建源码',
  };
  return map[e] || `对应「${e}」这个动作面，看 description 里该词的说明`;
}

// ---------- P4 参数组合（多参数工具一次给全）----------
for (const t of deep) {
  if (t.params.length < 3) continue;
  const args = t.params.map(p => {
    if (p.required) return `${p.name}=${suggest(p)}`;
    return null;
  }).filter(Boolean);
  const optional = t.params.filter(p => !p.required).slice(0, 4);
  add('combo', `${t.name} 一次要给的参数有哪些？给我一套能直接发的。`,
    `${t.name} 的参数面（共 ${t.params.length} 个）：\n${t.params.map(p => `· ${p.name}${p.required ? '（必填）' : '（可选）'} — ${p.description || '无说明'}`).join('\n')}\n\n一套可直接发的：\n${t.name}${args.length ? ' ' + args.join(' ') : ''}${optional.length ? '\n（可选补充：' + optional.map(p => p.name).join(' / ') + '）' : ''}\n\n判据：动手类参数（confirm / accept_* 这类）不给就是拒绝；必填缺一个直接 bad-arg，不会自己补默认值。`,
    { tool: t.name });
}

// ---------- P5 action 实现分支 ----------
for (const t of deep) {
  if (t.action_branches.length < 2) continue;
  add('branch', `${t.name} 的 ${t.action_branches.join(' / ')} 在实现里分别做什么？`,
    `${t.name} 的实现分支（从源码 if 分支提取，比文档准）：\n${t.action_branches.map(a => `· ${a} — ${guessMeaning(a, t.name)}`).join('\n')}\n\n判据：这些是真实走到的分支，不在列表里的值会落到默认分支或报错。选之前先想清楚这一步是"看"还是"动"，看类不产生副作用，动类要确认参数。`,
    { tool: t.name, branches: t.action_branches });
}

// ---------- 落盘 ----------
fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');

const kinds = out.reduce((a, x) => (a[x.meta.__kind] = (a[x.meta.__kind] || 0) + 1, a), {});
const chars = out.reduce((s, x) => s + JSON.stringify(x.messages).length, 0);
console.log(JSON.stringify({
  out: OUT, samples: out.length, by_kind: kinds,
  total_chars: chars, avg_chars: Math.round(chars / out.length),
  tools_covered: new Set(out.filter(x => x.meta.tool).map(x => x.meta.tool)).size,
}, null, 1));

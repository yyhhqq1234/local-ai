#!/usr/bin/env node
/**
 * gen_r35_dbvm2.mjs — R35：DBVM 0.5 硬规定 + 唯一正确链路 + 判据四坑 + checkSessionAction 分流
 *
 * 事实源（只读 DrCE）：
 *   README.md「0.5 硬规定：DBVM 只能由操作者通过 CE 拉起」+「正确链路」六步 + 坑 A 判据类
 *   configs/reverse-hybrid/session-gate.mjs 的 checkSessionAction（S1 + H1 分流）
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r35-dbvm2.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (kind, user, assistant, meta) => out.push({
  id: 'kitty-r35-' + kind + '-' + String(out.length).padStart(4, '0'),
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: Object.assign({ __stage: 're', __kind: kind, __round: 'r35' }, meta || {}),
});

const BOUNDARY = [
  ['DBVM 能不能由我来拉起',
    '**不能。这是边界，不是建议。**\n\n唯一通路：操作者在 CE 界面点 DBVM。\n\n原因：DBVM 初始化必须在 CE 的引擎主线程上下文执行。\n\n你的职责边界：\n· 可以做**前置** —— 驱动 / qc / 开关 / 单实例 / 桥 / SYNC / 中和 cmd.txt\n· 可以做**只读校验** —— 关于框版本、acescan 的 pa 字段\n· **不能做** "点 DBVM" 这一步\n\n判据：任何"我帮你把 DBVM 起起来"的方案都越界。'],
  ['用 UI 自动化点 CE 的 DBVM 按钮算不算代拉',
    '算。**禁止**。\n\nUI 自动化 / SendKeys / 注入点击 与"代拉"等价 —— 出问题时无法区分是 DBVM 本身的问题还是自动化引入的。\n\n判据：自动化点击 DBVM = 越界，和直接调 API 一样。'],
  ['经 cmd.txt 的 LUA 能起 DBVM 吗',
    '**不能，实测必 false。**\n\n桥侧 LUA 触发 dbvm_initialize 走不通（这个函数必须 GUI 上下文）。\n\n同理：经 CE 的 Lua 引擎窗口（含脚本注入多行）也不行 —— 会失败/卡死，而且比手动点更容易把 Lua 线程打死。\n\n判据：dbvm_initialize 走桥必然返回 false，不是参数问题。'],
  ['dbvm-auto.ps1 这类脚本能当日常拉起手段吗',
    '不能。它们只算**诊断**用。\n\n· dbvm-auto.ps1 -Stage Start / dbvm-oneshot.ps1 会写 cmd.txt 触发\n· 只在排障时用，**不得作为日常拉起手段**，更不得当作"已达成"\n\n判据：把脚本跑通当 DBVM 已就绪 = 误判。'],
  ['dbk_initialize 和 dbvm_initialize 的通道要求一样吗',
    '不一样，这是关键区别：\n\n· **dbk_initialize 走桥可以**\n· **dbvm_initialize 走桥必 false**（必须 GUI）\n\n判据：桥里 dbk 成功但 dbvm false，不是环境坏了，是通道选错。'],
];

const CHAIN = [
  ['DBVM 被验证过的唯一正确链路是什么',
    '六步，顺序固定：\n① 开机：KittyDrvBootHeal（AtStartup/SYSTEM）→ aux + KittyPrettyDriver(DrDriver) 先进内核，**早于 CE**\n② mhtglyts 保持 **STOPPED**，qc = Kitty_Dr_D_VT.sys\n③ 点【初始化驱动】→ 拉起 CE（此时**不要**让 init 对 VT 映像走 SCM START）\n④ CE 内触发 dbk_initialize() → CE 自己把 mhtglyts(VT) 装入（SCM 装不了，这是唯一入口）\n⑤ CE 内（GUI）触发 dbvm_initialize() → DBVM 起来，桥随后自愈\n⑥ 校验：dbvm_getCR4=11874040 · HypervisorPresent=True · 关于框 DBVM 19\n\n判据：跳步的典型后果是 mhtglyts 先 RUNNING → dbk_initialize 失败。'],
  ['第 2 步为什么 mhtglyts 要保持 STOPPED',
    '因为 mhtglyts 一旦先 RUNNING，第 ④ 步的 dbk_initialize 就会失败（DriverEntry 失败 → CE 弹 DBK 错误模态框 → Lua 阻塞 → PING 超时 → 看门狗连环重拉）。\n\n正确顺序：**dbk64 先进，mhtglyts 后起**。\n\n判据：CE 弹「DBK 错误」就是顺序反了。'],
  ['第 3 步为什么不能让 init 对 VT 映像走 SCM START',
    '因为 SCM 装不了 VT 映像 —— 这是已知限制，VT 映像只能由 CE 自己装入。\n\n所以【初始化驱动】只拉 CE，不负责 start VT 映像。\n\n判据：SCM 强行 start VT 映像 → 31。'],
  ['第 6 步的三个校验值分别是什么',
    '· dbvm_getCR4 = **11874040**\n· HypervisorPresent = **True**\n· 关于框显示 **DBVM 19**\n\n注意：判 VMXE 不要用 dbk_getCR4 —— 它成功时也是 0xB50EF8（无 0x2000 位）。\n\n判据：三个值齐了才算 DBVM 真起来。'],
];

const PIT_A = [
  ['pcall 返回 true 就是成功了吗',
    '**不是。**这是判据类坑第 4 条。\n\ndbvm_initialize 的返回值形态是 true/false 两个值：`pcall` 的第一个返回值表示"调用没抛异常"，**第二个才是函数真正的返回值 false**。\n\n判据：必须读第二项，不能只看 pcall 的 true。'],
  ['用 dbk_getCR4 判 VMXE 对不对',
    '不对。它成功时也是 **0xB50EF8**，没有 0x2000（VMXE）位。\n\n正确判据：看 **dbvm_getCR4 = 11874040**。\n\n判据：拿 dbk_getCR4 判 VMXE = 永远判不出来。'],
  ['怎么判断 DBVM 是不是真的初始化成功',
    '唯一可靠：dbvm_initialize 的**第二返回值**。\n\n辅助：dbvm_getCR4 = 11874040、关于框 DBVM 19、HypervisorPresent=True（注意这条单独不可靠）。\n\n判据：dbvm_initialize 返回 false 时，其他指标看起来对也不算成功。'],
];

const SESSION = [
  ['checkSessionAction 的第一道分流是什么',
    'S1：需要读分片（target 与 mode 都**没有显式传**）且缺 sessionKey → **直接 DENY**（fail-closed，去 default 共享）。\n\n而且 empty-action 优先拒。\n\n例外：显式传 target+mode 的纯判据用例不受影响（如任务态单测），仍按传入值判。\n\n判据：这条是"读盘前先验键"，避免无键读盘。'],
  ['host 不匹配时所有动作都拒吗',
    '不是，按动作分类（H1 门禁）：\n· **重锁/只读/补救类**（target-set / mode-set / mode-get / target-get / host-rebind / reverse-init）→ **ALLOW**，提示"先 host-rebind 再重锁"\n· **问询类**（STANDBY_ALLOW）→ **ALLOW**\n· **TASK_ONLY 类** → **DENY**（拒绝沿用他机状态件）\n· 其他 → DENY\n\n判据：他机件不是一律拒 —— 补救动作要放行，否则没法把它救回来。'],
  ['host 门禁什么情况下才查',
    '只有**分片读路径**才查。\n\n显式传参的纯判据用例（target 与 mode 都给了）**不查 host**。\n\n判据：单测里显式传值不会因为 host 不符而失败。'],
  ['为什么补救类动作要放行',
    '因为要让它有机会被救回来：\n· host-rebind 把宿主写回本机\n· target-get / mode-get 让调用方看清现状\n· target-set / mode-set 重锁\n\n如果补救类也拒，他机件就永远修不好。\n\n判据：放行后能 host-rebind → 重锁 → 恢复正常。'],
  ['STANDBY_ALLOW 是什么',
    '待命态允许的动作集合 —— 问询类。\n\n含义：即使在待命态、即使 host 不匹配，问询也不拦（看状态不需要写权限）。\n\n判据：问询类被拒就说明命中了别的规则（比如缺 key）。'],
  ['TASK_ONLY 命中时他机件为什么必须拒',
    '因为 TASK_ONLY 是"跑数/写道"类动作：OPEN / R / W / 扫描 / 反查 / kitty_ 工具 / trail-append / DBG_ / KM_。\n\n这些动作用他机的状态件执行，等于把数据写到错误的归属下。\n\n判据：`HOST-MISMATCH-DENY:该会话状态件属他机…先 host-rebind 写回本机 host 再重锁`。'],
  ['显式传 target 和 mode 的调用为什么绕过 host 检查',
    '因为它不读盘 —— 判据用的是你传入的值，跟"哪台机器"无关。\n\n这是为单测/纯函数用例留的口子。\n\n判据：生产路径应该走分片（不显式传），才能享受 host 保护。'],
  ['缺 key 和 host 不匹配哪个先判',
    '先判缺 key（S1 在 H1 之前）。\n\n顺序：empty-action → S1 缺 key DENY → H1 host 门禁。\n\n判据：两者都不满足时，报错是 SESSION-KEY-MISSING 而不是 HOST-MISMATCH。'],
  ['分片读和显式传参的判据结果会不一样吗',
    '会，这是设计：\n· 分片读：先验 key、再验 host，最严\n· 显式传参：只按传入值判，不走 host\n\n判据：同一动作两种调用方式结果可能不同 —— 排查时先确认走的是哪条路径。'],
];

for (const x of BOUNDARY) add('boundary', x[0], x[1], { topic: 'dbvm' });
for (const x of CHAIN) add('chain', x[0], x[1], { topic: 'dbvm' });
for (const x of PIT_A) add('pitfall', x[0], x[1], { topic: 'dbvm' });
for (const x of SESSION) add('session', x[0], x[1], { topic: 'session' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byKind = out.reduce((a, x) => (a[x.meta.__kind] = (a[x.meta.__kind] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_kind: byKind }, null, 1));

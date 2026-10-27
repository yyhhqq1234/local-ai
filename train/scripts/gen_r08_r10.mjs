#!/usr/bin/env node
/**
 * gen_r08_r10.mjs — R08 内核面 + R09 调试面 + R10 静态链
 *
 * 事实源（只读 DrCE）：
 *   tools/kernel-tools.ts  kitty_km：attach-once、pwrite 永久拒绝、read 降级 R、write 超时看门狗
 *                          kitty_dualview：KM_R 无回包降级 R 计数、samples≤20、250ms 间隔
 *   tools/channel-tools.ts kitty_dbg：accept_host_loss 硬闸门、DBG_ATTACH|iface|force|unsafe|async
 *   tools/static-tools.ts  kitty_patch：at 三形态、expect 拒写、in_place、fix_checksum、dry_run、KittyCE 白名单
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r08-r10-internal.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';
const ADDR = '0x7FF6DADB2450';
const PA = '0x1A4F2C00400';

const out = [];
const add = (round, kind, user, assistant, meta = {}) => out.push({
  id: `kitty-${round}-${kind}-${String(out.length).padStart(4, '0')}`,
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: q(user) },
    { role: 'assistant', content: assistant },
  ],
  meta: { __stage: 're', __kind: kind, __round: round, ...meta },
});
function q(s) { return s; }

// ==================== R08 内核面 ====================
const R08 = [
  ['attach-once 什么意思', `kitty_km 的 attach 做了 attach-once：如果目标 pid 和上次一样，**直接跳过**，不回包只说"跳过（attach-once 命中）"。\n\n原因：高频重复 KM_ATTACH 会诱发宿主丢失。\n\n调用：kitty_km action=attach pid=7412\n\n判据：看到"跳过"不是失败，说明内核对象已经打开着；要重新建立得先换目标或重启会话。`],
  ['pwrite 为什么一直被拒', `pwrite 是**全入口永久拒绝**，不是参数给错：\n· 门禁层先拒\n· 执行层纵深拒\n· accept 旗（accept_engine_wedge=true）**不再放行**\n\n实测原因：物理写会卡死 Lua 引擎（宿主活着但 tick 停摆），恢复只能重启宿主。\n\n返回固定是 \`ERR|KM_PW-DENIED:物理写永久拒绝…\`，同时落 logHostIncident('km-pwrite-blocked')。\n\n替代：取证走 pread（物理读）+ R/KM_R 对照；要改值走 W 或 kitty_wpb。`],
  ['内核读失败会怎样', `kitty_km action=read 失败时会自动**降级用用户态 R 兜底**，并在输出里写明"降级 R|…（KM失败只读降级，禁KM_PW/A-attach）"。\n\n含义：\n· 只读可以降级，写不行\n· 降级后拿到的是用户态视图，可能有 hook 干扰\n· 降级期间不要去碰 KM_PW 或 A 通道 attach\n\n判据：看到"降级"两字，这条读数的可信度要打折，需要对照就用 kitty_dualview 看三视图。`],
  ['内核写超时怎么办', `kitty_km action=write 超时不会静默失败，它会：\n1) 输出 \`[engine-wedge?] 调用未回包 → 跑看门狗确认/恢复\`\n2) 自动 ensureHost 重拉宿主 + PING\n3) 把看门狗的行一起返回\n\n所以 write 超时的正确处置是**看返回里的看门狗结果**，不要在外部再补一次写。\n\n判据：看门狗 ok 说明宿主救回来了，但这次写到底生效没有不确定 —— 必须重读验证。`],
  ['内核面各 action 的必填参数', `按实现逐条：\n· api —— 无必填\n· info —— 无必填\n· attach —— **pid 必填**，缺了回 \`ERR|attach 需要 pid\`\n· read —— **addr 必填**\n· write —— **addr 和 val 都必填**，且 confirm=true 才写\n· pa —— **addr 必填**\n· pread —— **pa 必填**\n· pwrite —— 永久拒绝（给了也拒）\n\n判据：这些缺参是在执行层直接返回 ERR|，不会发到桥，所以看到这类错不用怀疑通道。`],
  ['km 能做什么不能做什么', `能做：\n· 枚举内核可用面（api）\n· 看 PEProcess 是否可访问（info）\n· 内核态打开目标（attach）\n· 内核路由读写（read/write）\n· VA→PA（pa）、物理读（pread）\n\n不能做：\n· 物理写（pwrite 永久拒绝）\n· 当作调试器用（DBG_* 是另一套）\n· 替代用户态读写（KM 是**对照**手段，不是主路径）\n\n判据：内核面的定位是「验证用户态看到的是不是真的」，不是「绕过一切」。`],
  ['dualview 降级是什么意思', `kitty_dualview 每轮取三路：R / KM_R / KM_PR。如果 KM_R 没回包，它会：\n1) 计数 kmDegraded\n2) 用 R 再取一次当兜底\n3) 最后输出 \`降级 N/M 轮KM无回包→R兜底（只读降级，禁KM_PW/A-attach）\`\n\n含义：内核面这一轮不可用，三视图**退化成两视图**，分叉判据的可信度下降。\n\n判据：降级轮数 > 0 时不要下"无 hook"的结论，先修内核面再用。`],
  ['dualview 的 samples 怎么给', `samples 默认 1，上限 20，多轮之间固定间隔 250ms。\n\n给法：\n· 一次性判断 → 1\n· 怀疑间歇性分叉（race / 定时刷回）→ 5~10\n· 每多一轮就多 3 次往返（R + KM_R + KM_PA + KM_PR 约 4 次）\n\n判据：间歇问题必须多轮，单轮一致不能证明没问题。`],
  ['dualview 的证据落哪', `落 \`logs/anti-ace-<YYYY-MM-DD>.jsonl\`，每轮一行，字段：ts/addr/vt/pa/user/kernel/phys/fork/note。\n\n用途：事后复核用，尤其 fork=true 的行。note 参数会原样写进去。\n\n判据：交付对抗结论时要指到这个文件的具体行，不能只说"我看过了"。`],
  ['km 与 wpb 的分工', `两者都能碰物理层，但目的不同：\n\n· kitty_km：以**读**为主（PA 转换 + 物理读做对照），写被永久拒\n· kitty_wpb：以**写**为主（DTB→PTE→改 R/W→写入→还原），需要 accept_protection_bypass=true\n\n组合用法：先用 km pa/pread 看清物理页状态，再用 wpb 精确改一个字节，改完 km pread 复核。\n\n判据：要改就用 wpb，要验就用 km；不要试图用 km 写。`],
];
for (const [qi, ai] of R08) add('r08', 'kernel', qi, ai, { topic: 'kernel' });

// ==================== R09 调试面 ====================
const R09 = [
  ['kitty_dbg attach 报错说要 accept_host_loss', `这是硬闸门，不是提示。\n\n实现里：\n· attach 默认 standby，不主动挂\n· 桥侧 bridge 动作已经拒了 DBG_ATTACH\n· 必须 accept_host_loss=true 才继续\n· 实际发的是 \`DBG_ATTACH|<iface>|force|unsafe|async\`（双层闸门 + async）\n\n原因：本 build 的 debugProcess 会随机 0xc0000409 fail-fast **杀宿主**（F-13）。\n\n所以不传这个参数直接返回 \`ERR|attach 需显式 accept_host_loss=true…非必要请改走 C 通道 kitty_x64dbg\`。\n\n判据：真调试不该走这条路。`],
  ['真要调试该用什么', `用 C 通道 kitty_x64dbg，不用 A 通道的 kitty_dbg。\n\n选择表：\n· 只要看状态 → kitty_dbg action=status（安全）\n· 要下断点/看寄存器/单步 → kitty_x64dbg action=program 或 seed（C 通道，独立进程）\n· 要读日志 → kitty_x64dbg action=readlog / readdb\n· 要收集产物 → kitty_x64dbg action=collect\n\n判据：A 通道调试面的定位是「查状态」，不做真调试。`],
  ['DBG_WAIT 等多久', `有上限：实现里是 \`Math.min(wait_ms ?? 1500, 3000)\` —— 最多 3000ms。\n\n回包三态：\n· OK|attached — 已挂上\n· OK|attaching — 还在附加中，要短轮询\n· ERR|attach-failed:<e> — 失败，带原因\n\n判据：给 3000 以上没用，会被夹到 3000；附加慢的场景靠轮询而不是靠加大等待。`],
  ['下断点的参数怎么给', `kitty_dbg action=bp 发的是 \`DBG_BP|<addr>|<size>|<access>|<mode>|force\`。\n\n参数含义：\n· addr — 地址或 符号（如 kernelbase.CreateFileW）\n· size — 监视长度，默认 4\n· access — execute / write / access（默认 access）\n· mode — int3 / debug / exception（默认 debug）\n\n判据：回包带 pending 说明断点在异步建立，工具会自动补一次 DBG_WAIT|1500；没等到就是没设上。`],
  ['断点列表和删除', `· 列：kitty_dbg action=bp_list → DBG_BP_LIST\n· 删：kitty_dbg action=bp_del id=<n> → DBG_BP_DEL|<id>\n\n判据：删之前先 list 拿 id，别猜编号；删完再 list 确认没了。`],
  ['继续执行和单步', `kitty_dbg action=go 发 \`DBG_GO[|stepinto|stepover]\`，必须 confirm=true。\n\n· 不传 step → 正常继续\n· stepinto → 单步进入\n· stepover → 单步跳过\n\n判据：go 会让目标跑起来，回包不代表已停在新断点，要再 wait 或 status 看。`],
  ['收尾该做什么', `两步：\n1) kitty_dbg action=detach → DBG_DETACH\n2) kitty_dbg action=sync → SYNC_ARCHIVE + SYNC_STAT\n\n为什么要 sync：同步队列不归零，下一条指令可能顶到残留上。\n\n判据：SYNC_STAT 四项都不为 0 就是没清干净。`],
  ['A 通道调试和 C 通道的边界', `A 通道（kitty_dbg → DBG_*）：\n· 跑在 CE 进程内，附加会抢引擎锁\n· 本 build 会杀宿主\n· 适合查状态、列断点\n\nC 通道（kitty_x64dbg）：\n· 独立调试器进程，脚本驱动\n· 适合 program / seed / rununtil / collect\n· 参数用逗号分隔（x64dbg 命令语法）\n\n判据：任何"要停在某处看数据"的需求都走 C。`],
  ['调试面会不会影响性能', `会。附加期间 Cer 引擎锁会阻塞 tick ≤数秒，A 通道尤其明显。\n\n所以：\n· 不要在扫描/反查进行中 attach\n· 不要在循环作业里夹调试动作\n· 调试完立刻 detach\n\n判据：一边跑扫描一边调试，扫描的 pending 可能永远不落定。`],
  ['怎么确认调试器真的挂上了', `三层确认：\n1) kitty_dbg action=status → DBG_STAT|quick\n2) 回包里有 attached 字样\n3) 列一次断点（bp_list 有返回即通道通）\n\n判据：只要 status 说没挂，就别发 bp —— 断点会挂在空会话上，回包看着成功但永远不命中。`],
];
for (const [qi, ai] of R09) add('r09', 'debug', qi, ai, { topic: 'debug' });

// ==================== R10 静态链 ====================
const R10 = [
  ['补丁的五步顺序', `info → find → patch → hash（验证）→ 必要时 rollback。\n\n1) kitty_patch action=info path=<样本> —— 拿节表/入口/镜像信息\n2) kitty_patch action=find path=<样本> pattern="48 8B ?? 05" —— 定位偏移\n3) kitty_patch action=patch path=<样本> at=0x<偏移> expect="48 8B 05" bytes="31 C0 90" confirm=true\n4) kitty_patch action=hash path=<样本> —— 记改后哈希\n5) 出问题 kitty_patch action=rollback path=<样本>\n\n判据：跳步最常见的后果是打在错位置 —— 因为 find 会给多个命中，不核对就 patch 等于赌。`],
  ['expect 有什么用', `expect 是**拒写保护**：patch 前先校验目标位置的原字节，不匹配直接拒，不写。\n\n支持 \`??\` 通配（只校验关心的字节）。\n\n用法：\nkitty_patch action=patch path=<样本> at=rva:0x1234 expect="E8 ?? ?? ?? ??" bytes="90 90 90 90 90" confirm=true\n\n判据：expect 不匹配说明样本版本不对或偏移算错了 —— 这是保护你，不是障碍。`],
  ['at 的三种定位方式', `· \`0x<文件偏移>\` —— 直接文件偏移\n· \`va:0x<VA>\` —— 虚拟地址（工具会按节表换算）\n· \`rva:0x<RVA>\` —— 相对虚拟地址\n\n选法：\n· 从十六进制编辑器拿到的偏移 → 用 0x 形式\n· 从调试器/IDA 拿到的地址 → 用 va: 或 rva:\n\n判据：换算错了 expect 一定不匹配 —— 这也是用 expect 的理由。`],
  ['in_place=false 有什么好处', `true（默认）：直接改原文件，自动建 .bak 备份。\nfalse：写 \`<path>.patched\`，原文件一个字节不动。\n\n什么时候用 false：\n· 第一次打不确定的补丁\n· 要做 A/B 对比（原版 vs 补丁版）\n· 文件受保护/只读\n\n判据：不确定就 false，验证通过再 in_place=true 落原文件。`],
  ['fix_checksum 要开吗', `默认就是 true，一般不用改。\n\n它重算 PE 校验和，让文件看起来像"正常构建产物"。\n\n关掉的场景：\n· 你在做差分分析，需要字节级完全对应\n· 目标根本不校验 checksum（某些驱动/脚本宿主）\n\n判据：不确定就开着，关掉只在明确知道不用时。`],
  ['dry_run 什么时候用', `dry_run=true 只算不写：返回会做什么、命中哪里、新字节是什么，文件不动。\n\n用法：先 dry_run 看一遍，确认位置和字节对了再真打。\n\n判据：这是最便宜的纠错手段 —— 位置错在 dry_run 就能看出来，真打了还得 rollback。`],
  ['为什么拒绝补丁 KittyCE.exe', `这是内置白名单保护：补丁工具自己（KittyCE.exe）默认不许改，除非 force=true。\n\n原因：改了调试器本体，整条链路可能直接不可用，而且是不可逆的（连 rollback 都可能失败）。\n\n判据：真需要改就先复制一份改副本，不要动原件。`],
  ['find 的模式怎么写', `三种：\n· pattern="48 8B ?? 05" —— 十六进制，?? 是通配\n· str="CreateFileW" —— ASCII 字符串\n· str="..."utf16=true —— UTF-16LE 字符串\n\n配套：\n· limit —— 命中上限，默认 64\n· from / to —— 文件偏移范围\n\n判据：命中数正好等于 limit 说明被截断了，缩小范围或加更长的模式再找。`],
  ['rollback 靠什么', `靠原地补丁前自动建的 \`.bak\`。所以：\n· in_place=true（默认）+ backup=true（默认）→ 可 rollback\n· in_place=false → 没有 .bak，rollback 无从谈起（原文件本来就没改）\n· backup=false → 自己放弃了回滚能力\n\n判据：要可回滚就别关 backup。`],
  ['kitty_asm 怎么用', `两个 action：\n· assemble —— 多行汇编 → 机器码，支持标签和相对跳转修正\n· jump —— 单条跳转 → 字节，含 rel32 修正\n\n典型配合：算出 jmp 字节后用 kitty_patch 打进去。\n\n判据：跳转位移是相对当前地址算的，assemble 要给 base（承载地址），否则 rel 修正会错。`],
];
for (const [qi, ai] of R10) add('r10', 'static', qi, ai, { topic: 'static' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byRound = out.reduce((a, x) => (a[x.meta.__round] = (a[x.meta.__round] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_round: byRound }, null, 1));

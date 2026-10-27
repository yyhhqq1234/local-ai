#!/usr/bin/env node
/**
 * gen_r06_r07.mjs — R06 扫描族 + R07 指针链（事实源：ops-catalog.ts 的 S_ 与 P_ 族 + pchain-snippet.ts）
 *
 * R06 事实：S_NEW 窗≤16MB/总≤64MB/≤4窗；S_NEXT 超 PREV_CAP→ERR|too-big-rescan；
 *           S_CHANGED/S_UNCHANGED 快照随比对收窄；JOB_STAT 五态；MEMDUMP_HEX 有效≈3.2KB
 * R07 事实：窗口降级链（显式 > MODENUM size>0 > MODENUM+PE SizeOfImage > MODBASE+16MB）；
 *           双验证 rQword==parent && pWalk==parent；maxVerify 24/父、frontierCap 8、
 *           hitsPerParent 200、maxKeep 32；超限标 truncated
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r06-scan-r07-pchain.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const MOD = 'kitty-target.exe';
const BASE = '0x7FF6DADB0000';
const STOP16 = '0x7FF6DAEB0000';   // base+1MB
const ADDR = '0x7FF6DADB2450';

const out = [];
const add = (round, kind, user, assistant, meta = {}) => out.push({
  id: `kitty-${round}-${kind}-${String(out.length).padStart(4, '0')}`,
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: { __stage: 're', __kind: kind, __round: round, ...meta },
});

// ============ R06 扫描族 ============
const R06 = [
  { q: '我要按已知值 3500 扫血量，区间怎么给？',
    a: `区间必须显式给，S_NEW 不接受"只给值自动全扫"。\n\n先拿窗口：\nkitty_ce op=MODENUM\n\n再扫：\nkitty_ce op=S_NEW|dword|3500|${BASE}|${STOP16}\n\n限额（硬约束）：\n· 单窗 ≤16MB\n· 总窗 ≤64MB\n· 最多 4 窗\n\n回包是 \`OK|scan|range|<n>w|<desc>[|pending]\`。带 pending 说明还在跑，等 JOB_STAT 落定再取结果，不要重复投。\n\n判据：区间缺了直接回 ERR|need-range，不要靠重试解决。` },
  { q: 'S_NEW 回来 ERR|need-range，我明明给了 start 和 stop',
    a: `给了区间还报 need-range，是**超限额**不是没给。\n\n三个数对一下：\n· 单窗是不是 >16MB（${BASE}~${STOP16} 是 1MB，没问题）\n· 累计是不是 >64MB（多窗累加，不是每窗单独算）\n· 窗数是不是 >4\n\n修法：按模块实际 size 切，别用整个地址空间。MODENUM 的 size 可能为 0（自研靶标实测会），这时要用镜像头 SizeOfImage 推窗口。\n\n判据：改小窗口再发，还是 need-range 才说明参数格式错了（比如 0x 前缀或十进制混用）。` },
  { q: '第一次扫出 1200 个候选，接下来怎么收窄？',
    a: `两种收敛法，按"值变不变"选。\n\n**值会变**（血量、坐标）→ 变值收敛：\n1) 记下当前值：kitty_ce op=S_COUNT\n2) 让目标里的值变化（掉血/移动）\n3) kitty_ce op=S_NEXT|dword|<新值>\n   —— S_NEXT 是交集重扫，只在新值里保留原候选\n\n**值未知**（刚开局不知道初始值）→ 快照收敛：\n1) kitty_ce op=S_SNAP|dword|${BASE}|${STOP16}|20000\n2) 值变化后 kitty_ce op=S_CHANGED\n3) 没变的用 op=S_UNCHANGED\n4) 交替 S_CHANGED / S_UNCHANGED 逐轮收窄\n\n关键语义：快照会随每次比对收窄（CE 语义），所以不能拿第一次的快照反复比。\n\n判据：候选降到个位数再取 S_GET 拉地址，别一开始就拉全表。` },
  { q: 'S_NEXT 报 ERR|too-big-rescan',
    a: `说明这一轮要重扫的范围超过了 PREV_CAP。\n\n成因：上次的候选集太大（上千），S_NEXT 要在里面做交集，超了就拒。\n\n处置顺序：\n1) 先 S_COUNT 看当前候选数 —— 上千就是没收敛够\n2) 收窄窗口（只扫数据段，别扫整个模块）\n3) 或者换更具体的值再 S_NEW 一次，而不是在烂候选集上硬 S_NEXT\n\n判据：too-big-rescan 是"候选集太大"的信号，不是参数错。` },
  { q: 'S_GET 怎么取？一次能拿多少？',
    a: `S_GET|<start0>|<count>，注意 **start 是 0 基偏移**，不是地址。\n\n取前 20 条：kitty_ce op=S_GET|0|20\n取 20~40：kitty_ce op=S_GET|20|20\n\n回包是多行：首行 \`OK|<n>\`，之后每行一个地址。\n\n判据：想取全部就看 S_COUNT 的数，分批拿；一次拿几千条会截断，还可能拖慢通道。` },
  { q: '扫完不释放会怎样？',
    a: `会一直占着上一次的候选集，下一次扫描顶着旧状态跑，结果不可信。\n\n清理：\n· kitty_ce op=S_FREE —— 清扫描状态（正常收尾）\n· kitty_ce op=S_ABORT —— 中断正在跑的扫描\n\n判据：每次扫描会话结束（不管成没成）都要 S_FREE；中断场景用 S_ABORT + S_FREE 两步。` },
  { q: 'JOB_STAT 回的状态有几种，怎么读？',
    a: `五种：none / no-job / running / done / error。\n\n读法：\n· none、no-job → 没有作业在跑，可以直接发新指令\n· running → 等，别重复投（重复投会顶掉上一条）\n· done → 取结果（S_GET 或 P_BACK_RES）\n· error → 看同回包里的错误信息，修参数再发\n\n回包形态：OK|<state>|kind=…|mode=…|n=…|wi=…|age_ms=…\nage_ms 能看出跑了多久，太长就考虑缩窗口。\n\n判据：只要不是 done，就不要取结果；取到的是上一次的残留。` },
  { q: 'MEMDUMP_HEX 想导 8KB 出来看，行不行？',
    a: `不行，len 上限 4096。而且回包本身还有 ≤200 行限制 —— 16 字节一行的话有效约 3.2KB，给了 4096 也会被回包截断。\n\n稳妥做法：分段导\nkitty_ce op=MEMDUMP_HEX|${ADDR}|2048\nkitty_ce op=MEMDUMP_HEX|0x7FF6DADB2C50|2048\n\n判据：看到回包尾部有截断迹象（行数正好 200）就说明还有没导完的，按地址续。` },
  { q: 'RANGE_INFO 是干什么的，什么时候用？',
    a: `它给的是**分配窗**和靶标提示，回包 \`OK|target=…|alloc_windows=…|note=S_NEW_requires_explicit_range\`。\n\n用它的时机：不确定该扫哪个区间时，先用它看进程里有哪些可扫描的分配窗，比自己猜一个范围稳。\n\n判据：alloc_windows 给出的就是合法区间来源；note 里那句是在提醒 S_NEW 必须显式区间。` },
  { q: '扫描族一共几个 OP，各管什么？',
    a: `12 个：\n· S_NEW —— 按值开扫（必显式区间，窗≤16MB/总≤64MB/≤4窗）\n· S_COUNT —— 进度或结果计数\n· S_GET —— 取命中（start 为 0 基偏移）\n· S_NEXT —— 交集重扫（超 PREV_CAP → too-big-rescan）\n· S_SNAP —— 未知初值快照（cap≤20000）\n· S_CHANGED / S_UNCHANGED —— 与上次快照比对，交替收敛\n· S_FREE —— 清状态\n· S_ABORT —— 中断\n· JOB_STAT —— 作业落定判据（五态）\n· RANGE_INFO —— 分配窗提示\n· MEMDUMP_HEX —— 原始字节（len≤4096，有效≈3.2KB）\n\n判据：值已知走 S_NEW→S_NEXT，值未知走 S_SNAP→S_CHANGED/UNCHANGED，两条路的收尾都是 S_FREE。` },
  { q: '扫出 800 个候选，想直接全拿到内存里自己算，可以吗？',
    a: `不建议，两条路都不划算。\n\n· S_GET 分批拉：800 条要发 40 次（每次 20 条），每次一个往返，慢且容易撞回包截断。\n· 直接读内存自己筛：多一次 800 次读的开销，比扫描本身还贵。\n\n正确做法是先收敛：再变一次值跑 S_NEXT，或缩小窗口重扫，把候选压到个位数再取。\n\n判据：候选数 > 50 就不该往下走，先想办法收敛。` },
  { q: 'S_SNAP 的 cap 给多少合适？',
    a: `cap ≤ 20000，它决定单次快照取多少个地址做样本。\n\n给值的权衡：\n· 给小（如 2000）→ 快，但可能漏掉目标\n· 给大（20000）→ 覆盖好，但慢且占内存\n\n默认按窗口大小算：1MB 窗口给 20000 就够密了；更大窗口要分窗做。\n\n判据：快照回包带 \`|truncated\` 就说明 cap 到了上限被截，要分窗。` },
];

for (const x of R06) add('r06', 'scan', x.q, x.a, { topic: 'scan' });

// ============ R07 指针链 ============
const R07 = [
  { q: '血量地址拿到了，用 kitty_pchain 找指针链，参数怎么给？',
    a: `kitty_pchain target=${ADDR} depth=2 mod=${MOD}\n\n可选参数与默认值（实现里的真值）：\n· max_verify=24 —— 每跳最多验证 24 个候选（旧实现无限，最坏 200/父）\n· frontier_cap=8 —— 每跳前沿上限 8 个父地址\n· max_keep=32 —— 命中达 32 提前收口\n· start/stop —— 显式窗口，不给就自动解析\n\n它内部做的事：\n1) 解析窗口（降级链见下一条）\n2) P_BACK 反查谁指向目标（命中上限 200）\n3) 每个候选做**双验证**：读它的值 == 父地址 且 P_WALK 回验也 == 父地址\n4) 落在模块窗口内的记为 STATIC 进前沿，窗口外的进 droppedStack\n5) 逐跳重复，直到 depth 用完或前沿为空\n\n判据：结果里 keep 是可用链，droppedStack 是栈上指针（重启失效），droppedBad 是验证没过的。` },
  { q: 'pchain 的窗口是怎么定的？如果 MODENUM 拿不到 size 呢？',
    a: `降级链四级（实现原文）：\n1) **显式 start/stop** —— 你给了就用你的\n2) **MODENUM 且 size>0** —— 用 base~base+size\n3) **MODENUM base + 镜像头 SizeOfImage** —— size=0 时的兜底\n4) **MODBASE + 16MB 兜底** —— MODENUM 完全没命中的最后手段\n\n为什么需要第 3 级：CE 的 MODENUM 对部分模块（实测自研靶标）返回 **size=0**，直接用就会得到空窗口。\n\n判据：结果 stats.window.source 会告诉你用了哪一级 —— 看到 \`MODENUM+PE\` 说明走了兜底，\`MODBASE-fallback\` 说明模块名可能写错了。` },
  { q: '为什么 P_BACK 老报 need-range？我给了地址',
    a: `P_BACK 的签名是 \`P_BACK|<addr>|<start>|<stop>\` —— **三个参数，后两个是窗口，不是可选**。\n\n只给地址的旧写法一律 ERR|need-range，这是桥契约，不是 bug。\n\n正确：\nkitty_ce op=P_BACK|${ADDR}|${BASE}|${STOP16}\n\n然后取结果：\nkitty_ce op=P_BACK_RES|200\n\n判据：P_BACK 命中上限就是 200，超了要缩窗口而不是加窗口。` },
  { q: 'P_BACK 回了 OK|<n>|pending 是什么意思？',
    a: `这是**作业化**回包：反查被放到后台跑，n 是当前已知命中数，pending 表示还没落定。\n\n处理：\n1) kitty_ce op=JOB_STAT —— 轮询到 done\n2) kitty_ce op=P_BACK_RES|200 取结果\n\n注意：pchain 内部已经做了这个等待（waitJobByCall），所以你手动跑时要自己等。\n\n判据：pending 期间取 P_BACK_RES 拿到的是上一次的残留表，不是这次的。` },
  { q: 'pchain 结果里 droppedStack 是什么？能直接用吗？',
    a: `droppedStack 是**验证通过但落在模块窗口外**的候选 —— 通常是栈上的指针。\n\n为什么单独放：栈地址每次启动都变，这类链不可复用（重启后失效）。\n\n能不能用：\n· 单次会话内用 → 可以，但重启就废\n· 要做稳定链 → 不能用，只能沿 STATIC（模块内）那条走\n\n判据：交付指针链时说清楚"模块基址+偏移"才是稳定形态；只给绝对地址的链等于没交付。` },
  { q: 'pchain 结果 truncated=true 意味着什么？',
    a: `意味着**有候选没验完就停了**，结果可能不完整。四种触发点（实现里都会往 notes 写）：\n\n1) 某父命中数 > 200（hitsPerParent）→ 只取前 200\n2) 某父验证数达 24（maxVerify）→ 剩余候选没验\n3) 命中数达 32（maxKeep）→ 提前收口\n4) 前沿达 8（frontierCap）→ 不再扩\n\n怎么处理：\n· 看 notes 里是哪一条触发的\n· 命中太多 → 缩窗口重跑，别加大上限\n· 验证不够 → 说明候选噪声大，先确认目标地址有没有找错\n\n判据：truncated=true 时不要声称"找到唯一链"。` },
  { q: 'pchain 一次要跑多久？会不会很慢？',
    a: `看 stats.calls 和 stats.ms —— 结果里都给了。\n\n量级参考：\n· 每跳每个候选要 2 次往返（读值 + P_WALK）\n· 单跳最坏 24 候选 × 2 = 48 次往返\n· 旧实现不限验证数，最坏 ≈3200 次往返/跳\n\n提速手段：\n1) depth 从 2 开始，不要一上来给 4~5\n2) 窗口给紧一点（只给模块实际范围，别给 16MB 兜底）\n3) max_keep 调小，够用就停\n\n判据：ms 超过 30 秒就该怀疑窗口太大或候选太脏。` },
  { q: '找到链之后怎么验证它真的稳定？',
    a: `pchain 只保证"当前会话内双验证通过"，稳定性要你自己验。\n\n三步：\n1) 重启目标进程\n2) 重新拿模块基址（MODENUM，ASLR 会变）\n3) 按 基址+偏移 重算，看能不能读到原本的值\n\n判据：\n· 重启后同偏移读到的值合理 → 链稳定\n· 读到别的值/读不到 → 这条链依赖了栈或堆，不能用\n\n这也是为什么交付物必须是"模块+偏移"而不是绝对地址。` },
  { q: 'P_WALK 回 ERR|no-target 怎么理解？',
    a: `P_WALK|<addr>|<offset> 的语义是：从这个地址出发，按偏移走一跳，看落点。\n\nERR|no-target 表示走完这一跳**没落到有效目标**，通常是：\n1) 这个候选根本不是指针（值虽然是父地址，但结构不对）\n2) offset 给错了\n3) 中间那层地址已被释放/换了\n\n处置：换下一个候选，不要在这个上面反复试不同 offset。\n\n判据：pchain 内部把这种情况归到 droppedBad，你手动跑时也该这么归类。` },
  { q: '一次反查命中 200 个，怎么收敛？',
    a: `200 是桥的硬上限，收敛靠**缩窗口**不是加参数。\n\n三个方向：\n1) 窗口从整个模块缩到数据段（地址范围更紧，无关指针自然排除）\n2) depth 先给 1，只找直接父，别一次追多跳\n3) 用 pchain 的区域过滤：它只把 STATIC（模块内）的候选往前推，堆栈候选自动分到 droppedStack\n\n判据：命中正好 200 且 notes 说"已截断"，说明窗口给太宽，缩一半再跑。` },
];

for (const x of R07) add('r07', 'pchain', x.q, x.a, { topic: 'pchain' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const kinds = out.reduce((a, x) => (a[x.meta.__round] = (a[x.meta.__round] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_round: kinds }, null, 1));

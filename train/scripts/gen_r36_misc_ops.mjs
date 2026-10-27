#!/usr/bin/env node
/**
 * gen_r36_misc_ops.mjs — R36 补齐 18 个零覆盖 OP
 *
 * 事实源：ops-catalog.ts 的 VER / LP / DIS / THREADS / SPEED / CT_SAVE / CT_LOAD / KM_PROBE / AL_*
 *
 * 分组：
 *   查询类  VER / LP / THREADS / DIS
 *   控制类  SPEED / KM_PROBE
 *   持久化  CT_SAVE / CT_LOAD（含中文路径坑）
 *   地址表  AL_ADD / AL_DEL / AL_GET / AL_COUNT / AL_CLEAR / AL_SET_VAL / AL_SET_ACT / AL_SET_TYPE / AL_SET_DESC
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r36-miscops.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (kind, user, assistant, meta) => out.push({
  id: 'kitty-r36-' + kind + '-' + String(out.length).padStart(4, '0'),
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: Object.assign({ __stage: 're', __kind: kind, __round: 'r36' }, meta || {}),
});

const ADDR = '0x7FF6DADB2450';

// 查询类
add('query', '怎么确认桥的版本号',
  'kitty_ce op=VER\n\n回包：`OK|<ver>`。\n\n和 BRIDGE_VER 的区别：VER 是通用版本查询，BRIDGE_VER 是桥契约版本（T1 冻结，如 v0.2.9-open-name-resolve-fixed）。\n\n判据：查契约兼容性看 BRIDGE_VER；查运行版本看 VER。', { topic: 'query' });

add('query', '要给目标列表但 CUR 只给当前一个',
  'kitty_ce op=LP\n\n回包：`OK|<n>` 然后每行 `<pid-hex>|<name>`，**上限 200 行**。\n\n用途：不确定进程名/pid 时先列出来，再 OPEN。\n\n判据：正好 200 行说明被截断，用名字过滤而不是翻页（没有翻页语义）。', { topic: 'query' });

add('query', '想看目标有哪些线程',
  'kitty_ce op=THREADS\n\n回包：`OK|<n>` 然后每行一个 tid，**上限 200**。\n\n用途：\n· 判断目标是不是多线程（影响断点/注入策略）\n· 找特定 tid 做线程级操作\n\n判据：线程数异常多（几百）通常是运行时/GC 线程，不是业务线程。', { topic: 'query' });

add('query', '要在某个地址看一条反汇编',
  'kitty_ce op=DIS|' + ADDR + '\n\n回包：`OK|<文本>`（单条，**没有范围参数**）。\n\n限制：一次只反一条，要连续看就自己加指令长度往后推。\n\n判据：想看一段就用 kitty_ghidra / kitty_ida 反编译，别用 DIS 循环拼。', { topic: 'query' });

// 控制类
add('control', '想给目标加速',
  'kitty_ce op=SPEED|<倍率>\n\n回包：`OK`。\n\n注意：这是 CE 的 speedhack，改的是**时间流速**不是 CPU 频率。\n\n判据：加速后逻辑行为会变（动画/计时/冷却都按倍率走），测试完记得恢复 1.0。', { topic: 'control' });

add('control', 'KM_PROBE 是干什么的',
  'kitty_ce op=KM_PROBE → 回包 `OK|…`\n\n它是**探针**（dbk 初始化面），用来确认内核面能不能通，不是真正的初始化动作。\n\n和 KM_API 的区别：KM_API 枚举 dbk_* 可用面，KM_PROBE 只探一下。\n\n判据：探针通不代表内核路由可用，要看 KM_INFO 的 PEProcess。', { topic: 'control' });

// 持久化
add('persist', '想把地址表存成文件',
  'kitty_ce op=CT_SAVE|<文件名>\n\n回包：`OK|saved|<名>`，写进 `kitty\\` 目录。\n\n**关键坑**：中文路径必须用这条，别用 LUA 的 io.open —— Lua 侧对中文路径编码处理会失败。\n\n判据：存完到 `kitty\\` 目录确认文件在，大小非 0。', { topic: 'persist' });

add('persist', 'CT_SAVE 和 CT_LOAD 的区别',
  '· `CT_SAVE|<文件名>` → `OK|saved|<名>`，写 kitty\\ 目录\n· `CT_LOAD|<文件名>` → `OK|loaded|<名>`，从 kitty\\ 目录读\n\n两者路径语义相同（都在 kitty\\ 下，只给文件名不给全路径）。\n\n判据：中文文件名走这两条，不要走 LUA io.open。', { topic: 'persist' });

add('persist', '为什么不能用 LUA 的 io.open 写中文路径',
  '已知坑：Lua 侧对中文路径的编码处理与桥不一致，io.open 会失败（报找不到或乱码）。\n\n正确做法：中文路径用 `CT_SAVE|<文件名>` / `CT_LOAD|<文件名>` —— 桥侧做了编码处理。\n\n判据：LUA 里写文件失败但 CT_SAVE 成功 = 就是这个坑。', { topic: 'persist' });

// 地址表族
add('addrlist', '地址表怎么加一条',
  'kitty_ce op=AL_ADD|<描述>|<addr>|<type>\n\n例：\nkitty_ce op=AL_ADD|血量|' + ADDR + '|dword\n\n回包 `OK|…`。\n\ntype 取值同 vt（byte/word/dword/qword）。\n\n判据：加完用 AL_COUNT 确认条数变了。', { topic: 'addrlist' });

add('addrlist', '怎么看地址表有多少条',
  'kitty_ce op=AL_COUNT → 回包 `OK|<n>`（实测空表回 `OK|0`）。\n\n判据：AL_ADD 之后条数应该 +1；没变说明那条没加进去（看 AL_ADD 的完整回包）。', { topic: 'addrlist' });

add('addrlist', '怎么取地址表里的某一条',
  'kitty_ce op=AL_GET|<index>\n\nindex 是 0 基还是 1 基要看实回：先 AL_COUNT 拿总数，再试 AL_GET|0 和 AL_GET|1 对比。\n\n判据：越界会报错；取不到就先用 AL_COUNT 确认总数。', { topic: 'addrlist' });

add('addrlist', '怎么删地址表里的一条',
  'kitty_ce op=AL_DEL|<index>\n\n坑：删完后续 index 会顺移（列表语义），所以批量删要从**大到小**删。\n\n判据：删完 AL_COUNT 应该 -1；批量删完再 COUNT 核对。', { topic: 'addrlist' });

add('addrlist', '怎么清空地址表',
  'kitty_ce op=AL_CLEAR\n\n用途：开始新一轮分析前清干净，避免旧条目干扰。\n\n判据：清完 AL_COUNT 回 `OK|0`。', { topic: 'addrlist' });

add('addrlist', '怎么改地址表某条的值',
  'kitty_ce op=AL_SET_VAL|<index>|<val>\n\n它改的是**地址表里记录的目标值**（CE 会把值写下去），不是改描述。\n\n判据：改完用 AL_GET 看回包里的值字段。', { topic: 'addrlist' });

add('addrlist', '怎么启用/禁用某条',
  'kitty_ce op=AL_SET_ACT|<index>|<on|off>\n\n用途：临时停掉某条（不删），比如调试时先禁掉一个改写，看行为变化。\n\n判据：AL_GET 里 active 字段跟着变。', { topic: 'addrlist' });

add('addrlist', '怎么改某条的类型',
  'kitty_ce op=AL_SET_TYPE|<index>|<type>\n\ntype 同 vt：byte/word/dword/qword。\n\n坑：改类型不会自动重读，值可能显示成错的 —— 改完重新 AL_GET 或触发一次读。\n\n判据：改 dword→qword 后值的高 4 字节才有意义。', { topic: 'addrlist' });

add('addrlist', '怎么改某条的描述',
  'kitty_ce op=AL_SET_DESC|<index>|<描述>\n\n用途：给自己看的标签，不影响读写行为。\n\n判据：AL_GET 里 description 变了。', { topic: 'addrlist' });

add('addrlist', '地址表这一族一共几个 OP',
  '九个：\n· AL_ADD —— 加一条（描述 + 地址 + 类型）\n· AL_DEL —— 按 index 删\n· AL_GET —— 按 index 取\n· AL_COUNT —— 条数\n· AL_CLEAR —— 清空\n· AL_SET_VAL —— 改记录值\n· AL_SET_ACT —— 启用/禁用\n· AL_SET_TYPE —— 改类型\n· AL_SET_DESC —— 改描述\n\n判据：这族操作的是 CE 的地址列表（持久化用 CT_SAVE/CT_LOAD）。', { topic: 'addrlist' });

add('addrlist', '地址表和扫描结果有什么区别',
  '· **扫描结果**（S_NEW/S_GET）是临时的候选集，S_FREE 就没了\n· **地址表**（AL_*）是**人工整理过的持久列表**，可以 CT_SAVE 落盘\n\n典型流程：扫描收敛 → 挑出确定的那几个 → AL_ADD 进地址表 → CT_SAVE 存下来。\n\n判据：要跨会话保留就用 AL_*，不要指望扫描结果。', { topic: 'addrlist' });

add('addrlist', '批量删地址表要注意什么',
  '**从大到小删**，因为 AL_DEL 按 index 删完之后后续条目会顺移。\n\n反例：想删 0/1/2 三条，从 0 开始删 → 删完 0，原来的 1 变成 0，你再删 1 删的是原来的 2。\n\n判据：删完 AL_COUNT 要等于"原数 - 删掉的条数"。', { topic: 'addrlist' });

add('addrlist', 'AL_* 报通配是什么意思',
  'ops-catalog 里 `AL_*` 是**通配条目**，代表这一族（不是一条具体 OP）。\n\n总 OP 数 66 = 桥 65 + 通配 1 —— 那个通配就是它。\n\n判据：算 OP 总数时别把 AL_* 当成额外一条具体指令。', { topic: 'addrlist' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byKind = out.reduce((a, x) => (a[x.meta.__kind] = (a[x.meta.__kind] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_kind: byKind }, null, 1));

# -*- coding: utf-8 -*-
"""re-op-semantics 源 part B (16-30)。"""

OP_B = [
(
"JOB_STAT 一直显示 pending，我怎么判断它是卡了还是还在跑？",
"""看 JOB_STAT 的 state 与 n 两个字段的变化趋势，别只看一次。

判定：
kitty_ce op=JOB_STAT
判读：回包形如 OK|<state>|kind=<类型>|n=<命中数>。
- state=running 且 n 在增长 → 正常推进，继续等；
- state=running 且 n 连续三次不变 → 大区间里值稀少，进程仍在逐页走，等；
- state=done → 落定，去 S_GET 取样；
- 无回包/超时 → 桥层问题，不是作业问题。

工程做法（省掉手搓轮询）：
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" wait=true top=20
判读：wait=true 会替你轮询 JOB_STAT 直到落定并直接取样本，
比手工 for 循环稳，也不会因为轮询过密把桥打满。

卡死的真症状（与慢区分）：
1) 连续 30s 以上 n 不变且 state 仍 running；
2) kitty_ce op=PING 也超时；
判读：这时才是桥/宿主问题，走 kitty_drv action=host 看门狗，
不要在作业层面反复重试 —— 重试会叠加 pending 任务。

退出条件：拿到 state=done + 样本，或确认 PING 也挂（转宿主自愈）。
事后收尾用 SYNC_ARCHIVE + SYNC_STAT 确认四项归零。""",
),
(
"SYNC_STAT 四项是什么，为什么要它归零？",
"""四项是桥的内部计数器（待处理/待投递/异常/归档残留），归零代表通道干净。

查：
kitty_ce op=SYNC_STAT
判读：四项全 0 = 无残留；任一非 0 说明上一轮有指令没走完（常见于作业被中断）。

归一化：
kitty_ce op=SYNC_ARCHIVE
判读：把已完成/已中断的记录归档到 sync 目录，计数随之回落。
再跑一次 kitty_ce op=SYNC_STAT 确认。

为什么要逼到 0：
1) 残留会污染下一轮 JOB_STAT（把上一轮的命中算进本轮 n）；
2) 归档目录不清理会让 kitty_status 的 pending 数失真，误判「桥挂了」；
3) 写操作中断后未归零，回滚记录可能丢，后续无法证明「已还原」。

什么情况下容许非 0：
只有「作业仍在 running」时容许 pending 非 0，此时不要强行 ARCHIVE，
等落定后再归一。强归档会把正在写的记录截断。

落判据：每轮实验收口三件套 —
kitty_ce op=SYNC_ARCHIVE → kitty_ce op=SYNC_STAT（四项 0）→ kitty_status 复核 pending=0。
三项不齐不许开下一轮，否则后面所有计数都不可信。""",
),
(
"我想一次读 8KB 连续字节，MEMDUMP_HEX 会不会截断？",
"""会，单次上限 4096 字节，超了要么拒要么截，必须分块并按偏移拼。

正确做法：
kitty_ce op="MEMDUMP_HEX|0xSTART|4096"
kitty_ce op="MEMDUMP_HEX|0xSTART+4096|4096"
判读：每块独立回十六进制串，按顺序拼接即完整 8KB。
回包长度校验：每块应给 4096*2 个十六进制字符（含分隔符另算），
短了说明该块跨页边界被截。

跨页注意：
kitty_ce op="R|0xSTART+4090|bytes:12"
判读：若读失败，说明 0xSTART+4096 落在未映射页，
先用 kitty_prot action=query addr=0xSTART+4096 确认可读性，再决定是否续读。

替代（更省桥调用）：
kitty_ce op="LUA|local a=readBytes(0xSTART, 8192) if a then return string.format('%02X',a[1]) end"
判读：LUA 里可一次取更多，但返回会被截到 8192 字符，所以取回来只适合做「是否为零页」这类布尔判断。

退出条件：拼接后总长 == 期望长度；
若小于期望，按 query 结果把区间裁到可读边界内，并记录被裁掉的尾部。""",
),
(
"我写的 OP 里地址带了尖括号，桥直接拒了。占位符该怎么传？",
"""桥只认字面量：十六进制地址必须 0x 前缀 + 纯数字，尖括号占位符是我在写文档时用的，
落到实际 OP 前必须先替换成真实值。

替换规则：
- 0xADDR → 真实 VA，如 0x7FF6DADB1000；
- 0xBASE → MODENUM 回的 base；
- 0xSTART / 0xSTOP → 必须是算好的绝对地址，不是「基址+偏移」表达式。

表达式也不行：
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1000" 会被拒。
正确做法是自己算出 0x7FF6DADB1000 与 0x7FF6DADB2000 再传。

批量时用 BATCH 逐条替换：
kitty_ce ops=["R|0x7FF6DADB1000|dword","R|0x7FF6DADB2000|dword"]
判读：一次投递多条，各自独立回包；任一条拼错只影响那一条，不会整批失败。

参数校验做得对的地方：
桥在读 OP 时会先做本地校验（类型/段数/十六进制格式），
判读：回「拼错 OP」类本地拒绝时不要重试同样字符串，
先用 kitty_ops filter=<OP名> 看签名与段数要求，再重写。

退出条件：所有 OP 里不再出现尖括号与算术表达式，且每条段数与 kitty_ops 一致。""",
),
(
"同一个地址我想同时看四视图（用户/内核/物理/PTE），有现成工具吗？",
"""三视图有现成的（kitty_dualview），PTE 那层要自己补一步。

三视图：
kitty_dualview addr=0xADDR vt=dword samples=3 note=baseline
判读：每条采样给 R / KM_R / KM_PA+KM_PR 三路值，
任一路不同即判「视图分叉」，自动落 logs/anti-ace-<date>.jsonl。

补 PTE 层：
kitty_km action=pa addr=0xADDR
判读：给出物理地址 PA。有了 PA 就能直接读物理：
kitty_km action=pread pa=0xPA vt=dword
判读：物理值与 KM_R 一致 = 内核路由没有过滤；不一致 = 内核层有拦截。

一键取证（要完整证据包时）：
kitty_acescan target=<pid> vt=dword samples=3 writeback=true
判读：它串起 宿主探活 → OPEN → KM_ATTACH(attach-once) → 三视图门禁 → 写回环 → 证据包，
输出 logs/acescan-<ts>.{jsonl,json}。
判据：门禁 green + 写回环全通 = 该目标当前无拦截面；任一轮分叉或内核写被吞 = 存在拦截。

不要做：
KM_PW（物理写）已永久拒绝，实测卡死 Lua 引擎；物理侧只读，写一律走内核路由或 PTE 直改。""",
),
(
"P_BACK 命中 200 条上限，我不加窗口会不会自己收敛？",
"""不会。200 是硬上限，命中到上限时回包只给「前 N 条」，不保证覆盖全部，
也不会因为候选多就自我收敛 —— 收敛靠你缩窗口。

症状：
kitty_ce op="P_BACK|0xTARGET|0xSTART|0xSTOP"
判读：回 ERR|TOO_MANY_HITS|200 或恰好 200 条 → 判定窗口过大，不是数据问题。

三步缩窗：
1) 定位容器：
kitty_prot action=query addr=0xTARGET
判读：拿 AllocationBase 与 RegionSize，窗口改到这块。
2) 分片重查：
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x10000"
判读：每片 64KB，命中通常 0~5 条，逐片推进直到出现非零片。
3) 只保留有命中的片继续上跳：
kitty_ce op="P_BACK_RES|20"
判读：取结果样本，逐条 kitty_ce op="R|0xCAND|qword" 回验。

经验判据：x64 下窗口给 4MB 以上基本必打满；
正确窗口的典型量级是「单个结构体数组」——几十 KB 到几百 KB。

退出条件：某跳命中 ≤20 且 R 回验通过；
若缩到 64KB 仍打满，说明目标地址是高频共享值（如 0 或页对齐指针），换判据 ——
改扫「指向容器的指针」而不是目标地址本身。""",
),
(
"扫描前我该不该先 S_FREE？不 free 会怎样？",
"""不该无脑 free，但换窗口/换类型前必须 free —— 状态是单例的。

状态语义：
S_NEW / S_SNAP 会在桥里维护一份扫描状态（区间 + 结果集）。
判读：再来一次 S_NEW 会覆盖状态，不报错但不保留旧结果。

什么时候必须 S_FREE：
1) 换 vt（dword→bytes:4）：长度不同，旧状态会误导取样；
2) 换窗口（模块→堆）：S_GET 的索引含义变了；
3) 开新一轮实验：避免上一轮残留被当成本轮命中。

什么时候不必：
连续在同窗口内 S_CHANGED / S_UNCHANGED 收窄 —— 这正是状态的价值，free 掉就白扫了。

自动化时用 auto_free：
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" auto_free=true top=20
判读：取完样本自动 S_FREE，适合「一次性扫描」；需要后续 S_CHANGED 时不要开。

收尾：
kitty_ce op=S_FREE
判读：回 OK 后再跑 SYNC_STAT 看四项是否归零，
非 0 说明扫描状态没彻底释放，补一次 S_FREE 再归零。""",
),
(
"读 4 字节和读 bytes:4 有区别吗？我按哪个判断可读性？",
"""有区别：前者按类型取值，后者按原始字节；可读性判断要看前者（它走的是严格的类型读路径）。

类型读：
kitty_ce op="R|0xADDR|dword"
判读：成功回十进制；地址不可读时明确失败。这是判断「能不能读」的权威路径。

字节读：
kitty_ce op="R|0xADDR|bytes:4"
判读：回十六进制字节串。跨页尾部可能被缩短而不报错 —— 也就是说它「成功」不代表整 4 字节都可读。

判断可读性应当：
kitty_prot action=query addr=0xADDR
判读：返回 State=COMMIT 且 Protect 不含 NOACCESS 才叫可读；
再加一次类型读确认（状态可读但页可能被 guard）。

对齐的坑：
kitty_ce op="R|0xADDR+1|dword"
判读：x86 允许多数未对齐读，但某些保护页会把整页标 guard，
跨页未对齐读会触发 guard 而失败 —— 这时先用 bytes:2 分段读再拼。

落判据：可读性判据 = query 的 State/Protect + 类型读成功；
需要原始字节（比对签名、看字节序）才用 bytes:N，且长度以返回串为准，不要假定等于请求长度。""",
),
(
"断点命中后我立刻 R 读寄存器指向的栈，读到的是旧值。为什么？",
"""因为断点用的是 access/write 类型时，命中发生在「指令执行前后」的边界上，
你要读的目标内存可能还没写入 —— 时序错了，不是地址错了。

正确的时序：
1) 用执行断点确认「指令到了」：
kitty_dbg action=bp addr=0xINSN access=execute mode=int3
2) 命中后不要立刻读业务内存，先读寄存器确认操作数：
kitty_dbg action=regs
判读：rcx/rdx 里的地址才是写入目标；rsp 上是返回地址。
3) 单步过掉这条指令再读：
kitty_dbg action=go step=stepover
kitty_dbg action=status                 → 回 stopped 后再读
4) 现在读才有效：
kitty_ce op="R|0xRCX_TARGET|dword"

写断点的场合：
kitty_dbg action=bp addr=0xADDR access=write size=4
判读：write 断点在写入发生后命中（调试器语义），此时读是「新值」；
要读旧值得在寄存器里找被覆盖前的值。

兜底：
如果 DBG_ATTACH 路径不可靠（本 build 有 fail-fast 风险），
改走 kitty_x64dbg action=seed + collect，用 savedata 在命中点直接把内存落盘，
事后分析落盘文件，避免读时序问题。""",
),
(
"批量扫多个值，我该发多条 BATCH 还是一条条发？",
"""BATCH 优先，但要注意「异步作业不能塞进 BATCH」。

BATCH 适用：
纯同步 OP（R/W/MODENUM/PING/CUR/MEMDUMP_HEX/LP）：
kitty_ce ops=["PING","CUR","MODENUM","R|0xADDR|dword"]
判读：一次投递，逐条回包；顺序保证与投递一致。

不能进 BATCH：
S_NEW / S_SNAP / P_BACK 这类返回 pending 的作业 ——
它们在桥里是异步的，塞进 BATCH 会让后续指令在作业未落定时执行，
表现为回包错位或状态被覆盖。

正确组合：
1) 先用 BATCH 把环境钉死：
kitty_ce ops=["PING","OPEN|<pid>","CUR","MODENUM"]
2) 再单独发作业并等待：
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" wait=true top=20
3) 收尾再 BATCH 归一：
kitty_ce ops=["S_FREE","SYNC_ARCHIVE","SYNC_STAT"]

批量读的替代（作业外的循环）：
用 LUA 一次算完，避免 N 次桥往返：
kitty_ce op="LUA|local t={} for i=0,15 do t[#t+1]=string.format('%X',readInteger(0xBASE+i*4)) end return table.concat(t,',')"
判读：回包是逗号分隔的十六进制值，一次拿 16 个。

退出条件：回包条数与 ops 条数一致；不一致说明有一条被拒，按 kitty_ops 逐条核对签名。""",
),
(
"我要改的是 .rdata 里的常量，是不是所有写都会被拒？",
"""不会全被拒，但会被页属性挡 —— 先 query 再决定走哪条写路径。

先判定：
kitty_prot action=query addr=0xRDATA_ADDR
判读：Protect=R（只读）时直接 W 会失败；
Protect=RW 时可以直接写（有些编译器把 .rdata 合并进了可写节）。

三条写路径（按侵入性递增）：
1) kitty_prot action=protect protect=rw 后再写：
kitty_prot action=protect addr=0xADDR size=0x1000 protect=rw confirm=true
kitty_ce op="W|0xADDR|dword|<新值>" confirm=true
kitty_ce op="R|0xADDR|dword"                  → 回读
收尾把保护改回：kitty_prot action=protect protect=readonly confirm=true
判读：这条路会调用 VirtualProtectEx，最容易被检测。

2) kitty_wpb（PTE 直改，不调保护 API）：
kitty_wpb addr=0xADDR val=<新值> vt=dword restore=true accept_protection_bypass=true
判读：不经过目标进程句柄，痕迹只在 PTE 位。

3) 内核路由写：
kitty_km action=write addr=0xADDR val=<新值> vt=dword confirm=true
kitty_km action=read addr=0xADDR vt=dword      → 必回读

落判据：三条路都必须回读验证（R 与 KM_R 双视图），
只有一条通时用那条，并且把「哪条被拒、拒绝码」记进 trail —— 拒绝码本身就是拦截面证据。""",
),
(
"LM 地址与真实模块基址差了一个固定值，是不是我算错了？",
"""多半没错，是你在用文件 ImageBase 而不是运行时 base —— ASLR 下两者必然不同。

判据：
kitty_ce op=MODENUM
判读：回包 name|base|is64|size 里的 base 是运行时基址，一切地址运算都用它。
文件里的 ImageBase（kitty_patch action=info 可看）只在「未启用 DYNAMIC_BASE」时与运行时相同。

固定差值的性质：
运行时 base - 文件 ImageBase = 一个 64KB 对齐的随机量（每进程独立）。
判读：多次启动样本，差值变化 → 确认 ASLR 生效；
差值恒定 → 可能是「固定基址 + 系统 ASLR 关闭」，此时可以硬编码。

正确做法：
1) 一律存「模块内偏移」而不是绝对 VA：
偏移 = VA - MODENUM.base
2) 恢复绝对地址时：
绝对 = 新 MODENUM.base + 偏移
3) 用 P_WALK 验证换算：
kitty_ce op="P_WALK|0xNEW_BASE|0xOFF"
判读：回读值与上次一致才算偏移稳定。

陷阱：跨会话复用绝对地址是最常见的翻车点 ——
上一次找到的 0x7FF75FCD1000 在这次进程里落在别的模块里，
写进去看起来成功，但改的是别的东西。""",
),
(
"我需要连续监控一个值 5 秒内的变化，怎么写最省？",
"""用 S_CHANGED 做区间观测，不要写轮询循环 —— 轮询会把桥的指令队列打满。

省调用量的做法：
1) 基线快照（窄窗）：
kitty_ce op="S_SNAP|dword|0xADDR|0xADDR+0x1000"
判读：窗口只给目标所在页附近，避免整模块。
2) 等 5 秒（外部 sleep，别用 OP 堆时间）
3) 取变化：
kitty_ce op=S_CHANGED
判读：只回「变了的地址」，未变的自动剔除 —— 这就是它比轮询省的原因。
4) 需要「谁没变」时用 S_UNCHANGED 交替。

需要精确时间点的场次：
像计时器/动画这类周期性变值，S_CHANGED 会把它们全命中。
判读：命中里同一地址在两次 CHANGED 都出现 → 周期变量，直接排除。

定点监控的替代（单点高频）：
kitty_ce op="LUA|local a,b=readInteger(0xADDR),0 for i=1,50 do local v=readInteger(0xADDR) if v~=a then b=b+1 a=v end end return b"
判读：回包是「50 次采样里变化次数」，一次桥调用拿频度，比 50 次 R 省 49 次往返。

收口：观测完 S_FREE + SYNC_STAT 归零，避免快照状态留给下一轮。""",
),
(
"同一条 OP 在这台机通、那台机报段数错，为什么？",
"""桥版本不同。OP 的段数要求随桥版本变，先核版本再核签名。

核版本：
kitty_ce op=VER
判读：回 0.2.x；本插件按 0.2.6+ 契约写（含 KM_* 面与 S_NEW 显式区间要求）。
版本低于要求时，KM_* 类 OP 会直接报未知指令。

核签名（不要背）：
kitty_ops filter=S_NEW
判读：它回的是段数要求 —— 五段（类型 / 值 / 起 / 止，含 OP 名本身）。
段数错就按它改，不是我记错的写法。

常见版本差异点：
- S_NEW 早期版本允许省略区间（默认全空间），新版本强制显式区间 → 老写法报段数错；
- P_BACK 早期无 200 上限提示，新版本加 TOO_MANY_HITS；
- KM_* 面 0.2.6 起才有。

跨机一致的写法：
1) 先 PING 确认通道；
2) kitty_ops 拉全表（回包大时用 filter 分片拉）；
3) 按表的签名生成 OP，不要跨机复制旧脚本里的字符串。

落判据：两台机的 VER 与 kitty_ops 签名都记进 trail，
遇到「本机能跑别机不能跑」先比这两项，再怀疑别的原因。""",
),
("我要在一次调用里取 20 个不相邻地址的值，怎么少往返？",
"""用 BATCH 或 LUA；BATCH 更安全，LUA 更省。

BATCH（推荐，语义清晰）：
kitty_ce ops=[
 "R|0x7FF6DADB1000|dword","R|0x7FF6DADB2010|dword","R|0x7FF6DADB3020|dword",
 "R|0x7FF6DADB4030|dword","R|0x7FF6DADB5040|dword"
]
判读：回包按投递顺序一对一；有失败项时该项回 ERR，其余不受影响。
20 条一次投递没问题，桥按顺序执行。

LUA（更快，但要处理返回值截断）：
kitty_ce op="LUA|local a={0x1000,0x2010,0x3020} local t={} for _,o in ipairs(a) do t[#t+1]=string.format('%X',readInteger(0x7FF6DADB0000+o)) end return table.concat(t,',')"
判读：返回会被截到 8192 字符，20 个值远小于上限，安全。

选择判据：
- 地址列表固定、需逐个确认失败 → BATCH；
- 地址由算法生成（base + 表内偏移）→ LUA，省掉手工拼 20 段字符串。

注意：
BATCH 里不能混异步作业（S_NEW/S_SNAP/P_BACK），
判读：混了会导致回包错位 —— 表现为「第 5 条回的是第 6 条的结果」。

收口：两条路的失败项都要单独重试并记录，不要用「大部分成功」收工。""",
),
\
(
"扫描区间里有一页是未映射的，S_NEW 会怎么表现？",
"""会跳过或整段失败，取决于作业实现 —— 所以永远不要给「不确定可读」的区间。

表现（按频率）：
1) 作业正常完成，但那一页的数据没被扫到 → 最危险，因为不报错；
2) 报 ERR|READ_FAIL 并中断 → 至少你知道有问题；
3) pending 卡住不出结果。

先验区间可读性（成本最低的一步）：
kitty_prot action=query addr=0xSTART
判读：RegionSize 覆盖到哪一步，就只扫到哪一步：
若 RegionSize=0x300000 而你的区间是 0x0A000000，后 0x07000000 全是空洞。

正确建窗口的方式：
kitty_ce op=MODENUM
判读：模块窗口天然连续且已映射 —— 优先用模块，别用「模块到堆之间」这种跨区大区间。
必须跨区时按 query 的 RegionSize 逐块切：
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTART+0x300000"

验证扫全了没有：
扫完记录 n；再用一个「必然存在」的值（如模块入口前的字节模式）在同区间试扫，
判读：必然存在的都扫不到，说明区间没走完。

退出条件：每个扫过的区间都有 query 的 RegionSize 覆盖 + 一次正控命中。
不做：不把 addr=0x0 到 0xFFFFFFFFFFFFFFFF 当区间 —— 那不是扫描，是挂死。""",
),
]

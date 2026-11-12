# -*- coding: utf-8 -*-
"""re-op-semantics 源 part A (1-15)。硬规则：不得出现无区间 S_NEW / 无窗口 P_BACK。"""

OP_A = [
(
"我现在要定位血量，但不想先把整个地址空间扫一遍。给我一个不超时的打法。",
"""先用 MODENUM 把窗口限死在主模块内，再分块扫，别一次给全地址空间。

第一步拿真实窗口（size 可能为 0，必须兜底）：
kitty_ce op=MODENUM
判读：回包是 name|base|is64|size。若 size=0，用镜像头算：
kitty_ce op="R|0xBASE+0x3C|dword"        → e_lfanew
kitty_ce op="R|0xBASE+0xE_LFANEW+0x50|dword"  → SizeOfImage
以此 SizeOfImage 作为窗口长度，别用 0。

第二步按固定块切（单块 ≤16MB，避免 pending 超时）：
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1000000" auto_free=false
判读：回 pending 就让 kitty_ce wait=true 自动落定；命中数 >500 说明值太常见，
不要直接 S_GET 全量，先改值再 S_CHANGED 收窄。

第三步收窄而不是重扫：
改一次血量 → kitty_ce op=S_CHANGED → 再改一次 → 交替直到 ≤10 个候选。

退出条件：候选 ≤10 且连续两次改值都跟随 → 取 S_GET 前 10 条逐个 R 回读，
R 值与界面显示一致的那条即真值地址。""",
),
(
"P_BACK 我给了整模块窗口，直接 200 条打满。窗口到底该怎么给？",
"""窗口不是「值在哪」，是「谁能装下这个指针的容器」——给大了必然打满上限。

判据：P_BACK 反查的是「内存里哪个位置的 8 字节等于目标地址」，
所以窗口应当覆盖「可能存放该指针的分配区」，通常是堆块或结构体数组，而不是整个模块。

正确给法（三步）：
1) 先确认目标地址所属分配区：
kitty_prot action=query addr=0xTARGET_VA
判读：返回的 AllocationBase + RegionSize 就是这块容器，窗口取 [AllocationBase, +RegionSize]。

2) 再在该区内反查：
kitty_ce op="P_BACK|0xTARGET_VA|0xALLOC_BASE|0xALLOC_BASE+0x400000"
判读：命中数 ≤20 才可用；仍然打满说明这块区也被复用了（池化分配），
按 RegionSize 之内的每 64KB 分片逐一反查，取命中片。

3) 多跳不要手写窗口：
kitty_pchain target=0xTARGET_VA depth=2 mod=TARGET.exe
判读：它内部已按模块区域过滤 + 每跳限候选（max_verify 默认 24），
比自己手给窗口稳。

退出条件：某一跳命中数从 200 掉到个位数 = 窗口对了；
每级用 kitty_ce op="R|0xCAND|qword" 回验，逐级读到目标地址全链一致才收。""",
),
(
"MODENUM 里 size 是 0，我后面所有窗口都算不出来。怎么办？",
"""size=0 是已知现象，用镜像头两级兜底，不要凭经验猜长度。

兜底链（按可靠性排序）：
1) 镜像头：
kitty_ce op="R|0xBASE+0x3C|dword"                → e_lfanew（NT 头偏移）
kitty_ce op="R|0xBASE+0xE_LFANEW+0x50|dword"     → SizeOfImage
判读：SizeOfImage 是加载器实际映射的长度，最权威。

2) 节表累加（SizeOfImage 读到 0 时）：
kitty_ce op="R|0xBASE+0xE_LFANEW+0x6|word"       → NumberOfSections
kitty_ce op="MEMDUMP_HEX|0xBASE+0xE_LFANEW+0x108|256"   → 前 8 条节表
判读：取所有 (VirtualAddress + max(VirtualSize, SizeOfRawData)) 的最大值，
按 SectionAlignment 上取整。

3) 兜底验证：
kitty_ce op="R|0xBASE+SIZE|dword"
判读：读到访问失败 → 窗口给大了；读到正常值 → 还在模块内，可微调上探。

4) 交叉：
kitty_prot action=query addr=0xBASE
判读：返回的 RegionSize 若等于 SizeOfImage，两次独立来源一致即可定稿。

落判据：三条里任两条一致就用它开扫；不一致时以 kitty_prot query 为准（它是加载器视角）。""",
),
(
"KM_R 和 R 读同一个地址，值不一样。哪个是对的？",
"""两个都是「真」的，只是走了不同路径 —— 分叉本身就是结论，不是错误。

先定位分叉：
kitty_ce op="R|0xADDR|dword"
kitty_km action=read addr=0xADDR vt=dword
判读：两次都成功且值不同 → 存在拦截面（用户态读被 hook 或页表被改）。

三方对照（决定性一步）：
kitty_dualview addr=0xADDR vt=dword samples=3
判读：它一次给出 R / KM_R / KM_PA+KM_PR 三视图。
- 只有 R 不同 → 用户态读路径被拦（常见于反作弊钩 ReadProcessMemory）；
- 只有 KM_R 不同 → 内核路由被过滤（较少见，需查驱动）；
- R 和 KM_R 一致但与物理不同 → 页被映射了两次（影子页）。

物理自证：
kitty_km action=pa addr=0xADDR
kitty_km action=pread pa=0xPA vt=dword
判读：物理读是最底层视图，它与 KM_R 一致就说明内核路由可信、用户态被拦。

处置：写操作一律走可信视图（物理一致的那条）；
用 kitty_wpb 直改 PTE 可绕过用户态保护，须 accept_protection_bypass=true，
且仅限用户态地址。证据行落 logs/anti-ace-<date>.jsonl（kitty_dualview 自动写）。""",
),
(
"我要确认一个值真的写进去了，不是「OP 回了 OK」。怎么验？",
"""写后必须回读，且要跨视图回读 —— OP 回 OK 只代表指令被受理。

最小闭环（四步）：
1) 写前读基线：
kitty_ce op="R|0xADDR|dword"
2) 写（须 confirm=true）：
kitty_ce op="W|0xADDR|dword|99" confirm=true
3) 立即回读同视图：
kitty_ce op="R|0xADDR|dword"
判读：等于 99 才说明写入未被打回；等于旧值 = 写入被吞（保护/影子页）。
4) 跨视图回读（关键）：
kitty_km action=read addr=0xADDR vt=dword
判读：两视图一致才算真写入；不一致即存在拦截面，按 kitty_dualview 取证。

失败分支：
kitty_prot action=query addr=0xADDR
判读：Protect 为只读/无访问 → 先 protect 改 RW 再写；protect 也失败 → 走 kitty_wpb。

收口证据：把「基线 / 写入值 / R 回读 / KM_R 回读」四元组写进 trail，
只留 OK 不留回读的写操作一律视为未验证。""",
),
(
"ALLOC 一块内存做临时缓冲，什么时候 FREE？忘了会怎样？",
"""忘了会泄漏，但比泄漏更糟的是污染后续扫描 —— 缓冲区本身会被扫成候选。

正确时序：
1) 分配：
kitty_ce op=ALLOC
判读：回包给 VA。立刻记下来（VA 与大小），这是回滚依据。
2) 用（写 + 回读）：
kitty_ce op="W|0xVA|dword|0x41414141" confirm=true
kitty_ce op="R|0xVA|dword"
3) 还原（若改的是目标内存，不是新分配）：
把原值写回：
kitty_ce op="W|0xORIG|dword|<原值>" confirm=true
4) 释放：
kitty_ce op="FREE|0xVA"
判读：回 OK 后必须回读验证：
kitty_ce op="R|0xVA|dword"
判读：读失败 = 已解映射，正常；仍可读 = 未真正释放，重试一次 FREE。

为什么要这么严：
- 未释放的页会被 MODENUM 之外的扫描窗口扫到，产生假候选；
- 未还原的目标内存会让「改值验证」这一步失效，后续 S_CHANGED 全是噪音。

落判据：一次实验结束，ALLOC 与 FREE 数量必须配平，
未配平就在 SYNC_ARCHIVE 前补 FREE，别把状态带进下一轮。""",
),
(
"S_SNAP 之后 S_CHANGED 一直返回几千个地址。是我用法错了？",
"""用法没错，是预算没设好 —— S_CHANGED 只在「变化范围小」时才有判别力。

正常节奏（三段收敛）：
1) 基线：
kitty_ce op="S_SNAP|dword|0xSTART|0xSTOP"
判读：先给窄窗（建议 ≤0x1000000），别一上来整模块，否则任何刷新都会命中。
2) 第一次变化：
操作一次（改血量/走一步），kitty_ce op=S_CHANGED
判读：命中数应该在几十到几百；上千说明窗口内有周期性刷新的计时器/动画队列。
3) 交替：
再操作一次 → kitty_ce op=S_UNCHANGED 取「没变的」作为新基线，
再操作 → S_CHANGED。
判读：CHANGED 与 UNCHANGED 交替两轮后，命中通常掉到个位数。
4) 取样：
kitty_ce op="S_GET|0|10"
判读：取前 10 条逐个 R 回读确认，别一次取 200。

窗口给错的典型症状：
- 命中数千且改值不影响 → 窗口落在图形/计时器堆区。换窗口，不要加大力度。
- 命中 0 且确认值确实变了 → 值类型不对（float 当 dword 扫），换 vt 重来。

退出条件：两轮交替后 ≤20，且 S_GET 抽样 R 回读与界面一致。""",
),
(
"S_GET 一次取 200 条，结果里混进了别的进程的地址。可能吗？",
"""不可能跨进程 —— S_NEW 的区间是你给的，扫的就是当前 OPEN 的进程。
混进来的其实是同进程内「不该出现的区域」，来源有两个。

成因排查（按顺序）：
1) 区间本身就横跨了多个分配区：
kitty_ce op=S_GET 取样后，对每条做
kitty_prot action=query addr=0xCAND
判读：AllocationBase 不同 = 你的窗口跨了堆、栈、模块三块，候选自然杂。

2) 值太常见：
kitty_ce op="S_NEW|dword|100|0xSTART|0xSTOP" 这类小值必然几百命中，
判读：命中数 >500 时就该改值再 S_CHANGED，而不是取样后人工筛。

正确收窄（不重扫）：
改一次值 → kitty_ce op=S_CHANGED
判读：CHANGED 保留的是变化的地址，未变的自动剔除，这一步就等于按「语义」筛了一遍。

3) 目标进程有同名但 pid 不同：
kitty_ce op=CUR
判读：确认 pid 与预期一致，否则 OPEN 换 pid。

退出条件：S_GET 抽样 10 条里 8 条落在同一 AllocationBase，且 R 回读与预期语义一致 → 窗口对了。""",
),
(
"写保护页我想直接改，kitty_wpb 的参数怎么给才不翻车？",
"""先 PTE 直改前必须确认三件事：用户态地址、目标 pid、以及写后还原。

前置：
kitty_prot action=query addr=0xADDR
判读：确认属用户态（< 0x7FFFFFFFFFFF）且不是 PAGE_NOACCESS 的换出页；
换出页要 permissive=true 按 PFN 重建保护位。

调用：
kitty_wpb addr=0xADDR hex="90 90 90" pid=<pid> restore=true accept_protection_bypass=true
判读：回包会给出 DTB → PTE 物理地址 → PTE 自映射 VA → 改 R/W → 写入 → 还原 的链路。
四项都要有，缺任一项说明中途失败（常见于 PTE 自映射区取不到）。

回验（不可省）：
kitty_ce op="R|0xADDR|bytes:3"
kitty_km action=read addr=0xADDR vt=bytes:3
判读：两视图都必须是 90 90 90；只有 R 变而 KM_R 不变 = 写进了影子页。

为什么默认 restore=true：
留下的「PTE 曾可写」痕迹是检测点（Accessed/Dirty 位变化 + 保护位回跳时序）。
一次性改完就还原，暴露窗口最小。

退出条件：两视图一致 + PTE 已还原（再用 kitty_km action=pa 复核一次同一 PA 的 PTE 位）。""",
),
(
"kitty_pchain 和手写 P_BACK 循环，什么时候用哪个？",
"""定式：已知单跳用 P_BACK 精控窗口；不明跳数或跨多级结构用 kitty_pchain。

手写 P_BACK 的适用面：
目标地址已确认属于某个已知分配区，只需回答「谁指向我」：
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x200000"
判读：命中 ≤200 是硬上限；命中数离上限很近说明窗口还是大了，按 64KB 分片再来。

kitty_pchain 的适用面：
要从一个动态地址一路推到模块基址，跳数不确定：
kitty_pchain target=0xTARGET depth=3 mod=TARGET.exe max_verify=24 frontier_cap=8
判读：它做的是「每跳反查 + R 回验 + P_WALK 回验 + 区域过滤」，
max_verify 控制每跳验证候选数（默认 24，调大更全但更慢）。
回包里的链条每一级都给「偏移 + 验证结果」。

选择判据：
- 已知上一级结构 → 手写，省时间；
- 只知终点要一路向上 → pchain；
- 跨模块（指针存于另一个模块的静态区）→ pchain，因为它按 mod 过滤区域。

收口：不管哪条路，最后都要 P_WALK 回验：
kitty_ce op="P_WALK|0xBASE|0xOFF"
判读：回读值与目标一致才算链成立；中间任一级偏移是猜的，回验必挂。""",
),
(
"我读 bytes:16 想当 dword 用，结果对不上。回包格式是什么？",
"""回包格式随类型变：数值类回十进制，bytes:N 回十六进制 —— 混用必错。

规则：
- R|addr|byte / word / dword / qword → 回包是十进制数值；
- R|addr|bytes:16 → 回包是十六进制字节串（如 48 8B 05 10 2A 00 00）。 

互转的正确做法（不要手算）：
kitty_ce op="R|0xADDR|dword"
判读：直接拿十进制值做比较，别从 bytes 里自己拼。

需要看字节序时：
kitty_ce op="R|0xADDR|bytes:4"
判读：0x3C 值若为 1500（0x000005DC），小端字节序是 DC 05 00 00。
看到 DC 05 00 00 就说明是小端 dword 1500，反过来拼时按小端还原。

扫描侧的对应关系：
kitty_ce op="S_NEW|bytes:4|0x000005DC|0xSTART|0xSTOP"
判读：bytes 类型的 val 要按十六进制给，且长度必须与 bytes:N 的 N 一致，
给少一字节会静默不命中 —— 这是最常见的「扫不到」原因。

落判据：凡是跨类型运算（比如把 reads 当指针），先统一成十进制数值再比；
需要字节级模式匹配才用 bytes:N，并且 val 也写十六进制。""",
),
(
"目标进程是 32 位的，我的 OP 全按 64 位写，哪些要改？",
"""改三处：指针宽度、MODENUM 的 is64 字段、以及 P_BACK 的搜索粒度。

1) 判定位数：
kitty_ce op=MODENUM
判读：行格式 name|base|is64|size，is64=0 即 32 位。
交叉：kitty_ce op="R|0xBASE+0x3C|dword" 后读 NT 头 Machine 字段（0x14C=i386，0x8664=x64）。

2) 指针类型：
32 位下读指针用 dword 而不是 qword：
kitty_ce op="R|0xADDR|dword"
判读：用 qword 会把相邻字段一起读进来，值看着像「高位垃圾 + 低位地址」，容易误判。

3) 反查粒度：
kitty_ce op="P_BACK|0xTARGET|0xSTART|0xSTOP"
判读：32 位下地址 4 字节，命中密度是 64 位的两倍，
所以窗口要比 x64 时更窄（建议先给 0x200000），否则必然打满 200 上限。

4) 扫描类型：
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP"
判读：32 位下 dword 是通用字宽，qword 扫描基本没有意义（对齐 8 的 double 除外）。

退出条件：MODENUM 的 is64 与 NT 头 Machine 一致，且指针读宽与之匹配，
再开始建窗口 —— 位数搞错时所有读都不报错，只是值是错的。""",
),
(
"km_attach 之后我还要不要每次 OPEN？两者什么关系？",
"""不是替代关系：OPEN 建用户态通道，KM_ATTACH 建内核路由，两条独立。

各自作用：
kitty_ce op=OPEN|<pid>
判读：建立用户态读写通道（R/W/ALLOC/S_NEW 走这条）。
kitty_km action=attach pid=<pid>
判读：内核态打开（EPROCESS + 内存 + 区域表），KM_R/KM_W/KM_PA/KM_PR 走这条。

attach-once 语义：
kitty_km action=info
判读：回包里 pid 已是当前目标时不重复 attach，避免反复 attach 造成句柄堆积。
目标切换了才需要重新 attach。

典型组合（三视图门禁）：
kitty_ce op=OPEN|<pid>
kitty_km action=attach pid=<pid>
kitty_dualview addr=0xADDR vt=dword samples=2
判读：一次给出 R / KM_R / 物理 三视图，分叉即拦截面。

注意：
- KM_PW（物理写）已永久拒绝，会卡死 Lua 引擎，取证只走 KM_PR；
- 内核写用 kitty_km action=write（须 confirm=true），写后必须 KM_R 回读。

退出条件：两条通道都通（PING + KM_INFO 均正常），再开始取数；
只有一条通时不要用另一条的结论做判据。""",
),
(
"扫一个 float 值，我该用什么类型？",
"""按位模式扫，用 dword，别用「float 类型」——绝大多数 OP 只认整数类型。

做法：
1) 取位模式：
float 99.5 = 0x42C70000。给扫描时写十六进制：
kitty_ce op="S_NEW|dword|0x42C70000|0xSTART|0xSTOP"
判读：命中后 R 回读用 dword，值应等于 0x42C70000（十进制 1119686656），
不要拿 99.5 去比 —— 类型不匹配永远对不上。

2) 验证是 float：
kitty_ce op="R|0xADDR|dword"
判读：把十进制值按 IEEE754 单精度解一遍（外部算或心算位段），等于 99.5 即坐实。

3) 变值收窄：
改成 98.5 → 0x42C50000，用 S_CHANGED 收窄，
判读：S_CHANGED 会保留所有变化地址，再用新位模式做一次 S_NEW 交集更稳。

4) double 的情况：
8 字节、位模式更长，用 qword 扫，窗口要更窄（命中密度低但假阳性也低）。

退出条件：位模式解回原值一致 + 改两次值都跟随 → 地址正确；
若一直扫不到，先确认界面显示的是 float 还是被格式化过的数值。""",
),
]

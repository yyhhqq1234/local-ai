# -*- coding: utf-8 -*-
"""re-op-semantics 扩量 E（61-90）"""

OP_E = [
("S_NEW 的区间我给成了「0x0 到 0x7FFFFFFFFFFF」。",
"""这种区间包含全部用户态，作业必然挂死或超时。

```
kitty_ce op=MODENUM
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1000000" wait=true top=20
```
判读：窗口从模块起，一块 16MB。命中即停，不命中再推进下一块。

```
kitty_prot action=query addr=0xBASE+0x1000000
```
判读：query 报 INVALID_ADDRESS 说明模块只有一块，扩窗要跳到下一个有映射的区。

退出：单块 ≤16MB、且每块都经 query 确认可读；全空间区间一次都不许给。"""),

("P_BACK 命中 200 条，我想直接取全部 200 条来筛。",
"""取不到。200 是回包上限，且 P_BACK_RES 也只给前 N 条。

```
kitty_ce op="P_BACK_RES|20"
```
判读：单次最多取 top 条。要更多就缩窗口分片，别指望分页取全量。

```
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x10000"
```
判读：64KB 片内的命中通常 ≤5，这时才能把「全部候选」拿到手。

退出：至少一个 64KB 片命中 ≤20 且逐条 R 回验；
回验方式是 kitty_ce op="R|0xCAND|qword" 看是否等于目标。"""),

("我 attach 到内核后，R 读变慢了。",
"""KM_ATTACH 会打区域表，用户态读路径可能被额外校验。

```
kitty_km action=info
```
判读：确认只 attach 一次（attach-once）。重复 attach 会累积句柄并拖慢。

```
kitty_ce op="R|0xADDR|dword"
kitty_km action=read addr=0xADDR vt=dword
```
判读：两次耗时对比。KM_R 明显更快时，批量读全走 KM_R。

```
kitty_ce op="LUA|local t={} for i=0,99 do t[#t+1]=string.format('%X',readInteger(0xBASE+i*4)) end return table.concat(t,',')"
```
判读：批量读用 LUA 一次拿 100 个值，避免 100 次桥往返。

退出：批量读路径定型（LUA 或 KM_R），单点读才用 R。"""),

("S_NEW 返回 n=0，但我确定值在内存里。",
"""三条判据按序排除：类型、窗口、对齐。

```
kitty_ce op="R|0xADDR|bytes:16"
```
判读：先手工读目标附近，确认值真的存在、以及字节序。

```
kitty_ce op="S_NEW|bytes:4|DC050000|0xSTART|0xSTOP" wait=true top=20
```
判读：1500 = 0x000005DC，小端 DC 05 00 00。用 bytes 精确匹配排除对齐假设。

```
kitty_prot action=query addr=0xSTART
```
判读：窗口是否真的已映射。RegionSize 小于窗口 → 后半段没扫到。

退出：三条都排除后仍 0 命中，则值是被计算出来的（不常驻），改走 S_SNAP 变化法。"""),

("用 S_UNCHANGED 之后结果反而变多了。",
"""UNCHANGED 保留「没变的」，若基线本身噪声大，保留的就多。

```
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
```
判读：基线窗口要给小（≤1MB），大窗口的 UNCHANGED 必然多。

```
kitty_ce op=S_CHANGED
kitty_ce op=S_UNCHANGED
kitty_ce op=S_CHANGED
```
判读：交替两轮。每轮后计数应单调下降；上升说明窗口里有周期性写。

退出：两轮后计数 ≤20；不降就换窗口（挪到结构体所在分配区）。"""),

("我要读一个 2MB 的配置块，怎么一次拿全？",
"""分块 + 拼接，单次上限 4096 字节。

```
kitty_dump addr=0xCFG size=0x200000 path=logs\\cfg.bin
```
判读：工具层封装了分块，优先用它。

手工分块时：
```
kitty_ce op="MEMDUMP_HEX|0xCFG|4096"
kitty_ce op="MEMDUMP_HEX|0xCFG+4096|4096"
```
判读：起点每次 +4096，连续不跳页；每块长度必须完整。

退出：拼接总长 == 0x200000；首尾各取 16 字节做完整性抽检。"""),

("我想确认某个地址是不是被 PAGE_GUARD 保护。",
"""guard 页会在访问时抛异常，是反调试与栈增长检测的常用手段。

```
kitty_prot action=query addr=0xADDR
```
判读：Protect 含 PAGE_GUARD(0x100) 即命中。query 不会触发 guard。

```
kitty_ce op="R|0xADDR|dword"
```
判读：读会触发 guard，可能失败或让目标收到异常 —— 这是判据，不是 bug。

退出：给出「是否 guard」+ 读是否触发；guard 页不要用 R 试探，
改用 kitty_prot action=query 的静态结果。"""),

("扫描时值在变（计时器），命中数一直在涨。",
"""变值目标不能用精确扫描，要用区间/变化法。

```
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
kitty_ce op=S_CHANGED
```
判读：先拿「哪些地址在变」，再从变化集里找形态像计时器的（等距、单调增）。

```
kitty_ce op="S_GET|0|20"
kitty_ce op="R|0xCAND|dword"
```
判读：连续读两次，值递增且步长稳定 = 计时器，直接排除。

退出：剩下的候选改值跟随；跟随不上的全部是计时器/动画。"""),

("写 float 值用 dword 写，程序算出来的结果不对。",
"""位模式写对了才等价，十进制写 100 到 float 字段会得到一个极小值。

```
kitty_ce op="R|0xADDR|dword"          → 先看原位模式
kitty_ce op="W|0xADDR|dword|0x42C80000" confirm=true
kitty_ce op="R|0xADDR|dword"
```
判读：100.0f 的位模式是 0x42C80000。写它，回读应等于该十六进制值（十进制等值）。

```
kitty_ce op="R|0xADDR+4|dword"
```
判读：确认没写坏相邻 4 字节。

跨视图确认：
```
kitty_km action=read addr=0xADDR vt=dword
```
判读：内核视图也应是 0x42C80000；不一致说明写进了影子页。

退出：位模式回读一致 + 界面显示 100 + 双视图相同。"""),

("KM_PA 算出的物理地址，我用 KM_PR 读不到。",
"""物理读失败多半是地址没按页对齐，或该页已被换出。

```
kitty_km action=pa addr=0xVA
kitty_km action=pread pa=0xPA vt=bytes:16
```
判读：pread 必须给对齐后的物理地址；页内偏移要自己加到结果上。

```
kitty_km action=pa addr=0xVA+0x800
```
判读：换页内位置重算 PA，确认同一页内偏移一致。

退出：能读到与 KM_R 相同的前 16 字节；读不到就说明页被换出，
改用 KM_R（内核路由会处理换页）。"""),

("我用了 auto_free=true，还想接着 S_CHANGED。",
"""auto_free 会清掉扫描状态，S_CHANGED 就失去基线。

```
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" wait=true top=20 auto_free=false
kitty_ce op=S_CHANGED
```
判读：需要后续收窄时必须 auto_free=false。

```
kitty_ce op=S_FREE
```
判读：收尾手动释放。忘记释放会让下一轮 S_GET 的索引含义变。

退出：需要链路（SNAP→CHANGED→UNCHANGED）时全程 auto_free=false；
一次性扫描才用 true。"""),

("OPEN 一个 64 位进程后，读 32 位指针总是多出 4 字节。",
"""类型宽度与位数不匹配，读出来的高 4 字节是相邻字段。

```
kitty_ce op=MODENUM
```
判读：is64=1 → 指针 8 字节，用 qword；is64=0 → 4 字节，用 dword。

```
kitty_ce op="R|0xADDR|dword"
kitty_ce op="R|0xADDR+4|dword"
```
判读：目标若是 32 位进程，两段合起来才是完整 8 字节字段（如结构体里的两个 int）。

退出：位数与类型一致后，指针能过 kitty_prot action=query 的归属校验。"""),

("我需要判读「这个地址里的值是不是指针」，有快办法吗？",
"""三个判据叠加，命中率高且只需两条 OP。

```
kitty_ce op="R|0xADDR|qword"
```
判据一：值的高 2 字节是 0x0000（用户态地址）或 0xFFFF（内核态），中间不像随机数。

```
kitty_prot action=query addr=<读出的值>
```
判据二：能解析出 AllocationBase → 是真地址；报 INVALID_ADDRESS → 不是指针。

判据三：值与 8 对齐。
```
kitty_ce op="R|0xADDR|qword"
```
判读：值 % 8 == 0 加分（多数指针对齐），不为 0 也可能是 char*。

退出：判据二通过即为指针；不通过时给出「值 / 不是指针」结论并停手。"""),

("我改完值想恢复，但忘了原值。",
"""没记原值就无法回滚 —— 这是流程问题，用固定动作避免。

标准顺序（每次都走）：
```
kitty_ce op="R|0xADDR|dword"
kitty_ce op="W|0xADDR|dword|<新值>" confirm=true
kitty_ce op="R|0xADDR|dword"
```
判读：第一条的输出必须复制进 trail 或日志，这是回滚依据。

补救（已经忘了）：
```
kitty_ce op="S_NEW|dword|<新值>|0xSTART|0xSTOP" wait=true top=20
```
判读：找不到原值；改为查磁盘默认值（kitty_patch action=find）或重启进程复位。

退出：要么拿到原值写回，要么重启目标恢复到初始状态并记录「未还原」。"""),

("S_GET 的 start 参数是什么？我传了地址。",
"""S_GET 的第一个参数是结果索引起点，不是地址。

```
kitty_ce op="S_GET|0|20"
```
判读：从第 0 条开始取 20 条。第二个参数是条数。

```
kitty_ce op="S_GET|20|20"
```
判读：取第 20-39 条。索引超出总数时回空，不报错。

```
kitty_ce op=JOB_STAT
```
判读：n= 字段给出总命中数，据此决定分几次取。

退出：分页取到 n 条为止；地址筛选在取回后用 query 做，不在 S_GET 里做。"""),

("我要确认扫描真的覆盖了整块，有正控办法吗？",
"""有：埋一个已知值再扫，命中即证明区间可达。

```
kitty_ce op=ALLOC
kitty_ce op="W|0xNEW_VA|dword|0x12345678" confirm=true
kitty_ce op="S_NEW|dword|0x12345678|0xSTART|0xSTOP" wait=true top=5
```
判读：命中 0xNEW_VA → 区间可达；未命中 → 区间没覆盖到该分配区。

```
kitty_ce op=FREE|0xNEW_VA
```
判读：验完立刻释放，避免污染后续扫描。

退出：正控命中 + 释放完成 + SYNC_STAT 归零。"""),

("同一个 OP 连发两次，第二次报状态占用。",
"""异步作业未落定时不接受新作业。

```
kitty_ce op=JOB_STAT
```
判读：state=running 时不能开新 S_NEW。等落定或用 wait=true。

```
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" wait=true top=20
```
判读：wait=true 会自动等落定，避免「状态占用」。

退出：每次作业都有明确的落定判据（JOB_STAT 或 wait=true），不并发发同类作业。"""),

("我要读的内存在目标进程里是只读的，query 却说是 RW。",
"""query 看的是页表视图，实际写可能被更上层拦（hook / 保护驱动）。

```
kitty_prot action=query addr=0xADDR
kitty_ce op="R|0xADDR|dword"
```
判读：query=RW 且 R 成功，但 W 失败 → 拦在写路径，不在页表。

```
kitty_dualview addr=0xADDR vt=dword samples=2
```
判读：三视图分叉即坐实拦截面。

```
kitty_wpb addr=0xADDR val=<值> vt=dword restore=true accept_protection_bypass=true
```
退出：给出「页表可写 / 写路径被拦」判定；被拦时走 wpb，并回读两视图确认。"""),

("我需要判断两次读之间目标有没有被换页。",
"""判据是「KM_PA 是否变了」，不是值是否变了。

```
kitty_km action=pa addr=0xADDR
```
判读：记下 PA。等一段时间再算一次：
```
kitty_km action=pa addr=0xADDR
kitty_km action=pread pa=0xPA vt=dword
```
判读：PA 变了 = 换页发生（PFN 更换）；pread 读到的值应与 KM_R 一致。

退出：给出「是否换页」+ 换页前后 PA；换页频繁时物理读不可缓存，每次重算 PA。"""),

("扫到的地址我写入后，S_CHANGED 又把它当变化报出来。",
"""正常：你写的动作本身就是变化，S_CHANGED 会把它算进去。

```
kitty_ce op="W|0xADDR|dword|<值>" confirm=true
kitty_ce op=S_CHANGED
```
判读：把变化集里的 0xADDR 剔除即可 —— 这是已知变化，不是新线索。

正确用法：先 S_SNAP，再触发一次「业务动作」而不是写入，再 CHANGED。

```
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
```
退出：变化集只含业务动作引起的变化；写入引起的变化在分析时手工剔除。"""),

("我要在没有符号的情况下判断一个函数是「校验」还是「业务」。",
"""判据是它的输入输出形态与调用点密度，不是函数名。

```
kitty_ce op=MODENUM
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=sub_
```
判读：校验函数的特征：
1) 返回值只有 0/1 两种；
2) 内部有长常量（哈希初值、SBox）；
3) xref 少（1-3 个），且调用点后面紧跟条件跳转 + 失败分支。

业务函数：返回值多样、xref 多、内部有结构体访问。

```
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<候选>
```
退出：给出「校验 / 业务」判定 + 三条支撑特征中的至少两条。"""),

("我想拿一个函数的调用次数，用来确认是不是热路径。",
"""OP 层没有计数器，只能用断点或采样。

```
kitty_x64dbg action=seed addr=<函数VA> seedCmd=log
```
判读：命中日志的条数就是调用次数。热路径会在几秒内上百。

```
kitty_ce op="R|0xADDR|dword"
```
判读：若函数内有计数器字段（很多热路径会累加），直接读它更快。

退出：给出「调用频度数量级」（每秒几次 / 几百次）；
不要追求精确计数，量级足够判断热路径。"""),

("我分不清「匿名可执行区」和「模块代码区」。",
"""判据是有没有 PE 头与模块归属。

```
kitty_prot action=query addr=0xADDR
```
判读：Type=MEM_IMAGE → 模块映射；MEM_PRIVATE → 匿名区；
MEM_MAPPED → 文件映射（第三类，常见于大资源）。

```
kitty_ce op=MODENUM
```
判读：AllocationBase 能否对上某个模块 base。对不上 = 匿名。

```
kitty_ce op="R|0xADDR|bytes:2"
```
判读：匿名区首字节 4D 5A → 反射加载的 PE；48 89/55 8B → 裸代码。

退出：给出「模块 / 匿名代码 / 文件映射」三选一 + 首 2 字节。"""),

("我要在两条 OP 之间保持一个值不变，怎么做？",
"""OP 层没有事务，靠「写前记原值 + 写后回读 + 结束还原」三步保证。

```
kitty_ce op="R|0xADDR|dword"                       → 记原值 V0
kitty_ce op="W|0xADDR|dword|<新值>" confirm=true
kitty_ce op="R|0xADDR|dword"                       → 确认
kitty_ce op="W|0xADDR|dword|<V0>" confirm=true     → 还原
```
判读：之间任何失败都要立刻还原，不能等到最后。

退出：结束时该地址已还原，且 SYNC_STAT 四项归零。"""),

("读 qword 得到 0x00000000FFFFFFFF，这算指针吗？",
"""不算。高 32 位全 0 低 32 位全 1 不是合法地址，是两个相邻 int 拼出来的。

```
kitty_ce op="R|0xADDR|dword"
kitty_ce op="R|0xADDR+4|dword"
```
判读：两个字段分别是 0xFFFFFFFF 和 0 —— 说明这里不该按 qword 读。

```
kitty_prot action=query addr=0xFFFFFFFF
```
判读：报 INVALID_ADDRESS 即确认不是指针。

退出：给出「这是两个 32 位字段」的判定，并按 dword 重新读结构。"""),

("S_NEW 的 val 我写了负数，被拒。",
"""OP 只接受无符号或十六进制，负数要转成补码。

```
kitty_ce op="S_NEW|dword|0xFFFFFF9C|0xSTART|0xSTOP" wait=true top=20
```
判读：-100 的 32 位补码是 0xFFFFFF9C。

```
kitty_ce op="S_NEW|byte|0x9C|0xSTART|0xSTOP" wait=true top=20
```
判读：8 位 -100 = 0x9C。

退出：命中后 kitty_ce op="R|0xCAND|dword" 回读，值应等于十进制 4294967196
（即 -100 的无符号解释）。"""),

("我要判断某个 OP 是同步还是异步。",
"""看回包里有没有 pending / state。

```
kitty_ops filter=S_NEW
```
判读：签名里若有 wait 参数，说明它是异步作业（S_NEW/S_SNAP/P_BACK 三类）。

```
kitty_ce op="S_NEW|dword|1|0xSTART|0xSTOP" wait=false
```
判读：回 pending 即异步；回 OK|done|n= 即同步。

退出：把同步/异步分类记进 trail，BATCH 只能放同步类。
混入异步会让后续回包错位。"""),

("我要把一个 4 字节值改成 8 字节字段，注意什么？",
"""宽度不同会覆盖相邻字段，先把整个 8 字节读出来再改。

```
kitty_ce op="R|0xADDR|qword"
```
判读：拿到原 8 字节。若高 4 字节是别的字段，必须保留。

```
kitty_ce op="W|0xADDR|qword|<保留高位的值>" confirm=true
kitty_ce op="R|0xADDR|qword"
```
判读：回读一致，且 kitty_ce op="R|0xADDR+4|dword" 显示相邻字段未变。

跨视图确认：
```
kitty_km action=read addr=0xADDR vt=qword
```
判读：内核视图应与 R 一致；不一致时以内核视图为准。

退出：目标 4 字节正确 + 相邻 4 字节未变 + 双视图一致。"""),

("我要确认这块内存是不是「刚分配还没初始化」。",
"""判据是填充图案：0xCD / 0xCC / 0xDD / 0xFE 各有语义。

```
kitty_ce op="MEMDUMP_HEX|0xADDR|64"
```
判读：
0xCDCDCDCD = 未初始化的堆内存（Debug CRT）
0xCCCCCCCC = 未初始化的栈 / 断点填充
0xFEEEFEEE = 已释放的堆内存
0xDDDDDDDD = 已释放的堆（Debug）

```
kitty_prot action=query addr=0xADDR
```
判读：Type=MEM_PRIVATE 支持「堆/栈」判断。

退出：给出填充语义 + 该块是否已被写入过（非填充即写过）。"""),

("我想让一次扫描只返回奇数地址上的命中。",
"""OP 没有过滤参数，靠后处理。

```
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" wait=true top=50
kitty_ce op="S_GET|0|50"
```
判读：取回后按 (addr % 2) 过滤；但这只是展示层过滤，改变不了「可能漏命中」的事实。

改数据层：
```
kitty_ce op="S_NEW|word|0x05DC|0xSTART|0xSTOP" wait=true top=50
```
判读：改用 word 扫描相当于只匹配低 2 字节，天然包含奇偶两类。

退出：说明「OP 层无过滤」这个边界，并给出后处理脚本或换类型的替代方案。"""),

("查一个地址的完整属性，我该发几条 OP？",
"""三条足够：归属、权限、内容。

```
kitty_prot action=query addr=0xADDR
```
判读：AllocationBase / RegionSize / Protect / Type / State 一次给全。

```
kitty_ce op="R|0xADDR|bytes:16"
```
判读：内容形态。

```
kitty_ce op=MODENUM
```
判读：AllocationBase 落在哪个模块（模块归属）。

退出：三项齐备后写进卡片：地址 / 归属 / 权限 / 首 16 字节；
缺模块归属时标「非模块区」，不要写「未知」。"""),

("kill 掉目标后我没 FREE，下次 ALLOC 拿到的地址重叠了。",
"""地址重叠是正常的（新进程地址空间独立），但旧状态残留会让判读混乱。

```
kitty_ce op=SYNC_ARCHIVE
kitty_ce op=SYNC_STAT
```
判读：四项归零说明上一轮会话状态已归档。

```
kitty_ce op=PING
kitty_ce op=CUR
```
判读：CUR 报「无目标」= 会话已重置；仍报旧 pid = 状态未清，先 OPEN 新目标或重启宿主。

退出：四项归零 + CUR 与当前目标一致，再开始 ALLOC。"""),
]

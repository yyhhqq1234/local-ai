# -*- coding: utf-8 -*-
"""re-op-semantics 扩量 F（91-120）"""

OP_F = [
("我用 S_NEW 扫 0 值，命中几十万。",
"""0 是最常见的值，直接扫无意义。

```
kitty_ce op="S_NEW|dword|0|0xSTART|0xSTOP" wait=true
```
判读：n 巨大即放弃这条路径。

改判据（从「值」换到「变化」）：
```
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
kitty_ce op=S_CHANGED
```
判读：只保留变化的地址，0 值里绝大多数不变，会被自动剔除。

```
kitty_ce op="S_GET|0|20"
```
退出：候选 ≤20 且改值跟随；否则缩窗口到单个分配区再来一遍。"""),

("P_BACK 反查一个模块内的静态地址，窗口给多少？",
"""静态地址被引用的位置几乎都在同一模块的 .data/.rdata 里。

```
kitty_ce op=MODENUM
kitty_ce op="P_BACK|0xSTATIC|0xBASE+0xDATA_RVA|0xBASE+0xDATA_RVA+0x200000"
```
判读：先只在数据节反查，命中通常 1-5 条。

```
kitty_ce op="P_BACK|0xSTATIC|0xBASE|0xBASE+SIZE"
```
判读：数据节内无命中才扩到整模块（此时要按 1MB 分片）。

退出：命中 ≤20 且 R 回验通过；全模块无命中说明该地址是算出来的，不是存的。"""),

("我要判断值是不是被加密存储（读出来不是明文但语义相关）。",
"""判据是「同类型字段彼此相关」，不是看熵。

```
kitty_ce op="R|0xADDR|dword"
kitty_ce op="R|0xADDR+4|dword"
kitty_ce op="R|0xADDR+8|dword"
```
判读：三个相邻字段若是随机值 → 加密；若有单调/范围关系 → 明文（可能是缩放）。

```
kitty_ce op="S_NEW|dword|<读到的值>|0xSTART|0xSTOP" wait=true top=10
```
判读：能扫到说明是原样存储；扫不到（值在别处生成）说明只是缓存。

退出：给出「明文 / 加密 / 派生缓存」三选一 + 相邻字段对照。"""),

("读到的指针指向自己所在的地址（自引用）。",
"""自引用结构说明它是链表/树的哨兵节点，或初始化未完成的环形链。

```
kitty_ce op="R|0xADDR|qword"
```
判读：值 == 0xADDR 即自引用。

```
kitty_ce op="R|0xADDR+8|qword"
```
判读：下一个字段指向自己（双向环的 prev/next 同址）→ 单元素环；
指向别的地址 → 多元素链。

```
kitty_prot action=query addr=<next>
```
退出：给出「单元素环 / 链首 / 未初始化」判定；
单元素环常见于容器初始化，不代表有业务数据。"""),

("我要写一个 qword，但只改低 4 字节。",
"""读-改-写，不能直接写 qword（会覆盖高位）。

```
kitty_ce op="R|0xADDR|qword"
```
判读：记 V0。高位 = V0 >> 32，低位 = V0 & 0xFFFFFFFF。

```
kitty_ce op="W|0xADDR|qword|<(高位<<32)|新低32>" confirm=true
kitty_ce op="R|0xADDR|qword"
```
判读：回读高位不变、低位为新值。

跨视图确认：
```
kitty_km action=read addr=0xADDR vt=qword
```
判读：内核视图的高位也必须未变。

退出：高位未变 + 低位正确 + 双视图一致；用 kitty_ce op="R|0xADDR+4|dword" 再确认一次高位。"""),

("S_NEW 之后我想知道命中地址落在哪个模块，批量做。",
"""一条 OP 一个地址，批量靠 BATCH 或 LUA。

```
kitty_ce ops=["R|0xCAND1|dword","R|0xCAND2|dword"]
```
判读：只解决读值，解决不了归属。

归属查询没有批量 OP，必须逐条：
```
kitty_prot action=query addr=0xCAND
```
判读：AllocationBase 与模块表比对即归属。

```
kitty_ce op=MODENUM
```
退出：把候选按 AllocationBase 分组，同组只查一次模块名 —— 这样把 N 次查询降到组数次。"""),

("目标进程暂停时 R 还能读吗？",
"""能。R 走的是内存读写，不依赖目标线程调度。

```
kitty_ce op=PING
kitty_ce op="R|0xADDR|dword"
```
判读：进程被挂起（suspend）时读仍成功，这是它与断点路径的关键差异。

```
kitty_dbg action=status
```
判读：确认调试器是否处于 stopped；stopped 时 R 仍可用，但 DBG_REGS 是暂停快照。

退出：给出「读不受挂起影响」这个结论，并在暂停态优先用 R 取数据，
不要因为断点停下就停止取数。"""),

("我要判断某个地址是堆还是栈。",
"""两条 OP 足够。

```
kitty_prot action=query addr=0xADDR
```
判读：Type=MEM_PRIVATE 且 AllocationBase 的 RegionSize 是几百 KB 到几 MB、
且地址接近 RegionBase + RegionSize（向下增长）→ 栈。
RegionSize 小（≤64KB）且地址靠近 RegionBase → 堆块。

```
kitty_ce op="R|0xALLOC_BASE|bytes:16"
```
判读：栈区低地址处通常是 TEB/TIB 相关结构；堆块首部有堆头。

退出：给出「堆 / 栈」判定；判不出时记「MEM_PRIVATE 私有区」，不要猜。"""),

("我改了一个结构字段，程序读的是另一个。",
"""说明存在两份结构（服务端/客户端，或缓存/真值），你改的是副本。

```
kitty_ce op="S_NEW|dword|<字段值>|0xSTART|0xSTOP" wait=true top=20
```
判读：命中多份同值地址 → 存在副本。

```
kitty_ce op="W|0xCAND1|dword|<新值>" confirm=true
kitty_ce op="R|0xCAND2|dword"
```
判读：改一份看另一份是否跟随 —— 跟随说明有同步逻辑，不跟随说明是独立副本。

退出：找到「改了之后界面/行为变化」的那一份，其余标记为副本并记录同步方向。"""),

("读一个字符串，R 只给了前 8 字节。",
"""bytes 类型需要显式长度，读长串要分段或加大 N。

```
kitty_ce op="R|0xADDR|bytes:32"
```
判读：ASCII 串到 00 结束；UTF-16 每隔一字节一个 00。

```
kitty_ce op="MEMDUMP_HEX|0xADDR|256"
```
判读：一次性看 256 字节，人工找结束符更直观。

```
kitty_ce op="LUA|local s='' for i=0,255 do local b=readBytes(0xADDR+i,1)[1] if b==0 then break end s=s..string.char(b) end return s"
```
退出：拿到完整串 + 编码判定（ASCII / UTF-16LE）；长度以结束符为准，不以 N 为准。"""),

("我要确认写入没被目标自己的逻辑覆盖，最快判据是什么？",
"""写后立刻读 + 隔一拍再读，两次都等于新值才算成功。

```
kitty_ce op="W|0xADDR|dword|<值>" confirm=true
kitty_ce op="R|0xADDR|dword"
kitty_ce op="R|0xADDR|dword"
```
判读：第二次（隔一次往返）若回原值 → 被逻辑覆盖；两次都是新值 → 站住。

```
kitty_ce op="LUA|local v=readInteger(0xADDR) local c=0 for i=1,20 do if readInteger(0xADDR)~=v then c=c+1 end end return c"
```
判读：20 次采样里变化次数。>0 说明该字段被高频重写。

退出：给出「站住 / 被覆盖」判定 + 重写频度数值。"""),

("我用了 wait=true 但回包还是 pending。",
"""wait 有超时上限，超了仍回 pending。

```
kitty_ce op=JOB_STAT
```
判读：state 与 n。running 且 n 增长 → 继续等；n 不变 → 区间过大。

```
kitty_ce op="S_NEW|dword|<值>|0xSTART|0xSTART+0x1000000" wait=true top=20
```
判读：把区间缩到 16MB 再等；大区间无论 wait 多久都可能超时。

退出：拿到 done + 样本，或确认区间需要再切一半。"""),

("我要判断这块内存是否被目标程序 mmap 进来的文件。",
"""文件映射的判据是 Type，不是内容。

```
kitty_prot action=query addr=0xADDR
```
判读：Type=MEM_MAPPED → 文件/页文件映射；MEM_IMAGE → PE 映像；MEM_PRIVATE → 私有。

```
kitty_ce op="R|0xADDR|bytes:4"
```
判读：MEM_MAPPED 且首 4 字节是 4D 5A → 映射了一个 PE；
是 50 4B → 映射了 zip（常见于资源包）。

退出：给出「映射类型 + 首 4 字节格式」；MEM_MAPPED 区不要按堆结构去解释。"""),

("扫描时目标进程重启了，作业还在跑。",
"""作业绑定的是旧 pid 的地址空间，重启后结果无意义。

```
kitty_ce op=JOB_STAT
```
判读：若仍 running 而 CUR 已变，直接放弃这轮结果。

```
kitty_ce op=CUR
kitty_ce op=OPEN|<新 pid>
```
判读：重新 OPEN 后必须重新取 MODENUM —— base 已变。

退出：旧作业作废（S_FREE），新会话从 MODENUM 重来；
地址一律转成偏移再复用。"""),

("我需要读一个 bit 位，OP 支持吗？",
"""不支持位操作，读整字节自己算。

```
kitty_ce op="R|0xADDR|byte"
```
判读：拿到整字节，按 bit = (v >> n) & 1 判断。

写位时读-改-写：
```
kitty_ce op="W|0xADDR|byte|<(原值 & ~mask)|(新位<<n)>" confirm=true
kitty_ce op="R|0xADDR|byte"
```
判读：回读确认该位改变、其余位不变。

跨视图确认：
```
kitty_km action=read addr=0xADDR vt=byte
```
判读：内核视图的整字节应与你写入的一致。

退出：位值与相邻位都正确 + 双视图一致；用 bytes:2 再看一眼相邻字节是否被波及。"""),

("我要确认 scan 的 val 是十进制还是十六进制。",
"""带 0x 前缀按十六进制，不带按十进制。

```
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" wait=true top=5
kitty_ce op="S_NEW|dword|0x5DC|0xSTART|0xSTOP" wait=true top=5
```
判读：两条应命中同一批地址（1500 = 0x5DC）。结果不同说明有一条被当成别的进制解析。

```
kitty_ce op="R|0xCAND|dword"
```
退出：给出「两条等价」的验证结论；书写时统一用十进制或统一用 0x，不要混。"""),

("读出来的值每次都不一样，是加密还是随机数？",
"""每次不同 = 每次重新生成；要区分「随机」与「加密计数器」。

```
kitty_ce op="LUA|local t={} for i=1,10 do t[#t+1]=readInteger(0xADDR) end return table.concat(t,',')"
```
判读：10 次采样，值分布均匀且无重复 → 随机；
单调递增 → 计数器/时间；周期重复 → 伪随机种子固定。

```
kitty_ce op="R|0xADDR-8|qword"
```
判读：附近若有种子/计数器字段，能解释生成规律。

退出：给出「随机 / 计数 / 伪随机」判定 + 一条生成规律证据。"""),

("我要把一段内存改成可执行，注意什么？",
"""三条：先记原权限、改完立刻验证、结束还原。

```
kitty_prot action=query addr=0xADDR
kitty_prot action=protect addr=0xADDR size=0x1000 protect=rwx confirm=true
kitty_ce op="R|0xADDR|bytes:8"
```
判读：改后能读（权限提升不应破坏读）。

```
kitty_prot action=protect addr=0xADDR size=0x1000 protect=readonly confirm=true
```
判读：还原成原权限。原权限必须来自第一步 query。

退出：三步齐备 + 还原后 query 与初始一致。
不做：不改系统模块页（MEM_IMAGE + 系统 DLL），那会触发完整性校验。"""),

("S_GET 取回来的地址我怀疑是错的。",
"""用「写-读」双向验证，不要只读。

```
kitty_ce op="R|0xCAND|dword"
kitty_ce op="W|0xCAND|dword|<读到的值>" confirm=true
```
判读：写回同一个值不改变状态，但能验证该地址可写（错的地址常不可写）。

```
kitty_ce op="R|0xCAND+4|dword"
kitty_ce op="R|0xCAND-4|dword"
```
判读：相邻字段是否合理。垃圾值包围的地址多半不是目标。

归属核对：
```
kitty_prot action=query addr=0xCAND
```
判读：AllocationBase 应与目标对象一致；落在别的区说明取样索引混淆。

退出：可写 + 相邻字段自洽 + 改值跟随 + 归属一致，四项齐备。"""),

("我要判断两个地址是不是同一个对象。",
"""比「首 32 字节」而不是比值。

```
kitty_ce op="MEMDUMP_HEX|0xADDR1|32"
kitty_ce op="MEMDUMP_HEX|0xADDR2|32"
```
判读：两段完全相同 → 同一份内容的两个视图（拷贝）或同一对象；
不同 → 不同对象。

```
kitty_ce op="R|0xADDR1|qword"
kitty_ce op="R|0xADDR2|qword"
```
判读：首字段（vtable）相同 → 同类对象；不同 → 不同类。

退出：给出「同对象 / 同类型不同实例 / 不同类」三选一；
「同对象」必须有 dump 完全相同这一条支撑。"""),

("目标进程有多个同名线程，我断点只命中一个。",
"""断点默认是进程级，但线程可能没走到该代码。

```
kitty_dbg action=status
kitty_ce op=LP
```
判读：确认线程数量与状态。

```
kitty_x64dbg action=seed addr=<函数VA> seedCmd=log
```
判读：日志里看命中的线程 ID —— 只有主线程命中说明其他线程不走这条路径。

退出：给出「哪些线程会走该路径」的结论；
线程级断点要按线程 ID 过滤，不是所有同名线程都执行同一段代码。"""),

("我要读 TEB 里的字段，OP 层怎么拿基址？",
"""TEB 在 fs:[0]（32 位）或 gs:[0]（64 位），OP 层不能直接读段寄存器。

```
kitty_dbg action=regs
```
判读：调试器寄存器视图里若有 gs/fs 基址就直接用。

```
kitty_ce op="LUA|local teb=readPointer(...)"
```
判读：LUA 可用时通过已知偏移读 TEB；否则用宿主侧只读 API 取线程环境块。

```
kitty_ce op="R|0xTEB|bytes:16"
```
判读：TEB 首字段是 SEH 链（x86）或 NT_TIB 结构（x64），能解释即拿对了。

退出：给出 TEB 基址 + 目标字段偏移；拿不到 TEB 时改用「已确认的全局指针」，
不要靠段寄存器硬算。"""),

("我用 bytes 类型写，回包说长度不符。",
"""hex 串的字符数必须正好是 2×字节数。

```
kitty_ce op="W|0xADDR|bytes:4|"90 90 90 90"" confirm=true
```
判读：4 字节要 8 个十六进制字符（允许空格分隔）。

```
kitty_ce op="R|0xADDR|bytes:4"
```
判读：回读应等于写入的串。

跨视图确认：
```
kitty_km action=read addr=0xADDR vt=bytes:4
```
判读：内核视图的字节串应与写入一致（长度也会被校验）。

退出：写入 + 回读逐字节一致 + 双视图一致；长度不符时数一遍字符数再发。"""),

("我要在一段代码里找所有 call 指令的目标。",
"""静态做，不要在 OP 层扫。

```
kitty_ce op=MODENUM
kitty_dump module=SAMPLE.exe path=logs\\m.bin
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> limit=200
```
判读：Ghidra 的 xref 图就是 call 目标的完整集合。

需要运行期核验时：
```
kitty_ce op="R|0xINSN|bytes:5"
```
判读：E8 + rel32，目标 = 指令地址 + 5 + rel32。

退出：给出「静态 call 目标表 + 抽样 3 条运行期字节核对」。"""),

("我要判断这个值是「帧计数」还是「业务计数」。",
"""判据是变化频率与触发条件。

```
kitty_ce op="LUA|local a=readInteger(0xADDR) local n=0 for i=1,200 do local b=readInteger(0xADDR) if b~=a then n=n+1 a=b end end return n"
```
判读：200 次采样内变化次数。几十次以上 = 帧计数（每帧变）；个位数 = 业务计数。

```
kitty_ce op="R|0xADDR|dword"
```
判读：帧计数通常 16 位回绕或按刷新率递增；业务计数单调。

退出：给出「帧 / 业务」判定 + 变化频度数值。"""),

("我要恢复一个被我改坏的页，但没记原字节。",
"""先看有没有可回滚来源，再谈恢复。

```
kitty_patch action=hash path=SAMPLE.exe
```
判读：磁盘文件未改，可从中取原始字节。

```
kitty_dump module=SAMPLE.exe unmap=true path=logs\\orig.bin reference=SAMPLE.exe
```
判读：用磁盘文件做参考，重建原始内存布局。

```
kitty_ce op="W|0xADDR|bytes:<原字节>" confirm=true
```
判读：写回原字节后回读确认。

退出：字节回读与磁盘一致；做不到时记录「已污染」，并重启进程恢复干净状态。"""),

("查询一个地址的权限返回 PROTECT_UNKNOWN。",
"""UNKNOWN 通常是该地址未提交或跨界查询。

```
kitty_prot action=query addr=0xADDR
```
判读：State 字段应为 COMMIT；FREE/RESERVE 时权限无意义。

```
kitty_prot action=query addr=0xADDR-0x1000
```
判读：前移一页再查，看是否是边界问题。

退出：给出「未提交 / 边界」判定；未提交就按 RegionSize 找最近的已提交区。"""),

("我需要验证一个猜测：这块内存是脚本虚拟机的栈。",
"""判据是「栈式访问模式」：顶部指针 + 频繁 push/pop 的等距访问。

```
kitty_ce op="R|0xADDR|qword"
```
判读：首字段若是一个指向本区内部的指针（栈顶），强信号。

```
kitty_ce op="S_SNAP|bytes:16|0xADDR|0xADDR+0x2000"
kitty_ce op=S_CHANGED
```
判读：变化集中在「栈顶附近」且呈等距（每 8 字节）→ 栈式访问。

```
kitty_ce op="MEMDUMP_HEX|0xADDR|128"
```
退出：给出「VM 栈 / 普通数组」判定 + 栈顶指针值 + 变化区范围。"""),

("我要在两个地址之间做 diff，OP 层有工具吗？",
"""没有 diff OP，两段 dump 后本地比。

```
kitty_ce op="MEMDUMP_HEX|0xADDR1|256"
kitty_ce op="MEMDUMP_HEX|0xADDR2|256"
```
判读：两串十六进制逐字节比，找出首个差异偏移。

```
kitty_ce op="LUA|local a=readBytes(0xADDR1,256) local b=readBytes(0xADDR2,256) local t={} for i=1,256 do if a[i]~=b[i] then t[#t+1]=i-1 end end return table.concat(t,',')"
```
判读：LUA 一次回「所有差异偏移」，比人工比串快得多。

退出：给出差异偏移列表；差异为 0 时结论写「两段完全相同」。"""),

("我要确认一个字段是不是 vtable 指针。",
"""三条判据：指向模块只读区、首项是函数、同类对象共享同一值。

```
kitty_ce op="R|0xOBJ|qword"
kitty_prot action=query addr=<读出的值>
```
判读：落在模块的 .rdata 区（Type=MEM_IMAGE + 只读）→ 像 vtable。

```
kitty_ce op="R|<vtable>|qword"
kitty_prot action=query addr=<第一项>
```
判读：第一项指向模块 .text 内 → 是函数指针表；是 0 或数据 → 不是 vtable。

```
kitty_ce op="R|0xOBJ2|qword"
```
判读：同类型另一对象首字段相同 → 共享 vtable，坐实。

退出：三条中至少两条成立才判 vtable。"""),
]

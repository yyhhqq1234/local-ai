# -*- coding: utf-8 -*-
"""re-op-semantics 扩量 D（31-60）。每段 S_NEW 必须带显式区间，P_BACK 必须带窗口。"""

OP_D = [
("S_NEW 的区间我给成了「模块基址到模块基址+0x1000」，只扫了 4KB。",
"""4KB 只够一页，命中 0 是常态。判据不是「值不在」，而是「区间没覆盖到」。

```
kitty_ce op=MODENUM
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1000000" wait=true top=20
```
判读：先给 16MB 一块，命中数应在个位到百位。0 命中才继续扩。

```
kitty_ce op="S_NEW|dword|1500|0xBASE+0x1000000|0xBASE+0x2000000" wait=true top=20
```
判读：逐块推进，命中即停。不要一次给到 SizeOfImage —— 未映射页会让作业变慢。

退出：某块命中非 0，且 S_GET 抽样 R 回读与界面一致。"""),

("P_BACK 的窗口我给了堆的一整段（32MB），结果 200 打满。",
"""32MB 里同一指针被复制几十份是正常的（池化 + 结构体数组）。

```
kitty_prot action=query addr=0xTARGET
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x400000"
```
判读：先按 query 的 AllocationBase + 4MB 给窗。仍打满 → 按 64KB 分片。

```
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x10000"
```
判读：64KB 片内命中通常 0-5 条，逐片推进，命中片就是目标容器。

退出：某片命中 ≤20 且 R 回验通过；24 片全走完仍 0 → 目标不在堆上，改扫别的分配区。"""),

("MODENUM 给了 size=0，我按 0x1000000 猜了一个，结果扫到未映射区。",
"""猜测的代价是作业中途报错或静默漏扫。size=0 有三条兜底路径，按序试。

```
kitty_ce op="R|0xBASE+0x3C|dword"                 → e_lfanew
kitty_ce op="R|0xBASE+0xE_LFANEW+0x50|dword"      → SizeOfImage
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1C00000" wait=true top=20
```
判读：SizeOfImage 读到非零即用；读到 0 或失败，走第二条：
```
kitty_prot action=query addr=0xBASE
```
判读：返回的 RegionSize 是加载器视角的真实长度，最权威。

退出：三条里任两条一致即定稿；都不一致时以 query 为准。"""),

("KM_R 读到 0，但 R 读到正常值。哪个可信？",
"""内核路由读 0 通常是「没 attach 对」或「地址在用户态之外」。

```
kitty_km action=info
kitty_km action=attach pid=<pid>
kitty_km action=read addr=0xADDR vt=dword
```
判读：attach 前读 0 是未附加的正常表现，不是拦截面。

```
kitty_dualview addr=0xADDR vt=dword samples=2
```
判读：三视图（R / KM_R / 物理）同时给。只有 KM_R 不同 → 内核路由问题；
R 与物理一致 → 内核读路径有过滤。

退出：给出「未附加 / 内核过滤 / 用户态被拦」三选一，并落一条证据行。"""),

("S_CHANGED 命中了 600 多个地址，其中大部分是计时器。",
"""命中量大说明区间里有周期性刷新的字段，不是你的目标错了。

```
kitty_ce op=S_GET
kitty_ce op="S_GET|0|20"
```
判读：取前 20 条，逐个看地址间隔。等距（每 8 或 16 字节一个）→ 是结构体数组，
其中一两个字段是你的目标，其余是时间戳。

```
kitty_ce op="S_UNCHANGED"
```
判读：交替一轮，周期性字段会在「不变」那侧留下痕迹，把噪声分离出去。

```
kitty_ce op="S_NEW|dword|<新值>|0xSTART|0xSTOP" wait=true top=20
```
判读：改用新值重扫，直接跳过噪声。

退出：候选降到 ≤20，且改值两次都跟随。"""),

("写 4 字节时用了 bytes 类型，写进去多了一个字节。",
"""bytes:N 的长度必须等于 N 的字节数，多给会越界写坏相邻字段。

```
kitty_ce op="R|0xADDR|bytes:4"                      → 先看原 4 字节
kitty_ce op="W|0xADDR|dword|100" confirm=true
kitty_ce op="R|0xADDR|bytes:4"                      → 回读
```
判读：dword 类型只写 4 字节，不会溢出。需要写原始字节时才用 hex，且必须精确 4 字节。

```
kitty_ce op="R|0xADDR+4|dword"
```
判读：核对相邻字段没被改动 —— 这是 bytes 写法的必查项。

权限核对（写失败时先做这一步）：
```
kitty_prot action=query addr=0xADDR
```
判读：Protect 必须是 RW 或 RWX；只读页写入会被拒，不是 bytes 参数的问题。

退出：写入值正确 + 相邻 4 字节未变 + query 显示可写。"""),

("我要读一个 64 位指针，但 R 只回 32 位。",
"""dword 只有 4 字节，高位被截断。读指针必须 qword。

```
kitty_ce op="R|0xADDR|qword"
kitty_ce op="R|0xADDR|bytes:8"
```
判读：qword 回十进制；bytes:8 回十六进制串（小端）。
0x00007FF6XXXXXXXX 的形态在 bytes 里是 XX XX XX XX F6 7F 00 00。

```
kitty_prot action=query addr=<读出的指针值>
```
判读：query 能解析 = 指针有效；报 INVALID_ADDRESS = 高 4 字节是垃圾。

退出：指针能过 query 且指向的模块/分配区可解释。"""),

("扫 float 血量，我先用 dword 扫 1500 扫不到，后来发现值其实是 1500.0。",
"""float 是按位存的，1500.0 的位模式不是 1500。

```
kitty_ce op="S_NEW|dword|0x44BB8000|0xBASE|0xBASE+0x1000000" wait=true top=20
```
判读：1500.0f 的 IEEE754 单精度位模式是 0x44BB8000。扫它，不是扫 1500。

```
kitty_ce op="R|0xCAND|dword"
```
判读：回十进制值，与 0x44BB8000 的十进制等值（1153138688）比对，一致即命中。

退出：改一次值（如 1499.5 = 0x44BB6000）后 S_CHANGED 跟随。
两次位模式都命中同地址才算坐实。"""),

("S_NEW 指定 word 扫 300，命中两千多条。",
"""两字节值在 16MB 里出现两千次是统计必然，没有判别力。

```
kitty_ce op="S_NEW|dword|300|0xBASE|0xBASE+0x1000000" wait=true top=20
```
判读：先按更宽的类型扫（dword）。若真值只有 2 字节，dword 扫描仍能命中
（高位是相邻字段），命中数会降到几十。

```
kitty_ce op="S_NEW|bytes:2|2C01|0xBASE|0xBASE+0x1000000" wait=true top=20
```
判读：300 = 0x012C，小端 2C 01。bytes 精确匹配比 word 类型更严（不做对齐假设）。

退出：候选 ≤50 且改值跟随；仍过多就换「改值后 S_CHANGED」而不是继续缩类型。"""),

("P_BACK 我要反查一个栈上的地址。",
"""栈地址被大量栈帧引用，反查必然爆炸 —— 栈不是合适的反查起点。

```
kitty_prot action=query addr=0xSTACK_ADDR
```
判读：Type=MEM_PRIVATE + AllocationBase 是栈区 → 判据成立：放弃反查。

正确做法（改为从目标字段反查）：
```
kitty_ce op="P_BACK|0xTARGET_FIELD|0xBASE|0xBASE+0x200000"
```
判读：先反查「谁持有目标字段的地址」，而不是反查栈值。

```
kitty_ce op="P_WALK|0xBASE|0xOFF"
```
退出：给出「栈不可反查」的判定，并改用「从字段向上」的路径；
若目标只在栈上出现，说明它没有静态归属，只能用偏移 + 每次重启重扫。"""),

("我要同时监控两个值，但 S_NEW 会覆盖上一次的状态。",
"""扫描状态是单例，第二次 S_NEW 会顶掉第一次的结果。

```
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" wait=true top=20
kitty_ce op="S_GET|0|20"
```
判读：先把第一组取样落地（结果在回包里），再开第二组。

```
kitty_ce op="S_NEW|dword|300|0xSTART|0xSTOP" wait=true top=20
```
判读：第二组独立跑。要「同时」就只能靠两次取样对比，不能靠状态共存。

替代：用 S_SNAP 覆盖更大区间，一次拿两个值的变化：
```
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
```
判读：CHANGED 会同时给出两个值的变化页。

退出：两个值各自拿到可回读验证的地址。"""),

("OPEN 之后 MODENUM 列了 40 个模块，我怎么快速定位主模块？",
"""主模块一定是模块表第一行，且 base 最低（exe 映像）。

```
kitty_ce op=MODENUM
```
判读：第一行就是主模块（加载器按映像顺序列出）。base 通常不是最低 ——
系统 DLL 可能更低，所以「第一行」比「最低 base」更可靠。

```
kitty_ce op="R|0xFIRST_BASE+0x3C|dword"
```
判读：能读出合法 e_lfanew 说明它确实是 PE 映像；顺带确认 size 兜底值。

```
kitty_ce op=CUR
```
判读：确认当前 OPEN 的 pid 与模块表来源一致。

退出：主模块 base/size 定稿，写进会话记录；后续所有地址用它换算。"""),

("我想确认某个地址是不是在模块内，别再手动算了。",
"""用 query 让加载器回答，不要拿 base+size 心算。

```
kitty_prot action=query addr=0xADDR
```
判读：返回的 AllocationBase 与 Type 是判据：
Type=MEM_IMAGE 且 AllocationBase 落在模块表某行 base 上 → 模块内；
Type=MEM_PRIVATE → 堆/栈/自建区；AllocationBase 不在模块表 → 匿名映射。

```
kitty_ce op=MODENUM
```
判读：把 query 的 AllocationBase 与模块表逐个比对，锁定模块名。

退出：给出「模块名 + 模块内偏移」；给不出模块名时就是非模块区，
后续窗口按 query 的 RegionSize 建。"""),

("写值之后界面变了，但重启就丢。这是没写对吗？",
"""界面变、重启丢 = 写在运行期内存，本来就是非持久化的正常行为。

```
kitty_ce op="R|0xADDR|dword"          → 写后回读
kitty_km action=read addr=0xADDR vt=dword
```
判读：两视图一致 = 写成功（运行期有效）。持久化是另一回事。

```
kitty_patch action=find path=SAMPLE.exe str=<配置文件路径> limit=8
```
判读：如果样本有配置文件，持久化点在文件里，不在内存。

退出：明确区分「运行期写入成功」与「持久化」两件事；
本任务的判据只要求前者，不要用「重启丢失」当失败。"""),

("ALLOC 出来的地址不可写，写进去没反应。",
"""ALLOC 只给地址，不给执行/写权限的完整组合，要单独查。

```
kitty_ce op=ALLOC
kitty_prot action=query addr=0xNEW_VA
```
判读：看返回的 Protect。是 R 或 RX 就先改：
```
kitty_prot action=protect addr=0xNEW_VA size=0x1000 protect=rw confirm=true
```
判读：改完再 query 一次确认生效。

```
kitty_ce op="W|0xNEW_VA|dword|1234" confirm=true
kitty_ce op="R|0xNEW_VA|dword"
```
退出：写入 + 回读一致；收尾 FREE 并核对 SYNC_STAT 归零。"""),

("DBG_BP 下了三个断点，只有第一个命中。",
"""三个里只有一个命中通常是：地址算错、或前一个断点没继续。

```
kitty_dbg action=bp_list
```
判读：确认三个断点都还在（有的实现会在命中后自动删除）。

```
kitty_dbg action=go
kitty_dbg action=status
```
判读：命中后必须 go 才会走到下一个断点。卡在第一个 = 忘了继续。

```
kitty_ce op=MODENUM
```
判读：核对三个断点地址是否都用当前 base 算的；复用旧 base 的两个必然永不命中。

退出：三个断点各自命中一次，或给出「地址失效」的判定并重算。"""),

("SYNC_STAT 显示 pending 3，但我不确定是真有作业还是残留。",
"""3 个 pending 要么是未落定的作业，要么是网关层没归档完。

```
kitty_ce op=JOB_STAT
```
判读：state=running 的是真作业；没有对应作业却 pending 非零 = 残留。

```
kitty_ce op=SYNC_ARCHIVE
kitty_ce op=SYNC_STAT
```
判读：归档后仍非零 → 有作业真的在跑，别强清。

```
kitty_status probe=true
```
判读：给出 sync 根目录 pending 数与 KittyCE 进程状态，交叉确认。

退出：pending=0（真残留已清）或能指名哪个作业在跑。"""),

("我要在一条 OP 里同时读地址和它的类型信息，能吗？",
"""不能，OP 是单指令。要么 BATCH 两条，要么用 query + R 分开。

```
kitty_ce ops=["R|0xADDR|dword","R|0xADDR|bytes:4"]
```
判读：BATCH 里两条独立回包，分别给数值与字节。

```
kitty_ce op="LUA|local v=readInteger(0xADDR) local t={} for i=0,3 do t[#t+1]=string.format('%02X',readBytes(0xADDR+i,1)[1]) end return v..'|'..table.concat(t,' ')"
```
判读：LUA 一次拿「值 | 原始字节」，省一次往返。

权限信息不能靠 R 拿，必须 query：
```
kitty_prot action=query addr=0xADDR
```
退出：值 + 字节 + 权限三项齐；缺权限项时不要对「为什么写不进去」下结论。"""),

("读栈上的参数，R 一直读失败。",
"""栈顶附近常有 guard page，越界读会整段失败。

```
kitty_ce op="R|0xRSP|bytes:16"
kitty_prot action=query addr=0xRSP
```
判读：query 的 RegionSize 给出栈可读范围；RSP 靠近边界时只能往「栈内」读。

```
kitty_ce op="R|0xRSP+8|qword"
```
判读：x64 下 [rsp] 是返回地址，[rsp+8] 起才是第一个栈参数（第 5 个参数）。

```
kitty_dbg action=regs
```
判读：用调试器拿 RSP 比用上次记录的值可靠 —— RSP 每次调用都变。

退出：能读出返回地址 + 至少一个栈参数；读不出来就退回寄存器传参（前 4 个）。"""),

("MODBASE 和 MODENUM 给的 base 不一样。",
"""不一致说明 MODENUM 的 size 字段挤占了解析，或 MODBASE 走了 fallback 路径。

```
kitty_ce op=MODENUM
kitty_ce op="MODBASE|kitty-target.exe"
```
判读：两次 base 打印出来比对。MODENUM 是权威（一次枚举全表）；
MODBASE 是单点查询，size=0 时可能返回镜像头里的 ImageBase（磁盘值）。

```
kitty_ce op="R|0xBASE_FROM_MODENUM|dword"
```
判读：能读 = 真实加载基址；读失败 = 那个值是磁盘 ImageBase，用错了。

退出：以 MODENUM 为准，并把 MODBASE 的结果标注为「可能返回磁盘 ImageBase」。"""),

("S_SNAP 之后我忘了 S_CHANGED 的语义，直接 S_NEW 覆盖了。",
"""S_NEW 会重置快照状态，这之前的基线就废了。

```
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
kitty_ce op=S_CHANGED
```
判读：SNAP 与 CHANGED 必须成对，中间不能插 S_NEW。

正确顺序：
1) SNAP 建立基线
2) 触发变化
3) CHANGED 取变化集（快照自动收窄）
4) 再触发，UNCHANGED 取不变集
5) 交替到候选足够小
6) 取样后 S_FREE

```
kitty_ce op="S_GET|0|10"
kitty_ce op=S_FREE
```
退出：整个序列没有夹入 S_NEW；收尾 S_FREE + SYNC_STAT 归零。"""),

("我要判断一个值是「被程序周期重算」还是「真存着」。",
"""判据是「写入后是否被覆盖」，不是读取值本身。

```
kitty_ce op="W|0xADDR|dword|100" confirm=true
kitty_ce op="R|0xADDR|dword"
```
判读：立刻读回 100，等 2 秒再读：
```
kitty_ce op="R|0xADDR|dword"
```
判读：变回原值 = 周期重算（缓存/显示层）；仍 100 = 真值。

```
kitty_ce op="LUA|local a=readInteger(0xADDR) local n=0 for i=1,100 do if readInteger(0xADDR)~=a then n=n+1 a=readInteger(0xADDR) end end return n"
```
判读：回 100 次采样中变化次数。>10 说明它在被高频重写。

退出：给出「真值 / 缓存」判定 + 变化频度数值。"""),

("P_WALK 回验失败，但链是我一级级读出来的。",
"""回验失败通常是「某一级偏移算的是字节偏移，写成了元素索引」。

```
kitty_ce op="P_WALK|0xBASE|0xOFF"
```
判读：回读值与目标不符时，先核 OFF 的量纲。

```
kitty_ce op="R|0xBASE|qword"
```
判读：第一跳的实际指针值。与预期不符 → 第一级就错。

```
kitty_ce op="R|0xFIRST_PTR+0xOFF2|qword"
```
判读：逐级手工读，找到断在哪一级。

退出：断点定位到具体级数并给出该级真实偏移；
全对但 P_WALK 仍失败时，是 P_WALK 的参数顺序问题，按 kitty_ops 核签名。"""),

("扫到的候选地址，第二次启动全变了。",
"""ASLR 下堆地址每次都变，这是设计不是错误。存偏移不存绝对地址。

```
kitty_ce op=MODENUM
```
判读：记录 base。把候选转成「模块内偏移」或「从某个稳定指针起算的偏移」。

```
kitty_ce op="P_BACK|0xCAND|0xBASE|0xBASE+0x200000"
```
判读：反查谁持有它 —— 拿到静态归属后，路径才是稳定的。

```
kitty_pchain target=0xCAND depth=2 mod=kitty-target.exe
```
退出：给出「静态基址 + 两级偏移」的路径，并在新进程里 P_WALK 复验通过。"""),

("同一个值在两个不同进程里都存在，我 OPEN 了错的。",
"""同名双开时必须用 pid 钉死，OP 层没有任何「按名选最新」的语义。

```
kitty_ce op=LP
kitty_ce op=OPEN|<目标 pid>
kitty_ce op=CUR
```
判读：CUR 回读的 pid 必须等于你选的那个。

```
kitty_ce op=MODENUM
```
判读：两个实例的 base 不同（各自 ASLR），窗口必须从当前 pid 取。

```
kitty_ce op="R|0xADDR|dword"
```
判读：写前先回读确认是预期旧值 —— 这是唯一能防「写错实例」的动作。

退出：CUR 的 pid 与预期一致 + 写前回读符合预期。"""),

("我要读一个结构体的第 5 个字段，偏移 0x20，但读出来是垃圾。",
"""偏移对不代表基址对。结构体指针错一级，所有字段都是垃圾。

```
kitty_ce op="R|0xPTR|qword"
kitty_prot action=query addr=0xPTR
```
判读：先确认指针本身有效（query 能解析）。无效 → 指针链断了。

```
kitty_ce op="R|0xPTR+0x20|dword"
```
判读：读字段。若值明显不合理（如 0xCCCCCCCC / 0xFEEEFEEE），
那是未初始化内存标记 —— 说明 PTR 指向的是刚分配未填的结构。

```
kitty_ce op="MEMDUMP_HEX|0xPTR|96"
```
判读：dump 整个头部 96 字节，按字段排布反推真实布局，别信记忆里的偏移。

退出：dump 里能识别出 ≥2 个自洽字段（如 vtable 指针 + 计数字段），偏移才可信。"""),

("kitty_ce 返回 ERR|OP_UNKNOWN，但 kitty_ops 里明明有。",
"""版本落后于插件契约，或 OP 名拼错一个字符。

```
kitty_ce op=VER
```
判读：<0.2.6 时 KM_* 面不存在；<0.2.5 时 BATCH 不支持。

```
kitty_ops filter=<OP 名>
```
判读：核签名与段数。名字大小写、下划线数量都要一致。

```
kitty_variants action=list
```
判读：当前宿主变体是否带桥；某些变体的桥是精简版。

退出：VER + 签名两项都对上后重发；仍失败就换 kitty_drv action=host 重拉宿主。"""),

("我要把一段内存原样保存，但 MEMDUMP_HEX 只给十六进制文本。",
"""十六进制文本可以落盘，用 LUA 写更省往返。

```
kitty_ce op="MEMDUMP_HEX|0xADDR|4096"
```
判读：回包是十六进制串，复制到文件后需外部转二进制（每 2 字符 1 字节）。

```
kitty_ce op="LUA|local f=io.open('D:\\\\ws\\\\dump.bin','wb') local d=readBytes(0xADDR,4096) f:write(string.char(table.unpack(d)) f:close() return 'ok'"
```
判读：LUA 直接写盘，省掉十六进制转换。路径必须是 ASCII 且在工作区内。

```
kitty_dump addr=0xADDR size=0x1000 path=logs\\blk.bin
```
判读：工具层已封装分块落盘，优先用它而不是手写 LUA。

退出：落盘文件大小 == 请求长度；用 kitty_patch action=hash 记录指纹。"""),

("我读到的值一直是 0xCC，不知道是填充还是真值。",
"""0xCC 是调试器断点指令填充（int3），不是业务值。

```
kitty_prot action=query addr=0xADDR
```
判读：Type=MEM_PRIVATE 且 Protect=RX → 调试器填充的可执行区，
0xCC 是未写入的真实内容。

```
kitty_ce op="R|0xADDR|bytes:16"
```
判读：连续 0xCC 就是填充；间隔出现 0xCC 说明是断点被写入过。

```
kitty_ce op="R|0xADDR-4|dword"
```
判读：前后字段是否正常。前后都正常只有这 4 字节是 CC → 该字段未初始化。

退出：给出「填充 / 未初始化 / 真值 0xCC」三选一；
真值 0xCC 的话前后字段必然自洽，这是唯一判据。"""),

("我要在扫描结果里排除某一整段（已知噪声区）。",
"""OP 没有「排除」参数，只能分段扫或扫完过滤。

分段扫：
```
kitty_ce op="S_NEW|dword|1500|0xSTART|0xNOISE_START" wait=true top=20
kitty_ce op=S_GET
kitty_ce op="S_NEW|dword|1500|0xNOISE_END|0xSTOP" wait=true top=20
```
判读：两次独立扫描，各自取样后合并。

扫完过滤：
```
kitty_ce op="S_GET|0|50"
```
判读：逐条 kitty_prot action=query，落在噪声区（同一 AllocationBase）的剔除。

```
kitty_ce op="LUA|local t={} for _,a in ipairs({...}) do if a<0xNOISE_START or a>0xNOISE_END then t[#t+1]=a end end return #t"
```
退出：噪声区外的候选全部经过 query 归属确认；合并后总数 ≤20。"""),

("写入成功但目标程序立刻退出。",
"""写坏了关键字段会让程序自检失败退出 —— 先查写位置是否真的只影响目标。

```
kitty_ce op="R|0xADDR+4|dword"
kitty_ce op="R|0xADDR-4|dword"
```
判读：相邻字段是否被改（越界写）。变了 → 类型宽度用错。

```
kitty_km action=read addr=0xADDR vt=dword
```
判读：内核视图确认写入范围。

回滚：
```
kitty_ce op="W|0xADDR|dword|<原值>" confirm=true
```
判读：写回原值后程序能继续 → 确认是这次写导致。

退出：给出「写坏 / 自检触发」判定；自检触发时先定位校验函数，再谈改值。"""),
]

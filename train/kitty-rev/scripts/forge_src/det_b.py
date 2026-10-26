# -*- coding: utf-8 -*-
"""re-detour-trajectory 源 part B (16-30)"""

DET_B = [
(
"资源里的载荷提不出来，strings 只拿到半截。四次返工。",
"""往返1｜动作：用字符串工具扫二进制
strings SAMPLE.exe > out.txt
回包：拿到大量可读串，但没有 PE/容器结构
判读：第一次失败。strings 按可打印字符切分，二进制载荷会被切碎。

往返2｜动作：按「资源目录」找块，但用错偏移字段
读 IMAGE_RESOURCE_DATA_ENTRY 的 OffsetToData
判读：OffsetToData 在资源树里是 RVA（相对镜像），不是文件偏移。
直接拿去按文件偏移读 → 读到错位置的数据。
回包：数据无意义。

往返3｜动作：改成 RVA → 文件偏移 换算
kitty_patch action=info path=SAMPLE.exe
按节表：文件偏移 = RVA - 节.VirtualAddress + 节.PointerToRawData
回包：读到的块首字节 4D 5A
判读：这一步对了，拿到 PE 头。

往返4｜动作：按块长切出，但忘了资源大小可能大于单节
回包：切出的文件比预期短
判读：失败。资源 Size 字段需要按「多节跨页」处理，简单按节内取会截断。

往返5｜动作：换成 kitty_dump 的节级导出，不再手算
kitty_dump addr=0xRSRC_VA size=0x<.rsrc 的 VirtualSize> path=logs\\rsrc.bin sections=true
回包：落出 rsrc.bin + rsrc.bin..rsrc.bin
判读：拿到完整资源节，载荷不再是截断的。

收敛｜末态验证
kitty_die action=detect target=logs\\rsrc.bin..rsrc.bin
回包：合法 PE，节表自洽，入口可见
kitty_patch action=hash path=logs\\rsrc.bin..rsrc.bin
末态：内嵌载荷可独立分析（有自己的 PE 头、节表、入口）。
复盘：资源偏移是 RVA，不是文件偏移；动手算之前先确认字段语义。""",
),
(
"以为样本是 .NET，用 dnSpy 打开一片空白。三段纠正。",
"""往返1｜动作：看到 PE 头有 CLR 相关字样，直接上 dnSpy
kitty_dnspy action=decompile target=APP.exe out=logs\\dnspy-app
回包：产出为空 / 只有 <Module>
判读：第一次失败。CLR 目录存在不代表有托管代码 —— 也可能是 NativeAOT 或单文件打包。

往返2｜动作：改查 CLR 目录是否真有元数据
kitty_patch action=info path=APP.exe
回包：CLR Runtime Header 的 RVA/Size 看起来非零
判读：还需再验一步 —— RVA 指向的位置是否有合法 COR20 头（首 4 字节 cb=0x48）。

往返3｜动作：读 COR20 头
kitty_patch action=find path=APP.exe pattern="48 00 00 00" from=<CLR_RVA 对应文件偏移> limit=4
回包：命中
判读：COR20 头存在，但仍可能是「只有头、无 IL」。

往返4｜动作：直接看元数据流
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0x<CLR_RVA>|bytes:72"
回包：MetaData 的 RVA 非 0 但 Size 很小（<0x100）
判读：坐实 —— 元数据被剥掉，只有头，dnSpy 当然空白。

往返5｜动作：改走 native 路线
kitty_ida action=analyze target=APP.exe
kitty_ida action=functions out=logs\\ida-app-<ts> limit=80
回包：函数数正常，有业务结构
判读：正确路径。

收敛｜末态验证
kitty_sym action=imports path=APP.exe
回包：导入面完整（非托管程序不会只导 mscoree）
kitty_die action=detect target=APP.exe
末态：确认 native 程序 + 元数据被剥 + 可用 IDA 正常分析。
复盘：托管判定要三步（目录存在 → COR20 头 → 元数据 Size），只看第一步必翻车。""",
),
(
"想读一个 4KB 的结构体，MEMDUMP_HEX 被截。两次返工后写对。",
"""往返1｜动作：一次读 4096 字节
kitty_ce op="MEMDUMP_HEX|0x7FF6DAE12000|4096"
回包：十六进制串，但尾部不足
判读：第一次不完整。单次上限就是 4096 字节，加上分隔符后返回被截。

往返2｜动作：改成 8192 想「一次到位」
kitty_ce op="MEMDUMP_HEX|0x7FF6DAE12000|8192"
回包：被本地拒绝或只回 4096
判读：第二次失败。上限是硬的，加大参数无效。

往返3｜动作：分两块，但第二块起点算错（漏了 0x1000 对齐）
kitty_ce op="MEMDUMP_HEX|0x7FF6DAE12000|4096"
kitty_ce op="MEMDUMP_HEX|0x7FF6DAE14000|4096"    ← 中间漏了 0x1000
回包：两块拼起来长度 8192 但内容不连续
判读：第三次失败。分块起点必须是 start+4096，不是按页跳。

往返4｜动作：按 +4096 连续分块，并逐块校验长度
kitty_ce op="MEMDUMP_HEX|0x7FF6DAE12000|4096"
kitty_ce op="MEMDUMP_HEX|0x7FF6DAE13000|4096"
判读：每块返回长度应为 4096*2 个十六进制字符（不含分隔）；
短了说明该块跨了未映射页。
kitty_prot action=query addr=0x7FF6DAE13000
回包：State=COMMIT
判读：可读，块完整。

收敛｜末态验证
拼接后总长 = 8192 字节
结构体字段按表解析：
kitty_ce op="R|0x7FF6DAE12000|dword"  → 结构首字段
kitty_ce op="R|0x7FF6DAE12000|bytes:4" → 与该字段小端字节序一致
末态：完整 8KB 落盘 + 首字段双路验证一致。
复盘：MEMDUMP_HEX 按 4096 连续切，别跳页；每块校验长度。""",
),
(
"找主机名配置，扫描类型选错三次。",
"""往返1｜动作：按 dword 扫短字符串编码
kitty_ce op="S_NEW|dword|0x74736F68|0x7FF6DADB1000|0x7FF6DAE00000" wait=true
回包：n=0
判读：第一次失败。0x74736F68 是 "host" 的小端 dword，但字符串往往不是 4 字节对齐。

往返2｜动作：换 word
kitty_ce op="S_NEW|word|0x6F68|0x7FF6DADB1000|0x7FF6DAE00000" wait=true
回包：n=大量（几千）
判读：第二次失败。两字节值太常见，命中爆表，没有判别力。

往返3｜动作：换 bytes:8 精确匹配
kitty_ce op="S_NEW|bytes:8|686F73743A2F2F|0x7FF6DADB1000|0x7FF6DAE00000" wait=true
回包：ERR| 类型/长度不匹配（val 位数与 N 不符）
判读：第三次失败。bytes:N 的 val 必须正好 N 字节 —— 8 字节要 16 个十六进制字符，
我给了 6 字节的值。

往返4｜动作：值补足到 8 字节
kitty_ce op="S_NEW|bytes:8|686F73743A2F2F00|..." 仍错（7 字节）
改正：0x68 0x6F 0x73 0x74 0x3A 0x2F 0x2F = 7 字节 → 用 bytes:7
kitty_ce op="S_NEW|bytes:7|686F73743A2F2F00" 仍不对
最终：明确选 bytes:7 且 val=686F73743A2F2F
回包：n=1
判读：命中。

往返5｜动作：回读验证
kitty_ce op="S_GET|0|1"
kitty_ce op="R|0x7FF6DAD5A100|bytes:32"
回包：68 6F 73 74 3A 2F 2F ... = "host://..." 
判读：确认。

收敛｜末态验证
kitty_ce op="R|0x7FF6DAD5A100|bytes:7" → 与扫描值逐字节一致
末态：配置串地址确认，前 32 字节含完整前缀。
复盘：bytes:N 的 val 长度必须精确等于 N；用 word 扫短串会淹；先定字符串边界再扫。""",
),
(
"被骗了一次：以为在改血量，其实改的是显示缓存。三段。",
"""往返1｜动作：扫到 1500 就写
kitty_ce op="S_NEW|dword|1500|0x7FF6DADB1000|0x7FF6DADCD1000" wait=true top=20
kitty_ce op="W|0x7FF6DAE12340|dword|100" confirm=true
回包：写入成功，界面立刻变 100
判读：看起来成功 —— 但这是陷阱。

往返2｜动作：等一秒再看
kitty_ce op="R|0x7FF6DAE12340|dword"
回包：1500（自己变回去了）
判读：第二次失败。写进去的值被覆盖 → 我改的是显示缓存，每帧从真值重算。

往返3｜动作：改判据 —— 找「写回」的那个源
kitty_ce op="S_NEW|dword|1500|0x7FF6DADB1000|0x7FF6DADCD1000" wait=true top=20
判据：这次不取第一个，而是对每个候选：
kitty_ce op="W|0xCAND|dword|100" confirm=true → 立刻 kitty_ce op="R|0xCAND|dword"
回包：前一两个都回 1500（被覆盖）；第三个回 100 且稳定
判读：稳定不回滚的那个才是真值。

往返4｜动作：确认它是真值（跨视图 + 时间）
kitty_km action=read addr=0xCAND vt=dword → 100
等 2 秒再读：kitty_ce op="R|0xCAND|dword" → 100
判读：两视图一致 + 时间上稳定 → 真值地址。

收敛｜末态验证
kitty_ce op="R|0x7FF6DAE00988|dword" → 100（2 秒后仍 100）
kitty_km action=read addr=0x7FF6DAE00988 vt=dword → 100
末态：写入后稳定不回滚、双视图一致。之前的 0x...2340 标记为显示缓存（已排除）。
复盘：写后必须等一会再回读；立刻回读成功不代表改对了。""",
),
(
"想 hook 一个函数，三次下错断点。",
"""往返1｜动作：按磁盘文件偏移下断点
kitty_dbg action=bp addr=0x1A2B4C access=execute
回包：断点设置成功但永不命中
判读：第一次失败。0x1A2B4C 是文件偏移/RVA，不是运行时 VA。

往返2｜动作：加模块基址但用了磁盘 ImageBase
kitty_dbg action=bp addr=0x140001000+0x1A2B4C 表达式错
改成 0x14001B2B4C
回包：仍是永不命中
判读：第二次失败。磁盘 ImageBase（0x140000000）与运行时 base 不同（ASLR）。

往返3｜动作：取运行时 base 再算
kitty_ce op=MODENUM
回包：kitty-target.exe|0x7FF6DADB1000|1|0
kitty_dbg action=bp addr=0x7FF6DADB1000+0x1A2B4C → 0x7FF6DAF53B4C
回包：命中
判读：这一步对了。

往返4｜动作：命中后发现下在了错误的指令上
kitty_dbg action=regs
回包：rcx/rdx 都是无意义小值
kitty_dbg action=go step=stepover
判读：下在函数中段的比较指令上了，不是入口。要往前找序言。

往返5｜动作：用符号定位函数入口，而不是靠偏移猜
kitty_sym source=mem module=kitty-target.exe action=resolve name=<导出名>
回包：VA
kitty_dbg action=bp addr=<VA> access=execute
回包：命中，regs 里 rcx 是有效对象指针

收敛｜末态验证
kitty_dbg action=regs → rcx 指向堆对象
kitty_ce op="R|0xRCX|dword" → 读到合法值
kitty_dbg action=bp_del id=<id>
kitty_dbg action=detach
kitty_status probe=true → pending=0
末态：命中断点位于函数入口、寄存器可用、断点已清理、通道干净。
复盘：断点地址三要素 = 运行时 base + RVA；能拿符号就别用偏移。""",
),
(
"改 PE 校验分支，expect 拒绝了我三次。",
"""往返1｜动作：读文件偏移，替换字节
kitty_patch action=patch path=TARGET.dll at=0x1234 expect="74 05" bytes="EB 05" confirm=true
回包：ERR|EXPECT_MISMATCH
判读：第一次失败。0x1234 处不是 74 05 —— 偏移算错。

往返2｜动作：以为 RVA 就是文件偏移
算出 RVA=0x1234 直接当文件偏移用
回包：仍 MISMATCH
判读：第二次失败。RVA 与文件偏移之间差一节的对齐（节.VirtualAddress → PointerToRawData）。

往返3｜动作：用 va: 前缀让工具自己换算
kitty_patch action=patch path=TARGET.dll at=va:0x7FF6DADB2000 expect="74 05" bytes="EB 05" confirm=true
回包：ERR| 无法解析 VA（磁盘文件没有运行时基址）
判读：第三次失败。va: 需要模块已加载；磁盘文件只有 RVA。

往返4｜动作：改用 rva: 前缀
kitty_patch action=patch path=TARGET.dll at=rva:0x1234 expect="74 05" bytes="EB 05" confirm=true
回包：ERR|EXPECT_MISMATCH（原字节不是 74 05）
判读：偏移对了，但原字节判断错。回头核指令。

往返5｜动作：先 find 定位真实字节
kitty_sym action=exports path=TARGET.dll
kitty_patch action=find path=TARGET.dll pattern="74 ?? 48 8B" limit=8
回包：命中偏移 0x122C
kitty_patch action=patch path=TARGET.dll at=rva:0x122C expect="74 05" bytes="EB 05" confirm=true
回包：成功 + 已建 .bak + 校验和重算
判读：expect 必须来自 find 的实际命中，不能凭记忆写。

往返6｜动作：字节算错一次，用汇编器核对
kitty_asm action=assemble code="jmp <目标>" base=0x<该指令VA>
回包：给出 EB 05 / E9 xx xx xx xx 的正确形态
判读：短跳 vs 近跳的字节数不同，手写容易算出越界位移。

收敛｜末态验证
kitty_patch action=find path=TARGET.dll pattern="EB 05" from=0x122C limit=1 → 命中
kitty_patch action=hash path=TARGET.dll → 哈希已变
kitty_patch action=rollback path=TARGET.dll → 哈希回原值（先验回滚可用）
再 patch 一次恢复目标状态
末态：字节确认替换、哈希变化、回滚路径已验证。
复盘：at= 用 rva: 前缀；expect 来自 find；跳转字节用 kitty_asm 算。""",
),
(
"想批量改 20 个值，BATCH 里混了扫描，回包全错位。",
"""往返1｜动作：把扫描也塞进 BATCH
kitty_ce ops=["S_NEW|dword|1500|0x7FF6DADB1000|0x7FF6DADCD1000","R|0x7FF6DAE12340|dword"]
回包：第一条回 pending，第二条回的是扫描过程里的某条内部回包
判读：第一次失败。异步作业不能进 BATCH —— 它会打断顺序语义。

往返2｜动作：改成先扫再批量写
kitty_ce op="S_NEW|dword|1500|..." wait=true top=20
回包：n=37
kitty_ce ops=[... 20 条 W ...]
回包：逐条 OK
判读：顺序对了，但写操作没有回读，等于没验证。

往返3｜动作：加回读，但回读也塞进同一个 BATCH
kitty_ce ops=["W|0xA|dword|100","R|0xA|dword","W|0xB|dword|100","R|0xB|dword"]
回包：回包顺序正确，但 W 需要 confirm 标志，未带 confirm 的 W 被拒
判读：第三次失败。BATCH 里的写同样要 confirm。

往返4｜动作：分两批 —— 写一批（带 confirm），读一批
kitty_ce ops=[... 20 条 W，逐条带 confirm 语义均被受理 ...]
kitty_ce ops=[... 20 条 R ...]
回包：20 条写全部 OK，20 条读全部返回值
判读：正确。写与读分开批次，读批就是验证批。

往返5｜动作：比对
判读：20 条 R 值是否全部等于写入值。
回包：17 条一致，3 条回原值 → 这 3 个是显示缓存（被覆盖）。

收敛｜末态验证
kitty_ce ops=[17 条 R] → 全部等于目标值
kitty_ce op=SYNC_ARCHIVE → kitty_ce op=SYNC_STAT（四项 0）
末态：17/20 生效且可证明，3 个被排除并记录原因。
复盘：BATCH 只放同步 OP；写与读分两批；读批就是验证批。""",
),
(
"以为样例是 64 位，结果所有偏移都错。",
"""往返1｜动作：按 x64 惯例读指针
kitty_ce op="R|0x7FF6DAE12340|qword"
回包：0x00000000000005DC（低 4 字节是 1500，高 4 字节为 0）
判读：看着像「值为 1500 的指针」，实际是 32 位程序里的 dword 值被当 qword 读。

往返2｜动作：按这个 qword 去反查指针
kitty_ce op="P_BACK|0x5DC|0x7FF6DADB1000|0x7FF6DADCD1000"
回包：n=大量
判读：第二次失败。0x5DC 是小值，到处都是，毫无判别力。

往返3｜动作：核位数
kitty_ce op=MODENUM
回包：kitty-target.exe|0x00400000|0|0
判读：关键 —— is64=0，base=0x00400000。这是 32 位进程，我前面用的 0x7FF6... 地址全是幻觉。

往返4｜动作：纠正后重取窗口
kitty_ce op="R|0x00400000+0x3C|..." 表达式被拒 → 0x0040003C
kitty_ce op="R|0x0040003C|dword" → e_lfanew
kitty_ce op="R|0x00400000+0xE8+0x50" → 0x004000F8? 逐段算：
判读：SizeOfImage 读取成功，窗口建立。

往返5｜动作：按 4 字节重扫
kitty_ce op="S_NEW|dword|1500|0x00400000|0x00400000+SizeOfImage" wait=true top=20
回包：n=9
判读：命中量级正常。

收敛｜末态验证
kitty_ce op="R|0x00412A40|dword" → 1500
kitty_ce op="W|0x00412A40|dword|100" confirm=true
kitty_ce op="R|0x00412A40|dword" → 100
kitty_km action=read addr=0x00412A40 vt=dword → 100
末态：32 位地址空间中写入并双视图回读一致。
复盘：任何 OP 之前先看 MODENUM 的 is64；位数错时所有读都不报错，只给错值。""",
),
(
"试着用 kernel 路由写，被拒两次后改对。",
"""往返1｜动作：直接内核写
kitty_km action=write addr=0x7FF6DAE12340 val=100 vt=dword
回包：要求 confirm=true
判读：第一次拒。内核写必须显式确认，这是设计上的二次闸门。

往返2｜动作：加 confirm
kitty_km action=write addr=0x7FF6DAE12340 val=100 vt=dword confirm=true
回包：ERR|NOT_ATTACHED
判读：第二次拒。内核路由要先 attach 到目标进程。

往返3｜动作：先 attach
kitty_km action=info
回包：pid=0 / 未附加
kitty_km action=attach pid=<pid>
回包：PEProcess + 内存 + 区域表 打开成功
判读：这一步对了。

往返4｜动作：重试写入
kitty_km action=write addr=0x7FF6DAE12340 val=100 vt=dword confirm=true
回包：OK
判读：受理，但不等于生效。

往返5｜动作：回读
kitty_km action=read addr=0x7FF6DAE12340 vt=dword → 100
kitty_ce op="R|0x7FF6DAE12340|dword" → 100
判读：两视图一致。

往返6｜动作：想验物理层，用了 KM_PW
kitty_km action=pwrite pa=0xPA val=100
回包：永久拒绝（该原语会卡死 Lua 引擎）
判读：这条路本来就不通，取证只走 pread。
kitty_km action=pread pa=0xPA vt=dword → 100

收敛｜末态验证
kitty_km action=read → 100；kitty_ce op="R" → 100；kitty_km action=pread → 100
末态：三视图一致，写入真实生效。
复盘：内核写三步 = attach → confirm → 回读；物理写永久不走。""",
),
(
"想拿一份干净的导入表，走了四次弯路。",
"""往返1｜动作：读磁盘导入表
kitty_sym action=imports path=SAMPLE.exe
回包：12 项，全是 LoadLibrary/GetProcAddress
判读：第一次失败。磁盘导入被壳裁过。

往返2｜动作：dump 内存镜像再读
kitty_dump module=SAMPLE.exe path=logs\\m.bin
kitty_sym action=imports path=logs\\m.bin
回包：导入项指向模块内地址（无效）
判读：第二次失败。没 unmap、没修 IAT。

往返3｜动作：unmap + fix_iat
kitty_dump module=SAMPLE.exe unmap=true fix_iat=true path=logs\\m2.bin reference=SAMPLE.exe
回包：一致率 91%
kitty_sym action=imports path=logs\\m2.bin
回包：导入 34 项，但有 6 项名字是乱码
判读：好多了，但仍有脏项 —— 这 6 项可能是延迟导入或运行期解析，ILT 里没有。

往返4｜动作：分开处理脏项，不强行修
判据：对乱码项去内存里直接读：
kitty_sym source=mem module=SAMPLE.exe action=imports filter=.
回包：内存视图给出完整 40 项（含那 6 项）
判读：正确路径 —— 磁盘 ILT 缺的那些，内存里已经有了。

收敛｜末态验证
合并两份：磁盘 34 项 + 内存补 6 项 = 40 项
抽 5 项用 kitty_sym source=mem action=resolve name=<函数> 验证地址一致
回包：5/5 一致
末态：导入表 40 项可解析，抽验全对。
复盘：磁盘 + 内存两份导入互补；脏项不要硬修，去内存里读。""",
),
(
"以为要 hook 才能拿数据，最后发现不用 hook。四次调整。",
"""往返1｜动作：下 API 断点抓参数
kitty_x64dbg action=seed addr=kernel32.ReadFile seedCmd=log
回包：命中极频繁（每帧都有），抓不过来
判读：第一次方向错。太底层的 API 命中率过高，噪音淹没信号。

往返2｜动作：换更高层、更稀有的 API
kitty_x64dbg action=seed addr=<游戏自己的函数>
回包：需要符号，没有
判读：第二次失败。没有符号就定位不到「稀有函数」。

往返3｜动作：改用内存快照差分，不做 hook
kitty_ce op="S_SNAP|bytes:16|0x7FF6DADB1000|0x7FF6DADCD1000"
触发一次功能 → kitty_ce op=S_CHANGED
回包：n=0（这个窗口没变）
判读：第三次失败。窗口给错 —— 数据在堆上，不在模块里。

往返4｜动作：把窗口改到堆
kitty_prot action=query addr=<目标对象>
kitty_ce op="S_SNAP|bytes:16|0x1D2A0000000|0x1D2A0100000"
触发功能 → kitty_ce op=S_CHANGED
回包：n=6
判读：有变化了。

往返5｜动作：不用 hook 也拿到数据 —— 直接读变化页
kitty_ce op="S_GET|0|6"
kitty_ce op="R|0x1D2A0012340|qword" → 0x1D2A0045000
kitty_ce op="R|0x1D2A0045000|dword" → 目标值
判读：一次间接读拿到了数据，全程无 hook。

收敛｜末态验证
连续两次触发功能，同一地址值跟随变化（两次 R 回读不同且与界面一致）
末态：数据获取路径 = 快照差分定位指针 + 静态偏移读取，零 hook、零注入。
复盘：hook 是最后手段。先试快照差分 —— 它不需要代码执行、不需要符号。""",
),
(
"样本在虚拟机里跑不起来，我以为是反虚拟机。三段排查后不是。",
"""往返1｜动作：判定为反虚拟机检查
kitty_die action=detect target=SAMPLE.exe
回包：无已知反虚拟机特征（无 VM 相关字符串、无 cpuid 密集调用）
判读：第一次判断存疑。特征面不支持「反虚拟机」这个结论。

往返2｜动作：静态找反虚拟机典型指令
kitty_patch action=find path=SAMPLE.exe pattern="0F A2" limit=16
回包：cpuid 指令存在但很常见（CRT 也会用）
判读：第二次证据不足。cpuid 存在不构成判据。

往返3｜动作：改成看它为什么退出 —— 抓退出点而不是猜
kitty_x64dbg action=run target=SAMPLE.exe
回包：进程在 ExitProcess 前有一段错误处理
kitty_x64dbg action=seed addr=kernel32.ExitProcess seedCmd=log
判读：抓 exit 前最后一个模块调用。

往返4｜动作：看退出码旁的字符串/错误码
kitty_x64dbg action=readdb addr=<栈上的退出码参数>
回包：错误码对应「缺少某个运行库」
kitty_sym action=imports path=SAMPLE.exe filter=VCRUNTIME
回包：依赖 vcruntime140.dll 的特定版本
判读：真相 —— 不是反虚拟机，是缺运行库。

往返5｜动作：补齐依赖再跑
kitty_ce op=MODENUM
回包：模块表里出现新加载的 vcruntime
判读：能正常初始化了。

收敛｜末态验证
kitty_ce op=PING → 正常
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+SIZE" wait=true top=10 → n>0（业务逻辑跑到）
末态：样本在虚拟机内正常执行，行为面可观测。
复盘：跑不起来先抓退出码与最后调用，别先归因到「反虚拟机」——那是最贵的错误假设。""",
),
(
"我只是想验证一次写入成功，被两个假象骗了。",
"""往返1｜动作：写完立刻回读
kitty_ce op="W|0x7FF6DAE12340|dword|100" confirm=true
kitty_ce op="R|0x7FF6DAE12340|dword" → 100
判读：看起来成功。这是第一个假象。

往返2｜动作：等一会再回读
（3 秒后）kitty_ce op="R|0x7FF6DAE12340|dword" → 1500
判读：回滚了。说明写的是缓存层，真值在别处被重算。

往返3｜动作：换内核视图读
kitty_km action=attach pid=<pid>
kitty_km action=read addr=0x7FF6DAE12340 vt=dword → 1500
判读：第二个假象被破 —— 用户态视图在写入瞬间返回我写入的值，
内核视图从一开始就是 1500，说明写入被「吞」了。

往返4｜动作：查是不是影子页
kitty_dualview addr=0x7FF6DAE12340 vt=dword samples=2
回包：R=100 / KM_R=1500 / 物理=1500（分叉）
判读：坐实。R 与 KM_R 分叉，用户态被拦截（hook 返回伪造值）。

往返5｜动作：改走 AE 可用的写路径
kitty_wpb addr=0x7FF6DAE12340 val=100 vt=dword restore=true accept_protection_bypass=true
kitty_ce op="R|0x7FF6DAE12340|dword" → 100
kitty_km action=read addr=0x7FF6DAE12340 vt=dword → 100
判读：两视图一致，这次是真写。

收敛｜末态验证
kitty_dualview addr=0x7FF6DAE12340 vt=dword samples=3 → 无分叉
3 秒后复读：kitty_ce op="R|0x7FF6DAE12340|dword" → 100（不再回滚）
末态：写入稳定、双视图一致、分叉证据已落 logs/anti-ace-<date>.jsonl。
复盘：写后回读要「等一会 + 跨视图」；立刻单视图回读会被伪造值骗。""",
),
(
"想要一个函数的调用参数，三次取错位置。",
"""往返1｜动作：在函数入口读寄存器
命中入口后立刻 kitty_dbg action=regs
回包：rcx=0，rdx=0
判读：第一次失败。函数入口处寄存器还没被初始化（或用了别的传参约定）。

往返2｜动作：以为参数在栈上
kitty_ce op="R|0xRSP|qword"
回包：栈顶是返回地址（落在模块内），下一个不是参数
判读：第二次失败。x64 前四个整型参数在寄存器，第五个才在栈 +0x28。

往返3｜动作：按 x64 约定逐级核 —— 但读错了时机
在入口读 rcx/rdx/r8/r9
回包：r8/r9 有值但 rcx 是 0
判读：第三次失败一半。说明该函数第一参数确实为 0，或者我停在了一个 thunk。

往返4｜动作：确认断点位置是不是 thunk
kitty_dbg action=regs 里 rip 与 kitty_sym action=exports 的地址比对
回包：rip 落在导出地址 + 0x0，但函数体只有 jmp
判读：坐实是 thunk。要跟进目标。

往返5｜动作：跟跳转后重新取参
kitty_dbg action=go step=stepinto
kitty_dbg action=regs
回包：rcx 是有效指针，rdx 是小整数
kitty_ce op="R|0xRCX|bytes:32" → 读到结构体首字段

收敛｜末态验证
对 rcx 指针做 kitty_prot action=query → 归属堆
连续调用两次，rdx 值不同且与功能输入对应
末态：参数位置确定（rcx=对象指针，rdx=输入值），两次调用可区分。
复盘：入口命中不等于拿到参数 —— 先判 thunk，再判传参约定，再判时机。""",
),
]

# -*- coding: utf-8 -*-
"""re-pe-structure 源 part B (16-30)"""

PE_B = [
(
"节名是 .ggf 和 .themida，还有两个空的。这种还要往下逆吗？",
"""先判保护器档位再决定，别直接上调试器 —— 有些档位动态起来必崩。

指纹确认：
kitty_die action=detect target=SAMPLE.exe
判读：报 Themida/WinLicense 时看两点：
1) 是否有 VM 段（节名含 .vm 或两段零大小高熵节）；
2) 导入表是否只留 kernel32 的少数项 —— 保护器把真导入搬进自己的虚拟化区。

档位分流：
kitty_die action=detect 报「VM 保护」→ 静态只能拿到壳，逆向收益极低，
改走动态 dump + 重建：
kitty_ce op=MODENUM                              → 拿真实模块大小
kitty_ce op=PING                                 → 确认通道
kitty_dump module=SAMPLE.exe unmap=true fix_iat=true path=logs\\oep.bin
判读：unmap 后 OEP 是否落在非壳节、IAT 是否能解析出业务 API。
两项都成立才算 OEP 找对；IAT 全是壳地址 = 停在了壳的 stub，需要再等一段再 dump。

只加壳不虚拟化（SDK 弱档）时：
kitty_x64dbg action=seed addr=<OEP 候选> 走硬件断点绕 IAT 重定位，
判读：命中后 readdb 读栈，栈上返回地址落在原 .text = 已出壳。

退出条件：连续两次 dump 的 IAT 都无法解析业务 API → 判为强虚拟化档，记录并转等价值路径（行为面观察）。""",
),
(
"节 VirtualSize 是 0，RawSize 却有 0x8000。加载器会映射多少？",
"""映射 0x8000，但按 RoundUp(RawSize, SectionAlignment) 算，VirtualSize=0 不参与。
踩这个坑会让窗口算错，后面所有读都偏移。

先算准：
kitty_patch action=info path=SAMPLE.exe
判读：映射长度 = max(VirtualSize, SizeOfRawData) 按 SectionAlignment 上取整。
VirtualSize=0 时取 SizeOfRawData=0x8000。

验证实际映射：
kitty_ce op=MODENUM → 拿到的是整个模块的 VirtualSize 合计，不是单节
kitty_prot action=query addr=0xSECTION_VA
判读：返回的 RegionSize 就是加载器真实给的长度；RegionSize > 0x8000 = 后面接了相邻节，
这时按 0x8000 切窗口会漏读邻接数据。

对扫描的影响：
kitty_ce op="S_NEW|dword|1500|0xSECTION_VA|0xSECTION_VA+0x8000"
判读：若命中 0 且 query 显示该区可读，说明值不在这个节，扩窗到相邻节而不是怀疑 OP 写错。

落判据：VirtualSize=0 的节一律以 kitty_prot query 的 RegionSize 为准建窗口，
不手工推算 —— 手算在合并节、尾部对齐两种情况会同时出错。""",
),
(
"重定位目录指向 .text 内部，这正常吗？",
"""不正常，但有固定成因：节被合并或重定位表被搬过。

先看 RELOC 节是否存在：
kitty_patch action=info path=SAMPLE.exe
判读：无独立 .reloc 节、且 Reloc Directory 的 RVA 落在 .text 的 RVA 区间内 → 是构建期合并。
正常链接器不会这么放，但某些打包器（把壳与重定位一起塞进可执行节）会。

验重定位块合法性：
kitty_ce op=MEMDUMP_HEX 不适用（磁盘问题），用 kitty_patch action=find 定位 RVA 对应文件偏移，
再按 IMAGE_BASE_RELOCATION 结构读：第一个 DWORD 是 PageRVA，第二个是 BlockSize。
判读：BlockSize 合理（8 的倍数且不越界）、PageRVA 对齐 0x1000 → 表是完整的，只是位置怪；
PageRVA 乱跳 → 表被加密，动态期才还原。

对分析的影响：
kitty_die action=detect 报「可重定位」，但 ASLR 实际是否生效要看 PE 头 DllCharacteristics
的 DYNAMIC_BASE 位。位没置 → 基址固定，直接硬编码 base 可以；位置了 → 必须 MODENUM 取 base。

结论：位置异常不影响可用性，影响的是「能不能静态算 VA」；
一律走 kitty_ce op=MODENUM 拿真实 base 再算，别信文件里的 ImageBase。""",
),
(
"Bound Import 目录非空，这年头还有用吗？",
"""基本没用，但它是构建年代的指纹，能反推工具链和样本批次。

读出来：
kitty_patch action=info path=SAMPLE.exe
判读：Data Directory 第 11 项（Bound Import）RVA/Size 非零。
结构是 IMAGE_BOUND_IMPORT_DESCRIPTOR，含模块名与 TimeDateStamp。

它的含义：
绑定导入是「按导出时间戳预解析地址」的老优化，现代 Windows 在 ASLR 下基本会忽略并重解析。
所以：非空 ≠ 能利用，只说明链接时开了 /BIND 或用了老版本工具链。

情报价值：
1) TimeDateStamp 与 PE 头 TimeDateStamp 对比 → 差值给出「链接后多久又被改写」（加壳/签名回填）；
2) 绑定模块列表（常含 msvcr71/msvcp60 之类）→ 定位到 2000 年代工具链；
3) 若同批样本里只有部分有该目录 → 分批次的证据。

不要做的：不要拿绑定地址去静态解析 IAT，ASLR 下这些值全部失效，
kitty_sym source=mem 从内存读才是有效路径（先 kitty_ce op=MODENUM 取 base）。""",
),
(
"Security 目录指向文件尾，但 kitty_die 说没签名。哪个对？",
"""都对：目录存在不等于签名有效，签名可能被剥或校验失败。

三档验证：
1) 目录存在性：
kitty_patch action=info path=SAMPLE.exe   → Data Directory 第 4 项 RVA 非零
2) 结构可解析性：
kitty_patch action=find path=SAMPLE.exe pattern="30 82" from=<security_offset>
判读：30 82 是 DER SEQUENCE 长形式头，命中说明 WIN_CERTIFICATE 里塞的是 PKCS#7；
不命中 → 目录是伪造的（有些加壳器会随手填一个 RVA）。
3) 有效性：WIN_CERTIFICATE 的 dwLength 必须 ≤ 目录 Size，且证书链能解。

常见成因（按概率）：
a) 加壳器剥签名后没清目录 —— 最常见；
b) 自签名证书，工具链不认；
c) 目录 RVA 指向被裁掉的 overlay。

判据落地：kitty_die 报「无签名」时以它为准（它做的是完整解析），
但把「目录存在 + 解析失败」这一组合记进样本卡片 —— 这是「签名被主动移除」的强证据，
比单纯无签名有信息量：说明作者知道要规避基于签名的白名单。""",
),
(
"导入全是 ordinal，一个函数名都没有。怎么恢复 API 面？",
"""按目标模块的导出序号表反查，这是唯一确定性路径。

先定每条的归属模块：
kitty_sym action=imports path=SAMPLE.exe
判读：每条显示 Ordinal=N + 所属 DLL。把 (DLL, N) 收集成集合。

逐个 DLL 建序号表：
kitty_sym action=exports path=C:\\Windows\\System32\\KERNEL32.dll
判读：导出项按名字排序展示，但序号由 OptionalHeader 的 Export Base 决定：
第 i 个导出项（含转发）对应序号 Base+i。
所以正确做法是按导出项顺序索引，不是按名字排。

交叉验证（关键）：
kitty_ce op=OPEN|<pid> 打开样本进程后
kitty_ce op="R|0xIAT_ENTRY|qword"
kitty_sym source=mem module=KERNEL32.dll action=exports filter=.
判读：用 IAT 里解析出的真实 VA 去反查目标模块的导出区间，
落在哪个导出函数体内就是哪个 —— 这是运行期真值，能证伪静态序号映射。

退出条件：静态序号表与 IAT 真值抽样 5 条全一致 → 恢复的 API 面可用；
不一致说明样本用的不是系统同名 DLL（自带一份），改从自带的 DLL 建表。""",
),
(
"Delay Import 目录存在，里面的模块一个都没加载。这解释了什么？",
"""解释了「静态看不到、运行时才出现」的调用面 —— 延迟导入是刻意的载荷隐藏手段。

读出延迟导入表：
kitty_patch action=info path=SAMPLE.exe
判读：Data Directory 第 13 项（Delay Import）RVA/Size。结构是 ImgDelayDescr（32 字节），
字段 grAttrs 的最低位 dlattrRva=1 时，其余字段按 RVA 解释；为 0 时按 VA 解释（老链接器）。

对照实际加载：
kitty_ce op=MODENUM
判读：延迟导入的 DLL 若不在模块表里，说明对应函数还没被调用 —— 这正好是行为面的时间线。

强制触发并观察：
在目标功能路径上操作一次（打开某界面/发一次请求），再
kitty_ce op=MODENUM
判读：新出现的模块就是被延迟导入拉起的，第一出现顺序即调用顺序。

价值判断：延迟导入通常用于
1) 降低启动开销；
2) 隐藏敏感依赖（如 psapi/advapi 组合）；
3) 规避静态扫描。
第三种最常见 —— 把延迟导入的模块清单直接当 IOC 记录，
再用 kitty_sym action=imports 逐个确认里面有没有提权/注入类 API。""",
),
(
".text 节属性是可写可执行。这是编译错误还是设计？",
"""设计。W+X 是自修改代码或热补丁框架的标志，正常编译器产出 RWX .text 极少。

先确认属性：
kitty_patch action=info path=SAMPLE.exe
判读：Characteristics = 0xE0000020（含 IMAGE_SCN_MEM_WRITE 0x80000000 与 EXECUTE 0x20000000）。

运行期核对（属性可能被加载器改）：
kitty_prot action=query addr=0xTEXT_VA
判读：返回的 Protect 若是 RWX 或 RW，与磁盘一致；若是 RX，说明加载后有代码把自己改回去，
那更有意思 —— 说明写窗口只存在于初始化阶段。

定位谁在写：
kitty_ce op="S_SNAP|bytes:16|0xTEXT_VA|0xTEXT_VA+0x1000"
跑起来后 S_CHANGED，变化页地址即自修改落点。
再到 kitty_ghidra action=search filter=<落点地址的十六进制> 找写入指令。

判读要点：W+X 本身不是恶意的证据（.NET ReadyToRun、JIT、加壳器都会这样），
证据链要闭合到「写入的内容哪来」—— 用 kitty_ce op="MEMDUMP_HEX|0xCHANGED_VA|128"
取变化后的字节，首字节是合法序言才算真自修改代码，否则只是数据被搬到代码页。""",
),
(
"入口点落在最后一个节的末尾，正常吗？",
"""不正常，这是加壳器最典型的形态：OEP 被换成壳的 stub，原始入口被藏起来。

量化异常：
kitty_patch action=info path=SAMPLE.exe
判读：AddressOfEntryPoint 的 RVA 若 ≥ 最后一个节的 VirtualAddress，且该节熵 >7，
基本可以判定入口是壳 stub。正常编译器入口落在 .text 中部（CRT 起始）。

拿真 OEP 的两条路：
静态：kitty_ghidra action=analyze target=SAMPLE.exe 后
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=entry
判读：stub 尾部通常是一次大跳转（jmp rax / push+ret），跳转目标就是 OEP 候选。

动态：kitty_x64dbg action=seed addr=<stub 入口 VA> seedCmd=run
判读：单步过完解压循环后，第一次进入「非壳节」的地址即 OEP。
记录时用模块内偏移（VA - MODENUM base），跨重启可用。

收敛判据：OEP 处首字节是可识别序言（48 89 5C 24 / 55 8B EC / 40 53）且该处能解出 CRT 初始化调用
→ OEP 正确，可以 dump。

dump 之后必须
kitty_dump module=SAMPLE.exe unmap=true fix_iat=true reference=SAMPLE.exe
判读：与参考文件的一致率给出壳的改动范围，低于 60% 说明还有一层。""",
),
(
"RT_ICON 有 47 个，但 exe 只有 2MB。这密度可疑吗？",
"""可疑。图标资源数量与文件体积严重不匹配时，先查是不是把载荷切成图标分片塞进去了。

算期望值：
kitty_patch action=info path=SAMPLE.exe
判读：47 个 RT_ICON 若每个按 16KB 算就是 750KB，占 2MB 的三分之一以上。
正常 exe 的图标总计几十 KB（多尺寸 ICO 合并存）。

看单个分片：
kitty_die action=detect target=SAMPLE.exe   → 拿 .rsrc RVA/Raw
kitty_dump addr=0xRSRC_VA size=0xRSRC_SIZE path=logs\\rsrc.bin sections=true
判读：打开 rsrc 单节文件，RT_ICON 的数据块若不以 ICO 的 BITMAPINFOHEADER 开头
（首 4 字节是 biSize=0x28/0x0C/0x6C），而是任意高熵字节，就是伪装分片。

拼接验证：
按资源目录里各 RT_ICON 的 OffsetToData 顺序拼接（不是按 ID 数值），
拼完看首字节是否为 4D 5A 或 50 4B。
判读：命中 → 拼出完整载荷，用 kitty_die 复检；
不命中 → 可能需要按 ID 排序或每片带 4 字节长度头，读第一片的头部猜格式。

退出条件：拼三次仍不成立 → 记录为「资源分片但格式未知」，
转动态：kitty_ce op="S_SNAP|bytes:16|0xRSRC_VA|0xRSRC_VA+0x2000" 看运行期哪片被读。""",
),
(
"校验和字段是 0，这个信息有用吗？",
"""有用，但只能当辅证：0 表示文件在签名/链接之后被改过，或者链接器本来就没算。

分情况：
kitty_patch action=info path=SAMPLE.exe
判读：OptionalHeader.CheckSum == 0 时看三处：
1) 有无 Security 目录 → 有目录但校验和 0，几乎必然是手工改过（签名工具会重算）；
2) 节表 RawSize 是否与文件实际长度自洽 → 不自洽说明追加了数据；
3) TimeDateStamp 是否晚于同批同源样本 → 改动时间线。

正面用法（不是判断恶意，是判断分析路径）：
校验和 0 + 导入表可解析 → 改动很可能只发生在非结构区（字符串/常量），
静态分析可以直接信节表，走 kitty_ghidra 正常流程。

校验和 0 + 节表自洽性差 → 结构区被动过，
此时 kitty_patch action=info 的节表不可信，改用运行时 kitty_ce op=MODENUM 的真实窗口。

补算验证：
kitty_patch action=hash path=SAMPLE.exe
判读：记下哈希；若你之后要做兼容性修补，kitty_patch action=patch 默认 fix_checksum=true，
会把校验和补上 —— 这也解释了为什么「补丁后校验和从 0 变成非 0」是正常现象，不是新线索。""",
),
(
"导入里 VirtualAlloc + VirtualProtect 成对出现，一定是恶意吗？",
"""不一定，但它是「运行期分配可执行内存」这个行为的必要条件，值得无条件跟进。

先看组合的完整度：
kitty_sym action=imports path=SAMPLE.exe filter=Virtual
判读：
- VirtualAlloc + VirtualProtect + memcpy(RtlMoveMemory) → 经典 shellcode 装载三件套；
- 再加 CreateThread / QueueUserAPC → 有执行调度；
- 只有 Alloc + Free → 可能只是大块缓冲，恶意度低。

看分配参数的来源：
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<调用 VirtualAlloc 的函数>
判读：flProtect 实参是否为 0x40（PAGE_EXECUTE_READWRITE）；
大小实参是否来自 .rsrc / 网络 recv 的返回值 —— 这两条任一成立，跟进价值高。

动态坐实：
kitty_ce op=ALLOC 不需要；直接观察目标自己的分配：
kitty_prot action=query addr=0xSUSPECT_VA
判读：若一块没有模块归属的地址是 RWX 且大小与资源块一致 → 装载点。
再用 kitty_ce op="MEMDUMP_HEX|0xSUSPECT_VA|256" 读内容，首字节是序言则是代码。

退出条件：三件套齐 + RWX + 内容为代码 → 判为运行期装载，dump 出来单独分析；
缺任一条 → 只记录，不投入时间去解。""",
),
(
"SizeOfHeaders 比正常大 4 倍，头部空隙能藏东西吗？",
"""能，而且是静态扫描最容易漏的位置：头部空间在所有节之前，多数工具只解析不遍历。

算净空：
kitty_patch action=info path=SAMPLE.exe
判读：SizeOfHeaders 正常是 SectionAlignment 上取整（常见 0x400）。若是 0x1000 或更大，
多出来的 (SizeOfHeaders - 实际头部结束) 就是可用空隙。

找空隙里的数据：
kitty_patch action=find path=SAMPLE.exe pattern="4D 5A" to=<SizeOfHeaders>
判读：在头部范围内搜 MZ，命中即内嵌 PE。
再补一次 kitty_patch action=find path=SAMPLE.exe pattern="1F 8B 08" to=<SizeOfHeaders> 查 gzip。

交叉确认「空隙是否被加载器映射」：
kitty_ce op=MODENUM → base
kitty_ce op="R|0xBASE+0x200|bytes:64"
判读：头部是按 SizeOfHeaders 映射的，所以空隙在内存里可读 —— 与「幽灵节」不同，
这里的隐藏数据是活的，任何内存 dump 都会包含它。

判据落地：SizeOfHeaders 异常时，把 [实际头结束, SizeOfHeaders) 区间当独立数据区枚举一遍，
这一段的产出往往比 .text 里的更高（常量表、密钥、二次载荷头都在这里）。
用 kitty_dump addr=0xBASE size=<SizeOfHeaders> path=logs\\headers.bin 一次取全。""",
),
(
"两个同名进程，MODENUM 拿到的是谁的？",
"""拿到的是你当前 OPEN 的那个，不是你以为的那个 —— 同名进程必须按 pid 钉死。

先看当前锚点：
kitty_ce op=CUR
判读：返回当前打开的 pid/名称。如果显示的是进程名而你开了两个实例，锚点可能已漂。

钉死：
kitty_ce op=LP
判读：列出候选 pid + 名称，把同名项全部挑出来，按启动时间/命令行分组（命令行可用宿主的
Get-CimInstance Win32_Process 只读查询佐证）。
kitty_ce op=OPEN|<pid>
kitty_ce op=CUR                                → 回读确认 pid 与预期一致

再做窗口：
kitty_ce op=MODENUM
判读：即使在两个实例里，同一模块的 base 也可能不同（ASLR 每次独立随机），
所以 base 必须从当前 pid 的 MODENUM 取，不能复用另一实例的。

写前必做回读：
kitty_ce op="R|0xADDR|dword"
判读：与你预期的旧值一致才写。同名双开时最典型的翻车是「写到另一个实例」，
表现为目标界面没变化但回读成功 —— 回读同 pid 才排除。

落判据：kitty_ce op=CUR 的 pid 写进会话记录，后续每条 OP 都先核一次。""",
),
(
"节名是标准的，熵也正常，但文件里找不到任何字符串。这说明什么？",
"""说明字符串被加密或编码，不是「没有字符串」——正常编译产物必然有 CRT 报错串、类型名、DLL 名。

先确认是不是「真没有」：
kitty_patch action=find path=SAMPLE.exe str=kernel32 limit=8
判读：连 kernel32 都搜不到，而导入表里确实有 KERNEL32.dll → 字符串表整体被处理过。
因为导入 DLL 名一定在磁盘上以 ASCII 存在（除非导入表也加密）。

判类型：
kitty_patch action=find path=SAMPLE.exe pattern="4B 00 45 00 52 00" limit=8
判读：UTF-16 形式也搜不到 → 不是编码问题，是加密/压缩。
kitty_die action=detect target=SAMPLE.exe
判读：.rdata 熵 >7 且 .text 熵正常 → 只有数据段被加密，典型「字符串加密器」（编译期宏加密 + 运行期解密）。
.rdata 与 .text 都高熵 → 整壳，另走脱壳流程。

解密点定位（字符串加密器的固定套路）：
kitty_sym action=imports path=SAMPLE.exe filter=RtlMoveMemory
判读：配合一次性 VirtualProtect 调用，就是「解密到栈上临时缓冲」的写法。
动态在解密函数返回处断，寄存器/栈上的明文即密钥派生结果。

退出条件：能取到任意一串明文 → 解密方式定型，写脚本批量还原；
取不到 → 记录并按「全壳」处理。""",
),
]

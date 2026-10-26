# -*- coding: utf-8 -*-
"""re-pe-structure 扩量 D（46-70）：紧凑型，每条 300-450 字，判据 + 命令 + 退出条件"""

PE_D = [
("导入表的 RVA 指向 .text 内部，不是 .idata。",
"""说明导入目录被搬进了代码节，壳的常见布局。

```
kitty_patch action=info path=SAMPLE.exe      → Data Directory[1] RVA
kitty_sym action=imports path=SAMPLE.exe     → 实际能否解析
```
判据：info 给的 RVA 落在 .text 区间内，而 sym 仍能列出导入项 → 目录位置异常但结构有效
（打包器把自己的 stub 与 idata 合并）。解析失败则说明 RVA 是伪造值。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xIDATA_RVA|160"
```
判读：内存里那 160 字节若是 IMAGE_IMPORT_DESCRIPTOR 链（每 20 字节一条），以内存为准。

退出：能给出「位置异常但有效 / 伪造」二分，并指出后续用磁盘还是内存视图。"""),

("入口点 RVA 是 0。",
"""入口为 0 的程序无法启动 —— 除非有 TLS 回调先把代码补好。

```
kitty_patch action=info path=SAMPLE.exe     → AddressOfEntryPoint
kitty_die action=detect target=SAMPLE.exe   → TLS 目录是否非空
```
判据：EP=0 且 TLS 目录有内容 → 入口由 TLS 回调在加载时写入；EP=0 且 TLS 空 → 文件损坏。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0x28|dword"     → 运行期 EP
```
判读：运行期 EP 从 0 变成非 0 = TLS 改写坐实；仍为 0 = 加载即失败，别浪费动态时间。

退出：给出「TLS 补入口 / 损坏」判定 + 运行期 EP 值。"""),

("数据目录 4 和 6 我分不清，哪个是签名？",
"""4 是 Security（签名），6 是 Reserved。写反会导致你去验证一段空数据。

```
kitty_patch action=info path=SAMPLE.exe
```
判读：按 PE 规范，Data Directory 索引：0 导出 / 1 导入 / 2 资源 / 3 异常 /
4 Security / 5 重定位 / 6 调试 / 9 TLS / 13 延迟导入 / 14 CLR。

```
kitty_patch action=find path=SAMPLE.exe pattern="30 82" from=<索引4 指向的偏移> limit=2
```
判读：命中 DER SEQUENCE 头 → 索引 4 里确有 PKCS#7；索引 6 出现 30 82 说明我把调试目录
当成了签名，回头核索引。

交叉核对：
```
kitty_die action=detect target=SAMPLE.exe
```
判读：kitty_die 报的「签名 / 无签名」应与索引 4 的内容一致；
报「无签名」但索引 4 非零 → 目录伪造。

退出：四个关键索引（1/2/9/14）各自的值抄进卡片，不靠记忆，且与 kitty_die 结论一致。"""),

(".pdata 条数是 0，但样本有几千个函数。",
"""异常。x64 编译器对所有非叶子函数必生成 unwind，条数 0 说明表被剥。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：.pdata 节存在但 Size=0，或节被删。两者都指「主动剥离」。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> limit=100
```
判读：函数识别正常 → 剥表只为对抗调试器栈回溯（DBG_REGS 拿不到调用栈），
不影响静态分析。

```
kitty_ce op="R|0xBASE+0xEP|bytes:8"
```
判读：入口序言里若出现手工 push/pop 全寄存器（保存现场），说明它自己维护栈帧。

退出：给出「剥 unwind 以对抗回溯」判定，并改用 kitty_x64dbg 的 readdb 读栈替代 unwind 展开。"""),

("导出表 Base 是 0。",
"""Base=0 时序号从 0 开始，很多工具默认从 1 算，导致序号错一位。

```
kitty_sym action=exports path=MODULE.dll
```
判读：对比返回的序号与名字。若第一个导出的序号显示 0，Base 就是 0。

```
kitty_sym action=imports path=CALLER.exe
```
判读：调用方用的是序号还是名字。序号导入 + Base=0 的组合最容易算错。

```
kitty_ce op=OPEN|<pid> → MODENUM → "R|0xIAT|qword"
```
判读：用 IAT 真地址反查落在哪个导出函数体内，作为序号映射的最终校验。

退出：给出「Base 值 + 序号→名字」对照，并抽样一条 IAT 真值验证。"""),

("TLS 目录的 Index 值是 0xFFFFFFFF。",
"""越界的 TLS 索引 = 静态 TLS 未分配，或壳把索引改成了哨兵值。

```
kitty_patch action=info path=SAMPLE.exe     → TLS 目录 RVA
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xTLS_RVA|24"
```
判读：IMAGE_TLS_DIRECTORY64 首字段 StartAddressOfRawData、第二 AddressOfIndex、
第三 AddressOfCallBacks、最后 SizeOfZeroFill + Characteristics。
Index 字段实际在 AddressOfIndex 指向的 DWORD 里。

```
kitty_ce op="R|0xINDEX_ADDR|dword"
```
判读：等于 0xFFFFFFFF → 该模块的 TLS 槽尚未分配（正常程序在 DllMain 前分配）；
分配后应是一个小整数（<64）。

退出：给出「未分配 / 哨兵 / 正常整数」三态，并说明它对多线程初始化的影响。"""),

("导入的 DLL 名是一个不存在的名字：KERNEL33.dll。",
"""名字被改过，用于规避基于导入 DLL 名的静态检测。

```
kitty_sym action=imports path=SAMPLE.exe
kitty_patch action=find path=SAMPLE.exe str=KERNEL33 limit=2
```
判读：字符串命中且导入项结构完整 → 加载器会因找不到 DLL 而失败，
所以它必然在运行期被改回。

```
kitty_ce op="S_SNAP|bytes:16|0xBASE+0xIDATA_RVA|0xBASE+0xIDATA_RVA+0x200"
```
跑起来后 S_CHANGED
判读：idata 区出现变化 = 名字被就地改写回真名，变化页内就是真 DLL 名。

```
kitty_ce op="MEMDUMP_HEX|0xCHANGED|128"
```
退出：拿到真 DLL 名并给出「静态假名 → 运行期真名」映射。"""),

("资源里有 RT_DIALOG 但程序没有任何界面。",
"""对话框资源常被当成「配置容器」用 —— 里面存的是自定义二进制而不是 DIALOGTEMPLATE。

```
kitty_patch action=info path=SAMPLE.exe
kitty_dump addr=0xRSRC_VA size=0xRSRC_SIZE path=logs\\rsrc.bin sections=true
```
判读：打开 rsrc 单节，按资源目录定位 RT_DIALOG(5) 项，读块首 4 字节。

```
kitty_patch action=find path=SAMPLE.exe pattern="01 00 FF FF" from=<块偏移> limit=2
```
判读：真 DIALOGTEMPLATE 头是 dlgVer=1 + signature=0xFFFF。不命中 → 不是对话框，
是被借用了类型编号的数据块。

```
kitty_patch action=find path=SAMPLE.exe pattern="4D 5A" from=<块偏移> limit=2
```
退出：给出块的真实格式；是 PE 就切出来单独立项，是配置就按字段表解析。"""),

("节名是 .data 但熵 7.6，且被标成可执行。",
"""数据节高熵 + 可执行 = 藏代码。正常 .data 熵在 3-5。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：Characteristics 同时含 MEM_EXECUTE(0x20000000) 与 MEM_WRITE(0x80000000)，
且 .data 的熵由 kitty_die 报 >7。

```
kitty_die action=detect target=SAMPLE.exe
kitty_dump addr=0xDATA_VA size=0xDATA_SIZE path=logs\\data.bin
```
判读：按 x64 序言（48 89/55 8B/40 53）在 data.bin 里扫，命中即含代码。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<命中偏移的 RVA>
```
退出：给出「纯数据 / 含代码段」判定 + 命中偏移；含代码则把它当第二个代码区反汇编。"""),

("样本的 SizeOfStackReserve 是 0x40000000（1GB）。",
"""巨大栈保留说明它要跑递归或大缓冲，也是「反调试占内存」的手法之一。

```
kitty_patch action=info path=SAMPLE.exe     → OptionalHeader.SizeOfStackReserve
kitty_sym action=imports path=SAMPLE.exe filter=Virtual
```
判据：1GB reserve + 只有少量 commit（SizeOfStackCommit 正常 4-16KB）→ 只是保留地址空间，
不算异常；reserve 与 commit 都巨大 → 真实需求或刻意占位。

```
kitty_ce op=MODENUM
kitty_prot action=query addr=0xSTACK_TOP
```
判读：栈区的 RegionSize 能反推实际分配。

退出：给出「保留型 / 实占型」判定；实占型要在动态会话里预留足够内存，否则中途 OOM 会误判成崩溃。"""),

(".text 的 VirtualSize 比 RawSize 小 0x2000。",
"""VirtualSize < RawSize 意味着文件里有一段不会被映射 —— 静态可见、运行期不存在。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：该节映射长度取 max(VirtualSize, SizeOfRawData) 后再按 SectionAlignment 上取整，
所以 0x2000 的尾巴仍会被映射（多数加载器按 Raw 对齐映射），不要想当然。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xTEXT_VA+0xTEXT_VSIZE|bytes:8"
```
判读：读得到 → 尾巴被映射了，静态与动态一致；读失败 → 未映射，尾巴是纯文件数据。

```
kitty_patch action=find path=SAMPLE.exe pattern="4D 5A" from=<尾巴的 Raw 偏移> limit=2
```
退出：给出「映射 / 未映射」判定；未映射且尾巴含 MZ → 隐藏载荷，独立立项。"""),

("导入用 api-ms-win-crt-* 前缀的 DLL，本机没有这些文件。",
"""API Set 是虚拟 DLL 名，由加载器重定向到真实模块，磁盘上没有文件是正常的。

```
kitty_sym action=imports path=SAMPLE.exe filter=api-ms
```
判读：这些名字在 Schema 里被映射（如 api-ms-win-crt-runtime-l1-1-0 → ucrtbase.dll）。

```
kitty_ce op=OPEN|<pid> → MODENUM
```
判读：真实加载的是 ucrtbase.dll / vcruntime140.dll，模块表里不会有 api-ms-*。

```
kitty_sym source=mem module=ucrtbase.dll action=resolve name=<导入函数名>
```
判读：解析成功 = 该函数在真实模块里存在，导入面无问题。

退出：给出「API Set → 真实模块」映射表；解析失败才说明缺 VC 运行库，
需补齐后再做动态，别把缺依赖当成反分析。"""),

("资源里有 MANIFEST，但完全没有 VS_VERSION_INFO。",
"""这个组合在正经软件里不该出现（构建系统会一起生成），是「手工删版本资源」的痕迹。

```
kitty_patch action=find path=SAMPLE.exe str=VS_VERSION_INFO utf16=true limit=4
kitty_patch action=find path=SAMPLE.exe str=assemblyIdentity utf16=true limit=4
```
判读：只命中后者 = 版本资源被剥、清单保留。

```
kitty_die action=detect target=SAMPLE.exe
```
判读：看 CompanyName/ProductName 是否可从别处（如 .rdata 的字符串）恢复。
有残留 → 可以用残留反推原始身份；全无 → 身份只能用哈希聚类。

行为含义：
剥版本资源是为了让文件属性页空白，降低人工识别率。

退出：给出「版本资源被剥」判定 + 是否能从残留字符串恢复身份。"""),

("同一个目录下有两个样本，节表完全一样但哈希不同。",
"""同构建链、不同配置或不同载荷 —— 先用结构差分定位差异，别全量读。

```
kitty_patch action=info path=A.exe
kitty_patch action=info path=B.exe
```
判据：节数/节名/节大小/入口节全同 → 同源。差异只在某几节的 RawSize 或数据目录。

```
kitty_patch action=hash path=A.exe
kitty_patch action=hash path=B.exe
kitty_patch action=find path=A.exe pattern="<B 独有的特征字节>" limit=4
```
判读：定位到差异节后，用 kitty_dump 分别取该节，逐块比对。

```
kitty_rea action=call tool=compare_functions args={"left":<A 函数证据>,"right":<B 函数证据>}
```
退出：给出「差异集中在哪个节 + 差异性质（配置/载荷/校验）」；
不要在节表相同的前提下假设逻辑相同 —— 载荷差异往往比逻辑差异更关键。"""),

("节属性里 .rdata 可写。",
"""可写 .rdata = 程序打算在运行期改常量。判据是「谁在写」。

```
kitty_patch action=info path=SAMPLE.exe     → 该节 Characteristics 含 0x80000000
kitty_prot action=query addr=0xRDATA_VA
```
判读：运行期 Protect 若也是 RW，与磁盘一致；若被改回 R，说明写窗口只在初始化阶段。

```
kitty_ce op="S_SNAP|bytes:16|0xRDATA_VA|0xRDATA_VA+0x2000"
```
跑一段后 S_CHANGED
判读：有变化 = 常量被就地改写（常见于配置解密后就地存放）。

```
kitty_ce op="MEMDUMP_HEX|0xCHANGED|128"
```
退出：给出「改写点 + 改写后内容格式」；这是配置提取的最短路径，比读解密函数快。"""),

("样本没有 .reloc 节，但 DllCharacteristics 有 DYNAMIC_BASE。",
"""矛盾配置：声明可重定位却不给重定位表 → ASLR 生效后指针会错。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：Data Directory[5] 为 0 且 0x40 位为 1。

```
kitty_die action=detect target=SAMPLE.exe
```
判读：若节表里 .reloc 存在但 Size=0，属于「节在表空」；节被删则更彻底。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0x40|word"      → DllCharacteristics 运行期值
```
判读：运行期该位被系统清掉 = 系统已判定不可重定位，实际按固定基址加载。

退出：给出「系统实际如何处理」的结论（固定基址 or 崩溃），
并据此决定地址计算用不用 MODENUM。"""),

("导入表有 8 个 DLL，但每个只导 1-2 个函数。",
"""广而浅的导入 = 能力拼装，不是为了功能，是为了让静态扫描看到「有很多依赖」。

```
kitty_sym action=imports path=SAMPLE.exe
```
判读：统计每 DLL 的函数数。8 个 DLL × 1-2 项，且函数挑选集中在外设/凭据/网络
（SetupAPI、Crypt32、WinHttp、Advapi32）→ 能力面而非功能面。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=<某一导入函数名>
```
判读：xref 数为 1-2 说明只调一次 —— 典型「探测一次就够」的用法。

```
kitty_ce op=MODENUM
```
退出：给出「能力矩阵」而不是「功能描述」：哪几个 API 被调、各调几次、在哪个函数里。
这才是这类样本的正确交付物。"""),

("文件比所有节加起来大 0x1000，但差值是零填充。",
"""零填充尾巴多半是链接器对齐残留，不是载荷。判据是「全零且不跨页」。

```
kitty_patch action=info path=SAMPLE.exe
```
判读：算 Σ(PointerToRawData + SizeOfRawData) 的最大值 M，文件长 L，差 L-M。

```
kitty_patch action=find path=SAMPLE.exe pattern="00 00 00 00 00 00 00 00" from=M limit=1
```
判读：从 M 起到 L 全是 0 → 对齐填充，无信息。

```
kitty_patch action=hash path=SAMPLE.exe
```
判读：把「尾部零填充长度」也记进卡片 —— 同批样本若长度不同，差值就是附加数据的量。

反例判据：
填充里出现任何非零字节 → 立刻转 kitty_dump 切出，按 4D 5A / 1F 8B / 30 82 三种头判格式。

退出：给出「填充 / 载荷」判定 + 差值数值。"""),

("调试目录里有两条 CODEVIEW 记录。",
"""两条 CodeView = 两次链接或后期被工具追加，第二条通常才是真实的。

```
kitty_patch action=info path=SAMPLE.exe
kitty_patch action=find path=SAMPLE.exe str=RSDS limit=4
```
判读：每条 IMAGE_DEBUG_DIRECTORY 的 Type 若都是 2(CODEVIEW)，读其后的 RSDS 结构：
GUID(16) + Age(4) + PdbFileName。

```
kitty_patch action=find path=SAMPLE.exe str=.pdb utf16=false limit=4
kitty_patch action=find path=SAMPLE.exe str=.pdb utf16=true limit=4
```
判读：两条路径若指向不同目录（一条 Release、一条 Debug），取 Release 那条作为真实构建。

```
kitty_die action=detect target=SAMPLE.exe
```
判读：kitty_die 报的 GUID 是第一条还是最后一条 —— 与手读结果对照，确定工具取哪条。

退出：给出「第一条=残留 / 第二条=真实」的判定 + 两条各自的 GUID。"""),

("样本体积 200KB，但字符串表里有 3000 条 URL。",
"""URL 数量与体积脱钩 = 它们在运行期被算法生成，字符串表只是模板或种子。

```
kitty_patch action=find path=SAMPLE.exe str=http:// limit=16
kitty_patch action=find path=SAMPLE.exe str=.com limit=16
```
判读：命中条数远少于 3000 → 确认是生成，不是硬编码。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<命中字符串>
```
判读：xref 指向一个循环 + 字符表查表 → DGA 生成器。看循环里的取模常量（如 %26）与
种子来源（时间/域名列表）。

```
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
```
跑起来后 S_CHANGED，再 MEMDUMP_HEX 读变化区
判读：生成后的域名就落在变化区里，直接拿到真实 C2 列表。

退出：给出「DGA 判定 + 取模常量 + 种子来源」；只给三条生成结果不算完成。"""),

("导入表里的函数名是乱码（非 ASCII 字节）。",
"""乱码名字 = 名字表被加密，或它是一个「按序号导入但名字字段被污染」的畸形表。

```
kitty_sym action=imports path=SAMPLE.exe
```
判读：Hint 字段是否合理。Hint 合理 + 名字乱码 → 只有名字被加密；
Hint 与名字都乱 → 整张表被处理过。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xIDATA_RVA|256"
```
判读：内存里若名字可读 → 运行期解密，以内存为准；
内存仍乱 → 用序号导入反查：
```
kitty_sym action=exports path=<对应系统 DLL>
```
按 Hint/序号定位真实函数名。

退出：给出「内存可读 → 以内存为准」或「序号反查映射表」；
两条都不通就记录为畸形表，只保留模块名与函数数量。"""),

("节名 .text 里全是高熵数据，真正的代码在 .rsrc。",
"""代码藏在资源节 = 运行期把资源映射成可执行页。判据是资源块的属性与调用点。

```
kitty_die action=detect target=SAMPLE.exe
kitty_dump addr=0xRSRC_VA size=0xRSRC_SIZE path=logs\\rsrc.bin sections=true
```
判读：资源块首若是 x64 序言（48 89/55 8B），基本可判为代码。

```
kitty_sym action=imports path=SAMPLE.exe filter=Virtual
```
判读：VirtualAlloc + VirtualProtect(RWX) + CreateThread 组合 → 把资源读进新页并执行。

```
kitty_ce op="S_SNAP|bytes:16|0xRSRC_VA|0xRSRC_VA+0x2000"
```
跑起来后 S_CHANGED + kitty_prot action=query 看新出现的 RWX 匿名区
判读：新 RWX 区就是执行位；用 MEMDUMP_HEX 读它，内容应与资源块一致。

退出：给出「资源→执行页」链路证据（分配地址 + 权限 + 内容一致性）。"""),

("两个样本互相导入对方的函数（循环依赖 DLL）。",
"""循环导入在正常情况下无法加载，能跑说明其中一侧是延迟导入或运行期解析。

```
kitty_sym action=imports path=A.dll
kitty_sym action=imports path=B.dll
```
判读：A 导入 B 且 B 导入 A。再看 Data Directory[13]（延迟导入）：
哪一侧在延迟表里，那一侧就是运行期才解析。

```
kitty_ce op=OPEN|<pid> → MODENUM
```
判读：模块表里两者的加载顺序给出真实依赖方向；先加载的那个不是被依赖方。

```
kitty_sym source=mem module=A.dll action=imports
```
判读：内存里 A 的导入是否已解析到 B 的真实地址。

退出：给出「真实依赖方向 + 哪侧是延迟导入」；这对判断哪个是「主模块」很关键 ——
主模块通常是被延迟解析的一方。"""),

("PE 头说 32 位，但 .text 里出现 REX 前缀（0x48）指令。",
"""不可能同时成立 —— 要么头是假的，要么你在用 64 位反汇编器读 32 位代码。

```
kitty_patch action=info path=SAMPLE.exe
```
判读：Magic=0x10B(PE32) 还是 0x20B(PE32+)；Machine=0x14C 还是 0x8664。

```
kitty_ce op=MODENUM
```
判读：is64=0 而 base 是 0x00400000 这种低地址 → 32 位进程。
0x48 在 32 位里是 dec eax，不是 REX 前缀 —— 之前的判读是反汇编器位数设错。

```
kitty_ida action=status
```
判读：确认当前分析用的是 x86 还是 x86-64 处理器模块，改回 32 位重载。

退出：给出位数三方一致（头/MODENUM/反汇编器）的确认，
不对齐时所有指令解读都作废，必须重来。"""),
]

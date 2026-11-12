# -*- coding: utf-8 -*-
"""re-pe-structure 扩量 F（96-120）"""

PE_F = [
("样本的 ImageBase 落在 0x400000 但标了 ASLR。",
"""低基址 + ASLR 位 = 声明矛盾，实际行为要看系统是否接受重定位。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：ImageBase=0x00400000（exe 默认）且 DllCharacteristics 含 0x40。

```
kitty_ce op=MODENUM
```
判读：运行期 base 是否等于 0x00400000。相等 → 系统按固定基址加载（ASLR 未生效，
常见于 .reloc 缺失）；不同 → 重定位生效，必须每次取 base。

```
kitty_patch action=info path=SAMPLE.exe
```
判读：Data Directory[5] 是否为 0。为 0 + ASLR 位 → 系统会清 ASLR 位，行为同固定基址。

退出：给出「实际固定 / 实际随机」判定；这直接决定地址能不能硬编码进脚本。"""),

("导入只有 ntdll，一个 kernel32 都没有。",
"""纯 ntdll 导入 = 直接系统调用层编程，绕过 kernel32 的钩子面。

```
kitty_sym action=imports path=SAMPLE.exe
```
判读：若只有 ntdll.dll 且函数项以 Nt/Zw 开头 → 直调层。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=Nt
```
判读：调用点的前一跳是否手工构造了 syscall 号（mov eax, imm; syscall）——
是则连 ntdll 都只是掩护。

```
kitty_ce op="R|0xBASE+0xEP|bytes:8"
```
判读：入口序言异常（无 CRT 初始化）→ 极可能是壳或手写入口。

退出：给出「ntdll 直调 / 手工 syscall」判定 + 是否有 CRT；这类样本的 API 断点
全部失效，动态取证只能靠内存快照差分。"""),

("资源里有两份 manifest，语言分别是 0x409 和 0x804。",
"""双语言清单通常用于「按系统语言切换提权需求」，判据是两份的 requestedExecutionLevel。

```
kitty_patch action=find path=SAMPLE.exe str=requestedExecutionLevel utf16=true limit=8
```
判读：两份都读出来。级别 highestAvailable / requireAdministrator / asInvoker。

```
kitty_patch action=find path=SAMPLE.exe str=autoElevate utf16=true limit=4
```
判读：命中即 UI 自动提权（某些系统组件行为），伪造成分极高。

```
kitty_ce op=MODENUM
```
判读：跑起来后宿主完整性级别 —— 用 kitty_status 看，确认实际是否提权。

退出：给出「两份的级别 + 是否 autoElevate」；级别不同说明样本按语言选路径，
动态复现要在目标语言环境下做。"""),

("PE 里 .text 前面多了一个无名的节。",
"""无名节（名字全 0 或不可打印）在正规链接器输出里不存在，是加壳/手工构造的标志。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：节名不是以 . 开头的可打印串，或前 8 字节全 0。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xUNNAMED_VA|64"
```
判读：内容形态：全零 → 占位（留给运行期写入）；高熵 → 加密数据；
合法序言 → 真代码（只是没名字）。

```
kitty_ce op="S_SNAP|bytes:16|0xBASE+0xUNNAMED_VA|0xBASE+0xUNNAMED_VA+0x1000"
```
跑起来后 S_CHANGED
判读：有变化 = 运行期被填充，该节是壳的解压目标区。

退出：给出「占位 / 加密 / 代码 / 解压目标」四选一，并说明它对 OEP 定位的意义
（解压目标区的末尾通常就是 OEP）。"""),

("导入表里的 DLL 名是相对路径（.\\plugin\\core.dll）。",
"""相对路径导入是非法的（加载器按 DLL 搜索顺序解析名字），说明这是打包器产物或畸形表。

```
kitty_sym action=imports path=SAMPLE.exe
```
判读：名字含 \\ 或 / 即命中。

```
kitty_ce op=MODENUM
```
判读：真实加载的模块名（模块表里只有文件名，没有路径）——
把它与导入名对照，得出「实际加载了谁」。

```
kitty_patch action=find path=SAMPLE.exe str=plugin limit=8
```
判读：路径串附近通常有 LoadLibrary 调用点，说明真正的加载逻辑在代码里，
导入表里那条是残留。

退出：给出「实际模块 vs 表内名字」映射；这类样本的导入面必须以模块表为准。"""),

("样本的 TimeDateStamp 是 0。",
"""时间戳为 0 = 被工具清零（避免时间线溯源），或链接器被要求可重现构建。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：COFF 头 TimeDateStamp == 0。

```
kitty_patch action=find path=SAMPLE.exe str=Rich limit=1
```
判读：有 Rich 头 → MSVC 产物，可从中反推链接器版本序列（Rich 头里含校验与版本）；
无 Rich 头 → 可能是 mingw/自定义链接器。

```
kitty_patch action=find path=SAMPLE.exe str=Go build ID limit=2
kitty_patch action=find path=SAMPLE.exe str=rustc limit=2
```
判读：命中即语言确定，时间戳清零是构建选项而非对抗。

交叉：
```
kitty_die action=detect target=SAMPLE.exe
```
判读：kitty_die 报的编译/壳指纹与手读的 Rich/语言标记应一致；
不一致说明头部字段被改过。

退出：给出「清零原因（可重现构建 / 对抗溯源）」+ 能从其它指纹反推的构建信息。"""),

("导入表里有 CreateToolhelp32Snapshot 和 Thread32First。",
"""线程枚举 = 遍历目标进程线程，常用于注入前找可挂起线程或反调试。

```
kitty_sym action=imports path=SAMPLE.exe filter=Thread32
kitty_sym action=imports path=SAMPLE.exe filter=Process32
```
判读：只有 Thread32 系列 → 只关心线程；两者都有 → 完整进程/线程遍历器。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=Thread32First
```
判读：循环体里对每个线程做什么：OpenThread + SuspendThread → 注入准备；
仅记录 → 监控。

退出：给出「遍历目的（注入/监控/反调试）」+ 是否伴随 Suspend/Resume 调用。"""),

("导入表只有两个函数：GetProcAddress 和 ExitProcess。",
"""这是「最小 loader」的骨架：靠 GetProcAddress 在运行期拿一切，ExitProcess 收尾。

```
kitty_sym action=imports path=SAMPLE.exe
```
判读：只有两项。没有 LoadLibrary → 说明它从已加载模块里取函数
（kernel32/ntdll 一定在进程里）。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=GetProcAddress
```
判读：GetProcAddress 的第一个参数（hModule）来源 —— 常见是
GetModuleHandle 的返回值，或 PEB 遍历拿到的基址。

```
kitty_patch action=find path=SAMPLE.exe str=LoadLibrary limit=4
```
判读：搜不到 → 纯 PEB 遍历；搜得到 → 字符串用于运行期自解析。

退出：给出「API 获取链」（PEB → 模块基址 → 导出表 → 函数地址）；
这条链是壳与 shellcode 的通用骨架，拿到它就能读懂后续一切。"""),

("节的 Characteristics 里没有 CODE 也没有 DATA 标志。",
"""属性为 0 的节是「纯声明」，加载器按默认（不可读不可执行）处理，实际不可用。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：Characteristics == 0 或只含对齐位。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xSEC_VA|bytes:8"
```
判读：读失败 → 未映射，该节纯占位；读成功 → 加载器给了默认权限。

```
kitty_patch action=find path=SAMPLE.exe pattern="<该节应含的数据>" from=<Raw 偏移> limit=2
```
判读：磁盘上有数据但内存不可读 → 数据只在磁盘，静态可见动态不可见。

退出：给出「纯占位 / 磁盘可见」判定；这类节常被用来藏「只给静态工具看」的诱饵数据。"""),

("两个节的 Raw 数据互相覆盖（第二个的 Raw 起点在第一个之内）。",
"""Raw 重叠是文件级畸形，加载器按顺序读，后者覆盖前者的文件内容但不改映射。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：节 B.PointerToRawData 落在 [A.Raw, A.Raw+A.RawSize) 内。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xA_VA|bytes:8"
kitty_ce op="R|0xBASE+0xB_VA|bytes:8"
```
判读：两处内存内容相同 → 它们从同一段文件数据映射（重叠导致）；
不同 → 加载器按各自 Raw 读，重叠只是文件布局问题。

退出：给出「同源 / 不同源」判定；同源时静态分析只需看一份，另一份是副本。"""),

("样本的富头部（Rich header）缺失但导入风格明显是 MSVC。",
"""Rich 头被剥 = 刻意抹工具链指纹，这是「对抗归因」的成熟做法。

```
kitty_patch action=find path=SAMPLE.exe str=Rich limit=2
```
判读：搜不到 Rich → 被剥。MSVC 特征可从别处确认：

```
kitty_sym action=imports path=SAMPLE.exe filter=api-ms-win-crt
kitty_patch action=find path=SAMPLE.exe str=msvcrt limit=4
```
判读：api-ms-win-crt-* 或 vcruntime140.dll → VS2015+；
msvcr120/msvcp120 → VS2013。

```
kitty_patch action=find path=SAMPLE.exe str=__security_cookie limit=2
```
判读：GS 检查符号残留 → MSVC 编译。

退出：给出「工具链推定 + Rich 被剥的事实」；被剥本身是加分证据（刻意规避），
写进卡片时与工具链结论并列。"""),

("导入表里有 RegQueryInfoKey 但没有 RegEnumValue。",
"""只查不枚举 = 判断键是否存在/有几项，不读内容 —— 典型环境探测。

```
kitty_sym action=imports path=SAMPLE.exe filter=Reg
```
判读：Query 系列齐全但 Enum 缺失 → 探测型。

```
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=16
```
判读：探测的键名通常明文内联。命中列表就是「它在找什么」的答案。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=RegQueryInfoKey
```
判读：返回值的判断分支 —— 存在则走 A，不存在则走 B。这两条分支就是行为分叉点。

退出：给出「探测的键 + 两条分支各自的行为」；探测型样本的价值几乎全在这两条分支上。"""),

("PE32+ 的 ImageBase 是 0x140000000 但 SizeOfImage 只有 0x8000。",
"""基址高、镜像小 = 正常（现代 exe 默认 ImageBase），判据不是这两个字段，而是节是否越界。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：Σ 节的 (VirtualAddress + VirtualSize) 是否 ≤ SizeOfImage。超出 → 有节越界。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0x8000|bytes:8"
```
判读：能读 → 加载器按更大的实际大小映射（SizeOfImage 声明偏小）；
读失败 → 声明正确，越界节未映射。

```
kitty_prot action=query addr=0xBASE+0x8000
```
判读：RegionSize 给出真实映射长度，这是最权威的值。

退出：给出「真实映射长度（query）vs 声明（SizeOfImage）」；
不一致时以 query 为准，所有窗口按它建。"""),

("导入表里有 VirtualProtectEx 但没有 WriteProcessMemory。",
"""跨进程改保护却不在跨进程写 = 组合不完整，要么真的缺项，要么写走的是别的机制。

```
kitty_sym action=imports path=SAMPLE.exe filter=Process
```
判读：有无 OpenProcess。有 + 无 WriteProcessMemory → 它可能用
NtWriteVirtualMemory（ntdll）或直接改 PTE。

```
kitty_sym action=imports path=SAMPLE.exe filter=Nt
```
判读：命中 NtWriteVirtualMemory/NtProtectVirtualMemory → 真正路径在 ntdll 层，
kernel32 那条是备选或残留。

```
kitty_ce op=MODENUM
kitty_prot action=query addr=<可疑目标区>
```
退出：给出「真实写路径」；结论不能停在「缺 API」——缺项往往意味着换层实现。"""),

("资源版本信息里的 FileVersion 是 1.0.0.0 但 ProductVersion 是 10.0.19041.1。",
"""版本号矛盾 = 手工改过版本资源，通常是把产品版本伪造成系统版本。

```
kitty_patch action=find path=SAMPLE.exe str=ProductVersion utf16=true limit=4
kitty_patch action=find path=SAMPLE.exe str=FileVersion utf16=true limit=4
```
判读：两栏的字符串块都读出来，确认矛盾。

```
kitty_die action=detect target=SAMPLE.exe
```
判读：签名是否存在。有签名且签名者不是微软 → 矛盾更严重（伪造身份）；
无签名 → 只是改版本资源。

```
kitty_patch action=hash path=SAMPLE.exe
```
退出：给出「版本资源矛盾」+「签名状态」两条证据；
单独一条不足以定性，两条同时成立才是「刻意伪造身份」。"""),

("导入表里有 WriteConsole，但样本是 GUI 子系统。",
"""GUI 子系统 + 控制台 API = 手段：它可能在附加到父进程控制台输出调试信息。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：Subsystem = 2(WINDOWS_GUI) 且导入 WriteConsoleA/W。

```
kitty_sym action=imports path=SAMPLE.exe filter=Console
```
判读：AttachConsole + WriteConsole + FreeConsole 三连 → 标准「输出到调用者控制台」写法。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=AttachConsole
```
判读：AttachConsole 的参数是 0xFFFFFFFF(ATTACH_PARENT_PROCESS) → 挂父进程控制台。

退出：给出「调试输出通道」判定；这是拿明文日志的最快路径 ——
用命令行启动样本就能直接看到它输出的内容，不用下任何断点。"""),

(".text 节的 RawSize 是 0x1000 的整数倍，但别处都不是。",
"""只有代码节按页对齐 = 有人单独重写过该节的 Raw 字段，其余节保持链接器默认。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：各节 RawSize % 0x1000 的值，只有 .text 为 0。

```
kitty_patch action=find path=SAMPLE.exe pattern="<.text 应含首字节>" from=<.text Raw 偏移> limit=2
```
判读：命中 → Raw 偏移正确；不命中 → Raw 偏移被改过，要按字节模式反推真实偏移。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xTEXT_VA|bytes:16"
```
判读：内存里的真实代码首字节，与磁盘各候选偏移比对，锁定真实 Raw。

退出：给出「真实 Raw 偏移」；改过节表的样本一律以内存镜像为准做静态分析。"""),

("导入表里有 SetThreadContext。",
"""改线程上下文 = 注入或反调试的核心原语（改 RIP 就能改执行流）。

```
kitty_sym action=imports path=SAMPLE.exe filter=Context
```
判读：GetThreadContext + SetThreadContext 同时出现 → 完整读写上下文能力；
只有 Set → 可能有别处拿上下文（如 CreateProcess 的线程句柄）。

```
kitty_sym action=imports path=SAMPLE.exe filter=Thread
```
判读：配合 SuspendThread/ResumeThread/OpenThread → 进程镂空（hollowing）的标准四件套。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=SetThreadContext
```
判读：CONTEXT 结构里被改的字段（Rip 还是 Rsp）。

退出：给出「改上下文的目的（改执行流 / 恢复挂起）」+ 配套的挂起调用；
这是判 hollowing 的决定性证据。"""),

("同一个 RVA 在导出表与导入表里都出现。",
"""导出与导入指向同一 RVA = 自导入，或导出表被伪造指向代码内部。

```
kitty_sym action=exports path=MODULE.dll
kitty_sym action=imports path=MODULE.dll
```
判读：存在同名项且 RVA 相同。

```
kitty_ghidra action=analyze target=MODULE.dll
kitty_ghidra action=decompile out=logs\\ghidra-mod-<ts> name=<该名>
```
判读：函数体是否真的实现了该功能。实现 → 自导入（合法但少见）；
只有跳转/返回常量 → 导出表伪造（用于欺骗扫描器「这个 DLL 提供了 X」）。

退出：给出「真实现 / 伪造导出」判定；伪造导出是「能力伪装」的常见手法，
按伪造处理时要把导出名与真实函数地址一起记录。"""),

("PE 头的 Checksum 与按算法算出的值不同（不是 0）。",
"""非零但不匹配 = 文件被改过且没重算校验和，这是「手工改包」的直接证据。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：读到的 CheckSum 与自行计算值不同。

```
kitty_patch action=hash path=SAMPLE.exe
```
判读：记录当前哈希，作为改动后的基线。

```
kitty_patch action=patch path=SAMPLE.exe at=0x... expect="..." bytes="..." confirm=true
```
判读：kitty_patch 默认 fix_checksum=true，做完后校验和会自动正确 ——
所以「校验和不匹配」这个状态一旦被你修一次就消失，动手前先把原值记下。

交叉：
```
kitty_die action=detect target=SAMPLE.exe
```
判读：kitty_die 是否也报校验异常；两侧一致才说明是同一处改动。

退出：给出「不匹配的差值 + 是否已在别处被重算」；
差值本身没意义，有意义的是「有人改过文件但没跑完整流程」这个事实。"""),

("样本加载了 3 个同名 DLL，路径不同。",
"""同名不同路径 = DLL 侧加载或私有目录加载，判据是模块表里的完整路径。

```
kitty_ce op=OPEN|<pid> → MODENUM
```
判读：模块表只给名字，路径要用 kitty_ce op="R" 读 LDR 数据或宿主侧只读查询补全。

```
kitty_sym source=mem module=<同名> action=exports filter=.
```
判读：三次解析出的导出集合是否相同。不同 → 确实是三个不同文件。

```
kitty_ghidra action=analyze target=<其中一个文件>
```
判读：哪个实现了真实功能，哪两个是替身（替身通常只有转发或空实现）。

退出：给出「三份的路径 + 各自导出面 + 谁被真正调用」；
加载顺序与搜索路径是这类样本的核心机制，必须写清。"""),

("导入表里有 URLDownloadToFile。",
"""直接下载落盘，样本自身不含后续载荷 —— 判据是下载 URL 与落盘路径。

```
kitty_sym action=imports path=SAMPLE.exe filter=URLDownload
kitty_patch action=find path=SAMPLE.exe str=http limit=16
```
判读：URL 通常明文内联（或简单异或）。

```
kitty_patch action=find path=SAMPLE.exe str=%TEMP% limit=8
kitty_patch action=find path=SAMPLE.exe str=.exe utf16=true limit=8
```
判读：落盘路径模板与扩展名，给出「下载到哪里、下什么类型」。

```
kitty_net action=capture port=8080
```
判读：抓一次真实请求，拿到完整 URL 与响应头（含 User-Agent，也是指纹）。

退出：给出「下载 URL + 落盘路径 + 后续执行方式」三件套；
第二步的「后续执行」要靠 ShellExecute/CreateProcess 的导入面确认。"""),

("样本的 .data 节初始化数据全是 0xFF。",
"""0xFF 填充是「已分配未初始化」的常见标记，判据是运行期是否被写入真实值。

```
kitty_patch action=info path=SAMPLE.exe
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xDATA_VA|64"
```
判读：内存里仍是 FF → 真的没初始化；变成其它值 → 运行期写入。

```
kitty_ce op="S_SNAP|bytes:16|0xBASE+0xDATA_VA|0xBASE+0xDATA_VA+0x1000"
```
跑起来后 S_CHANGED
判读：变化位置就是「被写入的变量」，这是免扫的变量定位法
（比 S_NEW 值扫描更适合「不知道初值」的场合）。

退出：给出「写入的变量偏移列表」；这一步常直接给出配置结构体的字段布局。"""),

("PE 里没有 .rsrc 节，但 Data Directory[2] 指向 .data。",
"""资源目录搬进数据节 = 资源被当作普通数据存放，加载器仍能按目录解析。

```
kitty_patch action=info path=SAMPLE.exe
kitty_sym action=imports path=SAMPLE.exe
```
判读：确认无 .rsrc 且目录 RVA 落在 .data 内。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xRSRC_RVA|64"
```
判读：按 IMAGE_RESOURCE_DIRECTORY（16 字节头 + 8 字节条目）解析，
能读出 Type 字段 → 目录有效，只是位置在 .data。

```
kitty_dump addr=0xBASE+0xRSRC_RVA size=0xRES_SIZE path=logs\\res.bin sections=true
```
退出：给出「资源目录有效 + 位置异常」结论；提取流程不变，只是窗口地址要按目录 RVA 算，
不能按节名找。"""),
]

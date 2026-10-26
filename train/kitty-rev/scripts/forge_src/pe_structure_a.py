# -*- coding: utf-8 -*-
"""re-pe-structure 源：PE 结构识别 → 工具映射（part A, 1-15）
每条 = (user, assistant)。assistant 目标 250-450 字，≥2 工具名，≥1 结构化特征词。
"""

PE_A = [
(
"样本 .text 熵 7.8，但没有 .pdata，也没有 UPX 节名。第一刀切哪里？",
"""按「代码段被就地加密」处理，别当普通高熵代码。

triage：
kitty_die action=detect target=SAMPLE.exe
判读：.text 熵 >7.5 且 Exception dir 无 .pdata —— 编译器本该在这个 PE32+ 里生成 unwind 表，
表被抹掉说明磁盘上的 .text 不是最终形态。两条同时成立才判「就地加密」，只高熵可能是静态链接的 LTO。

static 取证：
kitty_sym action=imports path=SAMPLE.exe filter=Virtual
判读：出现 VirtualProtect 或 VirtualAlloc 组合即坐实自解密；只有 VirtualAlloc 可能是 JIT。

dynamic 圈解密窗口：
kitty_ce op=MODENUM                              → 取 name|base|is64|size
kitty_ce op="S_SNAP|bytes:16|0xTEXT_BASE|0xTEXT_BASE+0x2000"
跑起来后交替 S_CHANGED / S_UNCHANGED，第一个出现变化的页就是解密落点。

收敛判据：首 16 字节由基线变为新值，且新值首字节落在 48/4C/55/40/41（x64 函数序言），
这时才 dump：
kitty_dump module=SAMPLE.exe path=logs\\dec.bin unmap=true fix_iat=true
不解密就 dump 只会拿到仍加密的镜像，unmap 后的 IAT 也是坏的。""",
),
(
"IAT 只有 12 项，但 .rdata 里能看到 http:// 明文。这两条怎么一起读？",
"""读法是「导入被裁剪 + 字符串没洗」，典型的手工解析外壳。

先确认导入表的真实规模：
kitty_sym action=imports path=SAMPLE.exe
判读：条目数 ≤15 且缺 GetProcAddress / LoadLibrary 之外的一切 —— 12 项里通常只有
kernel32 的三个装载函数 + 若干 CRT 桩，业务 API 一个没有，说明后续调用全靠运行期拼名字。

再确认字符串面：
kitty_patch action=find path=SAMPLE.exe str=http limit=32
判读：字符串命中但对应调用点不在导入表里，只有两种解释 —— 动态解析，或者字符串是诱饵。

量化：
kitty_sym action=exports path=SAMPLE.exe filter=Rtl
判读：本模块无导出、无转发，排除「它只是别人的代理层」。

下一步不是找字符串，而是找解析器的消费点：
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=GetProcAddress
从 GetProcAddress 的返回值 xref 往回收，能拿到一整张「运行期 API 表」，那张表才是真导入表。
拿它和磁盘导入表做差集，差出来的就是这个样本真正想藏的能力面。""",
),
(
"节表里 .text 和 .data 的 RVA 重叠了，这算畸形还是故意？",
"""先当畸形验证，再当构造验证 —— 顺序不能反。

测畸形的界：
kitty_patch action=info path=SAMPLE.exe
判读：看 SizeOfImage 是否等于「最后一个节 VA+VirtualSize 按 SectionAlignment 上取整」。
重叠但 SizeOfImage 正常 → 加载器能映射，畸形只影响静态分析工具；SizeOfImage 也算错 → 文件本身被改动过。

交叉验：
kitty_sym action=imports path=SAMPLE.exe
判读：导入表 RVA 若落进重叠区，说明 idata 是运行期重建的，静态导入不可信。

动态确认哪个节真的被用：
kitty_ce op=MODENUM                        → 拿 base/size
kitty_ce op="MEMDUMP_HEX|0xTEXT_BASE|256"
kitty_ce op="MEMDUMP_HEX|0xDATA_BASE|256"
判读：两处 dump 出来的前 256 字节若高度相似，是同一份内容被两个节描述（日志/回滚副本），
不是重叠错误；若一处是可执行序言、一处是零页，那就是节表造假，映射时后写的胜出。

结论落地：这种样本不要信静态节边界，一律用 MODENUM 报的真实模块大小切窗口，
再按 MEMDUMP_HEX 的实读内容修正每个节的真实起止。""",
),
(
"TLS 目录存在，回调地址在入口点之前。这个先后顺序有什么用？",
"""用处在时序：TLS 回调在 OEP 之前执行，任何「入口处才生效」的观测都看不到它。

定位回调：
kitty_die action=detect target=SAMPLE.exe          → 确认 TLS 目录 RVA
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=TlsCallback
判读：回调函数体里出现 IsDebuggerPresent / QueryPerformanceCounter / NtQueryInformationProcess
任一，就是反调试前置；出现一大段异或循环 + 写 .text，就是解密前置。

动态抓它：
kitty_sym source=mem module=SAMPLE.exe action=resolve name=TlsCallback_0
kitty_ce op="DBG_BP" 不可用时的等价路径：
kitty_x64dbg action=seed addr=<TLS_CALLBACK_VA> seedCmd=savedata logs\\tls.bin, SAMPLE.exe, 64
判读：断在回调里第一件事就是读 .text 首字节；若此刻已是明文，证明解密在 TLS 阶段完成，
那么普通「入口下断」永远看不到密文，也就看不到解密密钥。

退出条件：回调体读完仍无写 .text 的路径 → 说明 TLS 只做反调试，解密另有线程，转
kitty_ce op=PING 后 R 读 EPROCESS 线程表的思路继续。""",
),
(
".rsrc 里三个 RT_RCDATA，每个约 400KB，熵 7.9。这是载荷还是皮肤资源？",
"""熵 7.9 + RCDATA + 体量一致 → 先按压缩/加密载荷处理，皮肤资源不会三个一样大。

静态确认可提取性：
kitty_patch action=info path=SAMPLE.exe          → 记 .rsrc 的 VA / Raw / size
kitty_dump addr=0xRSRC_VA size=0xRSRC_SIZE path=logs\\rsrc.bin sections=true
判读：sections=true 会额外落 .rsrc 单节文件；三个 400KB 块在偏移上应等距相邻，
等距说明是同一打包器按块切出来的，不是三种不同素材。

验是不是压缩：
kitty_ce 不适用（磁盘文件），改用 kitty_patch action=find 在块首找 4B 5A / 1F 8B / 28 B5 2F FD，
命中即是 LZ4/Zlib/Zstd 容器头，可直接用外部解压；全不命中说明是自定义异或或纯密文。

真正的判据在运行期：
kitty_inject 前先用 kitty_ce op=MODENUM 拿窗口，再
kitty_ce op="S_SNAP|bytes:16|0xRSRC_BASE|0xRSRC_BASE+0x1000"
跑起来后 S_CHANGED —— 资源段在内存里被改写，说明它被当数据源解密到了别处，
这时用 kitty_ce op="S_GET|..." 取变化页地址，再 MEMDUMP_HEX 读出来就是明文载荷头。""",
),
(
"导出表 312 个，286 个是 forwarder。这种 DLL 值得逆吗？",
"""值得，但目标不是它本身，是它代理的那条链。

先量化转发结构：
kitty_sym action=exports path=PROXY.dll filter=.
判读：forwarder 的格式是 DLL.Func 字符串，把 286 条按目标 DLL 归并，
如果 90% 指向 ntdll/api-ms-win-*，这个 DLL 就是 API set 的本地替身，逻辑接近零。

再看剩下 26 个真导出：
kitty_sym action=exports path=PROXY.dll
筛出无 forwarder 的那批名字，逐个
kitty_ida action=analyze target=PROXY.dll
kitty_ida action=functions out=logs\\ida-proxy-<ts> filter=<真导出名>
判读：真导出函数里若只有 mov rax,[rip+x]; jmp rax 形态，是跳板；出现参数校验、
字符串拼接、注册表路径，才是业务。

动态确认加载顺序：
kitty_ce op=MODENUM 看它被谁先加载（在目标进程模块表里的位置靠前 = 早注入），
再 kitty_ce op="R|0xEXPORT_VA|qword" 读跳板目标，和静态判断对齐。

退出条件：286 条全是 forwarder 且无 .text 实体 → 只记录代理关系，不再逆，直接转去逆被代理模块。""",
),
(
"文件末尾有一段不属于任何节的数据，长度 0x2A000。怎么定性？",
"""定性顺序：先算 overlay，再判它是签名、安装器附件还是隐藏载荷。

算边界：
kitty_patch action=info path=SAMPLE.exe
判读：overlay 起点 = 所有节里 (PointerToRawData + SizeOfRawData) 的最大值。
0x2A000 的尾巴若正好从该值开始，就是真 overlay；若中间还有缝，说明节表被裁过。

看头 16 字节：
kitty_patch action=find path=SAMPLE.exe pattern="4D 5A" from=<overlay_start>
判读：命中 4D 5A → 内嵌 PE，这是 dropper 的标准形态，后续走 kitty_dump 按 offset 切出来单独分析。
不命中 PE，再看 30 82 / 06 09 2A 86 48（PKCS#7 / ASN.1）→ 证书签名块，无分析价值。

分辨率不够时：
kitty_die action=detect target=SAMPLE.exe
判读：Security 目录的 FileOffset 若等于 overlay 起点，直接判签名，收工。

确认内嵌 PE 的可执行性：
kitty_dump addr=0xOVERLAY_VA size=0x2A000 path=logs\\inner.bin
（overlay 不在映射内时用 kitty_patch action=find 按文件偏移切，再对 inner.bin 跑一次 kitty_die）
判读：inner.bin 能过 kitty_die 且有自己的节表 → 独立样本，按新样本重开一轮 triage。""",
),
(
"SizeOfImage 是 0x6C000，但按节表算出来应该是 0x8E000。差在哪？",
"""差值 0x22000 说明有节没被算进镜像大小，加载器不会映射它 —— 静态可见、运行期不存在。

先定差集：
kitty_patch action=info path=SAMPLE.exe
判读：把每个节 (VirtualAddress + max(VirtualSize, SizeOfRawData)) 按 SectionAlignment 上取整后求和，
和 SizeOfImage 比对。缺的 0x22000 会精确对上某一个节的 VirtualSize，
那个节就是「被声明但未映射」的幽灵节。

验幽灵节内容：
kitty_dump addr=0xGHOST_VA size=0x22000 path=logs\\ghost.bin   （VA 取不到时按 Raw 偏移切）
判读：全零 → 只是链接器残留，无害；有高熵数据 → 载荷藏在加载器视野外，
任何基于内存 dump 的分析都会漏掉它，必须静态单独取。

运行期反证：
kitty_ce op=MODENUM 记 size，若 size==0x6C000，与 SizeOfImage 一致，
说明内存里确实没有这段，进一步坐实幽灵节。

落判据：幽灵节有内容 + 内存不存在 → 把它当独立数据文件交给 kitty_ghidra 单独分析，
不要试图在动态会话里找它的执行痕迹。""",
),
(
"样本有 CLR 目录，但 kitty_ida 反出来全是 jmp thunk。走错门了吗？",
"""走错了，托管程序不要从 native 入口进。

先确认是托管：
kitty_patch action=info path=APP.exe
判读：Data Directory 第 14 项（CLR Runtime Header）RVA/Size 非零即托管；
native 入口只剩一个 _CorExeMain 跳板，这就是你看到的满屏 jmp thunk。

换门：
kitty_dnspy action=status
kitty_dnspy action=decompile target=APP.exe out=logs\\dnspy-app
判读：产出 .cs 目录里优先看 Program.Main 与任何名字含 License/Activate/Verify 的类；
托管层的字符串是明文的，直接 grep 验证逻辑比读 IL 快。

混淆时的补充：
kitty_die action=detect target=APP.exe 里若报 ConfuserEx / Babel / .NET Reactor 特征，
先
kitty_dnspy action=decompile target=APP.exe out=logs\\dnspy-deob  （内部会先过 de4dot 风格的处理）
判读：去混淆后再看控制流；仍花指令则退回 kitty_ida 只做 native 桩定位，逻辑判读全部留在 dnspy。

退出条件：能在 dnspy 产物里定位到校验方法的完整 if/else 分支 → 托管路线成立，不再回 native。""",
),
(
"Debug 目录里 PDB 路径带构建机用户名，这算情报还是噪音？",
"""算情报，而且是最便宜的那类 —— 它给出构建环境、语言和可能的源码树布局。

提取：
kitty_patch action=find path=SAMPLE.exe str=.pdb utf16=false
kitty_patch action=find path=SAMPLE.exe str=.pdb utf16=true
判读：两条都跑，CodeView 记录里的路径常是 UTF-8 单字节，但有些链接器写 UTF-16；
命中串形如 C:\\Users\\<name>\\source\\repos\\<proj>\\x64\\Release\\<mod>.pdb。

拆情报：
1) 用户名 → 同批次样本归并用的弱指纹；
2) 路径分隔与盘符 → 构建 OS；
3) x64\\Release → 配置，Debug 版会带更多断言字符串；
4) 工程名 → 搜同名开源项目，能直接拿到算法出处。

GUID 校验（决定能不能用公网符号）：
kitty_die action=detect target=SAMPLE.exe   → 记 PDB GUID + Age
kitty_sym action=exports path=SAMPLE.exe    对比导出名是否与工程名一致
判读：GUID 与官方发布的 PDB 不一致 → 符号服务器拿不到匹配文件，别浪费时间去下。

落库：把路径串 + GUID 写进样本卡片，后续同源样本直接按用户名聚类，不用重复 triage。""",
),
(
"导出表有名字，但调用点全是序号调用，为什么？",
"""因为调用方是按序号绑定的，导出名只是给人看的。

确认绑定方式：
kitty_sym action=imports source=file path=CALLER.exe
判读：导入项若只显示 Ordinal=0x1F 而无 Hint/Name，就是序号导入。
这类调用在静态视图里没有符号，反汇编器只能显示 sub_xxx。

把序号翻译回名字：
kitty_sym action=exports path=CALLEE.dll filter=.
判读：导出表是按序号升序排列的，第 N 个非转发导出对应序号 Base+N-1。
把 CALLER 的每个序号映射到 CALLEE 的导出名，得到一张真实调用表 —— 这是唯一可靠的翻译方式。

验证映射对不对：
kitty_ghidra action=analyze target=CALLER.exe
kitty_ghidra action=decompile out=logs\\ghidra-caller-<ts> name=<映射后的函数名>
判读：解出来的函数体若与其名字语义吻合（比如 GetVersion 里出现版本结构写入），映射正确；
不吻合说明 Base 值取错，回头核 OptionalHeader 里导出目录的 Base 字段。

退出条件：全部序号都能落到名字且抽样三个语义自洽 → 直接用名字重建 CALLER 的导入视图。""",
),
(
"异常目录 RUNTIME_FUNCTION 只有 421 条，但这个 exe 明显有几万个函数。",
"""421 条 unwind 只覆盖「需要栈展开的函数」，不是函数总数，差值本身不是异常 ——
但如果函数数远超同规模正常样本，就要怀疑 .pdata 被裁剪过。

先算基线：
kitty_die action=detect target=SAMPLE.exe
判读：.pdata Size / 12 = RUNTIME_FUNCTION 条数（x64 每条 12 字节）。若 421*12 恰好等于节大小，
说明表是完整的，只是这 421 个是有 unwind 需求的那部分（叶子函数不需要 .pdata）。

再估函数总数：
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> limit=200
判读：Ghidra 靠 call 目标 + 序言识别出的函数数。几万个函数里只有 421 个进 .pdata 属于正常比例
（多数是小于 0x40 字节的叶子函数）；若 .pdata 只覆盖了极少数「大函数」，那才是被裁。

动态侧证：
kitty_ce op=MODENUM 拿 .pdata 的运行时地址，kitty_ce op="R|0xPDATA_VA|bytes:24"
判读：读到的两条 RUNTIME_FUNCTION 的 BeginAddress 若全落在 .text 外，表被改过。

结论：条数少不等于异常，用「.pdata 字节数 /12 是否等于节大小」这一步定性最省。""",
),
(
"资源里有 RT_MANIFEST，要求 requireAdministrator。这条怎么用？",
"""它决定了样本必须以高完整性运行，也决定了你的动态会话必须同样提权，否则行为面直接少一半。

确认清单内容：
kitty_patch action=find path=SAMPLE.exe str=requireAdministrator utf16=false
判读：命中即坐实；同时看有没有 uiAccess=true 与 autoElevate，后者会绕 UAC 静默提权。

提权路径判断：
kitty_sym action=imports path=SAMPLE.exe filter=Shell
判读：出现 ShellExecuteExW + "runas" 字符串 → 样本自己能提权，启动即高完整性；
无 Shell 系列 → 依赖清单，用户双击时由系统弹 UAC。

对你的动态会话的含义：
kitty_status 先看宿主完整性；宿主不是管理员时，kitty_ce op=OPEN|<pid> 能连上但
W 写高完整性进程会被拒。此时先提权宿主再重连，别在低完整性里反复试写。

交叉价值：
requireAdministrator + 只写 HKLM 的样本，行为面基本可预测；若同时导入 SeDebugPrivilege，
把「读其他进程内存」列入必查项，用 kitty_ce op=LP 列出同用户进程做范围限定。""",
),
(
"导入表里只有 ws2_32 和 kernel32，能推出什么？",
"""能推出行为骨架：这是网络客户端，不是本地工具，且它没有服务端组件。

看导入的粒度：
kitty_sym action=imports path=SAMPLE.exe
判读：ws2_32 只导 WSAStartup/socket/connect/send/recv 四个 → 明文 TCP 客户端；
多出 WSAIoctl + gethostbyname → 有探测或 DNS 轮询；出现 select + 非阻塞 → 长连接心跳。

判定协议族：
kitty_patch action=find path=SAMPLE.exe str=HTTP/1.1
kitty_patch action=find path=SAMPLE.exe str=.php
判读：命中明文 HTTP 头 → 走 kitty_net action=capture 抓包看字段；
全不命中且 .rdata 熵偏高 → 自定义二进制协议，改走 kitty_proto。

确认监听面（排除它自己是服务端）：
kitty_sym action=imports path=SAMPLE.exe filter=bind
判读：无 bind/listen/accept → 纯客户端，攻击面在出向，抓包比逆代码快。

收敛：先用 kitty_net action=capture port=8080 起代理抓一轮，
判读：抓到的首个 send 报文头 4 字节若是小端长度 → 定长帧协议，直接照帧结构写解析器，
不用回 kitty_ida 读发送函数。""",
),
(
".idata 熵 7.6，但导入函数名在字符串里都找得到。矛盾吗？",
"""不矛盾：字符串在 .rdata，导入描述符结构在 .idata，被加密的是结构不是名字。

分清两份数据：
kitty_sym action=imports path=SAMPLE.exe
判读：能正常列出导入项 → 说明加载时描述符是有效的，加密是「磁盘态加密、运行期解密」。

验磁盘态：
kitty_patch action=find path=SAMPLE.exe pattern="4B 45 52 4E 45 4C 33 32" limit=4
判读：磁盘上搜不到 KERNEL32 的 ASCII → 名字表也被处理过；搜得到 → 只有 RVA 数组被异或。

对比运行期：
kitty_ce op=MODENUM → 取 idata 的运行时 VA（若 idata 没单独节，按导入目录 RVA + base 算）
kitty_ce op="MEMDUMP_HEX|0xIDATA_VA|512"
判读：内存里能看到标准 IMAGE_IMPORT_DESCRIPTOR 链（每 20 字节一条，Name 字段指向可读字符串）
→ 加载器已还原，直接从这个地址重建导入视图最准。

落做法：磁盘导入表不可信时，一律以内存 idata 为准，
用 kitty_ce 读描述符链 → kitty_sym source=mem 校验目标模块 → 手工拼出真实调用面。""",
),
]

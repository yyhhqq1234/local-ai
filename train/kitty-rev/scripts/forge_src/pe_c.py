# -*- coding: utf-8 -*-
"""re-pe-structure 扩量 C（31-45）：导入表瘦、资源加密、TLS 异常、IAT 越界等"""

PE_C = [
(
"导入表只有 KERNEL32 和 USER32 两个 DLL，但字符串里有 winsock 调用痕迹。怎么解释？",
"""解释只有两种：静态链接了，或者导入被运行期接管。先排除静态链接。

看导入的深度而不是数量：
kitty_sym action=imports path=SAMPLE.exe
判读：两个 DLL 但函数项很多（>60 条）= 正常程序，winsock 功能是通过
LoadLibrary/GetProcAddress 在运行期拿的，静态面看不到。
函数项也少（<20 条）= 导入被裁。

验静态链接：
kitty_patch action=find path=SAMPLE.exe str=ws2_32 limit=4
kitty_patch action=find path=SAMPLE.exe str=WS2_32.dll utf16=true limit=4
判读：命中即说明它会在运行期装载 ws2_32；全不命中说明 socket 实现在样本自己身上
（静态链接 libcurl/libuv），此时行为面等价但代码量巨大。

验代码自证：
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=socket
判读：能搜到 socket 相关函数体（含 0x02/0x01 常量）→ 静态链接成立。

退出条件：给出「运行期装载」或「静态链接」二选一，并附一条证据；
两者都排除的话，第三条解释是判定器误报，回头核字符串位置。""",
),
(
".rsrc 里有一个 RCDATA 块熵 7.9，但资源目录显示它是 ICON。这是伪装吗？",
"""是伪装。资源类型字段是给人看的，内容才是事实 —— 判据是块首的结构合法性。

先取块：
kitty_patch action=info path=SAMPLE.exe                  → .rsrc 的 RVA/Raw/size
kitty_dump addr=0xRSRC_VA size=0xRSRC_SIZE path=logs\\rsrc.bin sections=true
判读：拿到 rsrc 单节文件，按资源目录树定位该块的文件偏移。

验类型是否真：
kitty_patch action=find path=SAMPLE.exe pattern="28 00 00 00" from=<块偏移> limit=2
判读：真 ICON 的块首 4 字节是 biSize（0x28 = 40 字节 BITMAPINFOHEADER，
或 0x0C 表示 PNG 图标）。不命中 → 不是图标，类型字段是假的。

再验它是什么：
kitty_patch action=find path=SAMPLE.exe pattern="4D 5A" from=<块偏移> limit=2
判读：命中 → 内嵌 PE；命中 1F 8B / 28 B5 2F FD → 压缩容器。

交叉验证运行期：
kitty_ce op=MODENUM → .rsrc 的运行时 VA
kitty_ce op="S_SNAP|bytes:16|0xRSRC_VA|0xRSRC_VA+0x1000"
跑起来后 S_CHANGED
判读：资源在内存里被改写 → 它被当数据源解密，伪装确认。

退出条件：拿到「类型字段造假 + 真实内容格式」两条结论，才写进卡片。""",
),
(
"TLS 目录的 AddressOfCallBacks 数组有 3 项，但程序行为只像有 1 个初始化函数。",
"""3 项是常态：编译器会把 CRT 初始化、线程局部存储初始化、用户回调都排进这个数组。
真正要查的是「哪一项在做非初始化的事」。

取数组：
kitty_patch action=info path=SAMPLE.exe                 → TLS 目录 RVA
kitty_die action=detect target=SAMPLE.exe                → 拿 ImageBase 与节表
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=Tls
判读：三个函数体逐个看。正常 CRT 回调只做 TLS 索引初始化（写 _tls_index）与 SEH 注册；
可疑回调会碰 .text 写入、内存分配、或 API 解析。

按体积排优先级：
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<最短的那个回调>
判读：最短的往往是壳的解密桩（几十字节，一个循环 + 一次跳转）。

运行期确认顺序：
kitty_ce op=MODENUM → base
kitty_ce op="MEMDUMP_HEX|0xBASE+0xTLS_CALLBACKS_RVA|24"
判读：三个指针按顺序读出来，与静态的 RVA 对得上说明数组未被改写。

退出条件：能指出「第 N 项做解密 / 第 N 项只做 TLS 索引」，
并对该项给出一条运行期证据。三项都只做初始化时，结论写「TLS 组件干净」。""",
),
(
"IAT 里有一项指向的地址不在任何已加载模块范围内。这是什么？",
"""两种可能：热补丁留下的跳板，或者 IAT 被改成了自建桩。判据是那块内存的属性。

先定位归属：
kitty_ce op=OPEN|<pid>
kitty_ce op=MODENUM
判读：把 IAT 项的值与所有模块的 [base, base+size) 比对，落在外面即命中。

问加载器这块是谁的：
kitty_prot action=query addr=0xIAT_TARGET
判读：Type=MEM_PRIVATE + Protect=RWX → 自建桩（壳/注入器的标准做法）；
Type=MEM_IMAGE 但不在模块表 → 已被卸载的模块残留（悬空指针，调用会崩）；
AllocationBase 指向堆 → 被改成数据指针，说明是运行期重定向。

看桩的内容：
kitty_ce op="MEMDUMP_HEX|0xIAT_TARGET|64"
判读：首字节 48 B8 ... FF E0（mov rax,imm; jmp rax）→ 跳板；
FF 25 [rip+x] → 二次解引用；E9 rel32 → 直接跳。

对照磁盘：
kitty_sym action=imports path=SAMPLE.exe
判读：磁盘 IAT 里这一项本该是哪个函数，再看桩跳到哪 —— 两者不同即被劫持。

退出条件：给出「桩类型 + 最终目标模块/函数」，并对最终目标做一次 R 回读确认可达。""",
),
(
"样本导出 200 个函数，其中 30 个是转发到自己的转发器（循环）。",
"""自转发是导出表畸形，会让加载器解析失败或无限递归 —— 先当损坏处理，再看是不是刻意。

读转发结构：
kitty_sym action=exports path=MODULE.dll filter=.
判读：forwarder 字符串形如 "MODULE.Func"。目标 DLL 名与本模块名相同 → 自转发。

分两类：
1) 目标函数在本模块里存在 → 无害但冗余（链接器脚本写错），解析正常；
2) 目标函数在本模块里不存在 → 悬空，调用即失败。

验证第 2 类：
kitty_sym action=exports path=MODULE.dll filter=<转发目标函数名>
判读：搜不到 → 悬空转发。这类样本通常被拿来做「加载器模糊测试」的靶标。

对分析的影响：
kitty_ida action=analyze target=MODULE.dll
kitty_ida action=entries out=logs\\ida-mod-<ts> filter=<导出名>
判读：如果 IDA 把转发项当成函数体反编译，产出的就是垃圾 —— 要手工标记为 thunk。

退出条件：给出「自转发 N 条，其中悬空 M 条」的计数；
M>0 时把它记进样本卡片，作为「加载即失败」的预期依据，不要当成正常模块继续逆。""",
),
(
"节表里 FileAlignment=0x200，但某节的 PointerToRawData 是 0x201。",
"""非对齐的 Raw 指针是手工改过的痕迹。判据不是「能不能加载」，而是「谁在按什么粒度读」。

先量化偏差：
kitty_patch action=info path=SAMPLE.exe
判读：每个节都核 (PointerToRawData % FileAlignment == 0)。
单节偏 1 字节 = 有人用十六进制编辑器插了字节；多节都偏 = 节表被整体重写。

能不能加载：
kitty_die action=detect target=SAMPLE.exe
判读：加载器对 Raw 指针不严格（按页映射），所以多数情况能跑。
能跑 ≠ 文件正常 —— 静态工具按 Raw 读会整体错位 1 字节。

静态工具的正确做法：
不要用 kitty_ida 直接读该文件（它按 FileAlignment 对齐读，会全错）。
改用运行期镜像：
kitty_dump module=SAMPLE.exe unmap=true fix_iat=true path=logs\\fixed.bin
判读：unmap 会按节表重排，但源头错位仍会被带进来 —— 一致率会明显低于 85%。

修法（自有样本）：
kitty_patch action=patch path=SAMPLE.exe at=0x<节表项 Raw 字段偏移> expect="<原 4 字节>" bytes="<对齐后的 4 字节>" confirm=true
判据：expect 必须来自 kitty_patch action=info 的实际输出，不能凭算。

退出条件：改完重跑 info，所有 Raw 都对齐；或确认这是刻意构造、直接改用内存镜像路线。""",
),
(
"SizeOfOptionalHeader 是 0xE0，正常 PE32+ 应该是 0xF0。少了 16 字节。",
"""少了 16 字节 = Data Directory 少了两项，或者 OptionalHeader 被截。
这直接决定你能不能信 TLS/CLR/延迟导入这几个目录。

先算：
kitty_patch action=info path=SAMPLE.exe
判读：PE32+ 的 OptionalHeader 标准长度 0xF0（含 16 个 Data Directory × 8 字节）。
0xE0 = 少了 2 个目录项。

哪两个被裁：
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xE_LFANEW+0x18|224"
判读：按偏移数：可选头从 +0x18（PE32+）开始，Data Directory 在 +0x70 处，
共 16 项。0xE0 意味着只声明了 14 项 —— 最后两项（CLR Runtime Header、
Reserved）消失。CLR 项缺失会让 dnSpy 判定「非托管」。

对判读的直接影响：
kitty_die action=detect target=SAMPLE.exe
判读：它按声明长度读，报「无 CLR」时不要直接采信 ——
用 kitty_patch action=find 在文件中手动找 BSJB 元数据签名：
kitty_patch action=find path=SAMPLE.exe str=BSJB limit=4
命中即实际是托管程序，只是目录被裁。

退出条件：给出「声明目录数 vs 实际存在的目录」对照表，
并说明后续该用哪条路径（按声明读 or 手工补目录）。""",
),
(
"有 Security 目录（第 4 项）但内容是空的全零块。怎么定性？",
"""定性为「签名被剥离但目录未清」，这是加壳/改包流程的典型残留。

三步确认：
1) 目录声明：
kitty_patch action=info path=SAMPLE.exe
判读：Data Directory[4].RVA/Size 非零。记下 RVA 与 Size。
2) 内容：
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xSEC_RVA|256"
判读：全 00 → 空块；有 30 82 开头 → 真 PKCS#7，转去验证证书链。
3) 落点：
kitty_patch action=info path=SAMPLE.exe
判读：Security 的 RVA 通常指向 overlay（文件尾），核对它是否等于
「所有节 Raw 末端最大值」。

为什么这个组合有信息量：
它能区分三种历史：
a) 原本有签名，后来被工具剥掉（目录留、内容清空）→ 改包痕迹；
b) 从未签名，目录被人手工填了个假值（Malware 常见）→ 伪造痕迹；
c) 目录和内容都对，只是证书自签名（kitty_die 报无签名）→ 自签。

区分 a 与 b 的判据：
kitty_patch action=hash path=SAMPLE.exe
比对同批样本的校验和字段：a 类校验和通常被重算过（非 0），b 类常见 0。

退出条件：落到 a/b/c 之一，并把依据（目录值、内容首字节、校验和）写进卡片。""",
),
(
".text 被拆成 .text、.text$1、.text$mn 三个节，这正常吗？",
"""正常，这是 MSVC 的节合并语法（$ 后缀表示合并顺序）。异常的是**合并粒度被改过**。

读节表：
kitty_patch action=info path=SAMPLE.exe
判读：.text$mn → .text$mn$21 之类是编译器为 /Gy（函数级链接）生成的中间节，
链接后通常会被合并掉。留下多个 = 用了 /OPT:NOREF 或人为保留。

对分析的影响（比好奇更重要）：
kitty_ghidra action=analyze target=SAMPLE.exe
判读：Ghidra 会把每个节当成独立地址区间，跨节的 call 可能被标成外部引用。
症状：反编译里出现大量 undefined 目标。

修正：
kitty_ce op=MODENUM → base/size
kitty_dump module=SAMPLE.exe unmap=true path=logs\\merged.bin
判读：内存镜像里这些节是连续的，以此为准反汇编；跨节 call 就不会断。

判可疑的分支：
如果 $ 后缀的数字乱序（.text$3 在 .text$1 之前），说明节表被手工重排 ——
这是「把代码块挪到别处」的常见手法，与 OEP 篡改经常成对出现。

退出条件：给出「编译器产物」或「手工重排」判定，并按结论选反汇编入口（磁盘 or 内存镜像）。""",
),
(
"导入了一个 KERNEL32 里不存在的函数名（比如 CreateFileWx）。",
"""两种解释：名字被改（对抗静态特征），或它是从别的模块转发的。

先确认这个名字真不存在：
kitty_sym action=exports path=C:\\Windows\\System32\\KERNEL32.dll filter=CreateFileW
判读：只有 CreateFileW / CreateFileA / CreateFile2 这类，没有 CreateFileWx。

再看导入项的写法：
kitty_sym action=imports path=SAMPLE.exe
判读：Hint 字段是否有效（有效 Hint + 无效名字 = 名字被改过）；
Hint=0 且 Name 是乱名 = 手工构造。

运行期真相：
kitty_ce op=OPEN|<pid>
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xIAT_ENTRY|qword"
kitty_prot action=query addr=<读到的值>
判读：落在 KERNEL32 的区间内的哪个函数体内 —— 那就是它真正调用的 API。
位置不能精确定位时，用 kitty_sym source=mem module=KERNEL32.dll action=exports 逐个比区间。

为什么这么做：
名字是字符串，可被替换；IAT 里填的是运行期解析后的真地址，改不动（除非整段劫持）。

退出条件：给出「假名 → 真 API」映射，并注明是「静态特征规避」还是「转发」。
一条都对不上时，把它当私有导出（样本自带实现）处理。""",
),
(
"资源版本信息里 CompanyName 是空的，但 FileDescription 是「Windows Update Standalone Installer」。",
"""组合本身是矛盾证据：真微软组件的 CompanyName 不会为空，而 FileDescription 是最常见的仿冒字段。

先取全量版本字段：
kitty_patch action=find path=SAMPLE.exe str=VS_VERSION_INFO utf16=true limit=4
判读：命中后按 StringFileInfo 结构读全部键值对。重点看四栏：
CompanyName / ProductName / FileVersion / OriginalFilename。
判据：CompanyName 空 + FileDescription 冒充系统组件 = 借名；
OriginalFilename 与磁盘文件名不一致 = 二次改名。

再看硬字段：
kitty_die action=detect target=SAMPLE.exe
判读：看 TimeDateStamp 与签名。真微软组件两者都在；
仿冒的常见组合是「无签名 + 时间戳随机」。

行为面交叉：
kitty_sym action=imports path=SAMPLE.exe
判读：系统更新组件不会导入 ws2_32 或 CreateRemoteThread。
出现任一条 → 借名判定成立，且用途与自称完全不符。

退出条件：给出「借名」判定，附三栏具体值 + 一条导入面反证。
不写「疑似恶意」这类无判据结论。""",
),
(
"overlay 尾部又有一个 MZ，但它的 e_lfanew 指向文件外。",
"""说明它不是完整 PE，而是被截断的内嵌镜像或加密过的 PE 头。判据是 NT 头能否落在块内。

先量：
kitty_patch action=info path=SAMPLE.exe
判读：overlay 起点 = 各节 Raw 末端最大值。记下起点与文件总长 → 块长。

验头：
kitty_patch action=find path=SAMPLE.exe pattern="4D 5A" from=<overlay_start> limit=4
判读：命中偏移 O。读 O+0x3C 处的 e_lfanew：
kitty_patch action=find path=SAMPLE.exe pattern="<e_lfanew 的小端 4 字节>" from=O+0x3C limit=1
判读：若 e_lfanew > 块长 → 头指向界外，确认畸形。

三种成因与处置：
1) 被截断：块长只够 PE 头 → kitty_dump 切出来只能做签名比对，不能反汇编；
2) 加密头：头部字段是密文 → 找解密点（运行期 S_SNAP 圈变化页）拿明文头；
3) 只有 MZ 两个字节是巧合 → 换判据（找 4D 5A 90 00 03 00 00 00 的完整 DOS 头）。

kitty_dump addr=0x<O 换算的 VA> size=<块长> path=logs\\inner_raw.bin
判读：切出来先跑 kitty_patch action=info 看它自己怎么解释 e_lfanew。

退出条件：三选一并给出块长 + e_lfanew 两个数值作为证据。""",
),
(
"重定位表整段是 0x00（BlockSize 字段也是 0）。",
"""清零的重定位表 = 「我不打算被重定位」，通常来自固定基址编译或壳的重定位剥离。

验意图：
kitty_patch action=info path=SAMPLE.exe
判读：DllCharacteristics 是否含 DYNAMIC_BASE(0x40)。有该位但表清零 →
系统会强行动态化但无法修正指针，结果就是启动即崩（或依赖 /FIXED 兼容层）。
无该位 + 表清零 → 固定基址程序，一致且合法。

验是否真的不能重定位：
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xRELOC_RVA|dword"        → 读 BlockSize
判读：运行期也是 0 → 表确实空；运行期非 0 而磁盘为 0 → 运行期重建（少见，但存在）。

对地址计算的影响：
表为空 + 无 DYNAMIC_BASE → 可以硬编码 ImageBase 算绝对地址，重启不变；
表为空 + 有 DYNAMIC_BASE → 必须每次 MODENUM 取 base，且要预期指针可能已坏。

退出条件：给出「固定基址 / 动态但不可重定位（会崩）」二分，
并写明后续地址计算规则（硬编码 or 运行期取 base）。""",
),
(
"Delay Import 表里指向的 DLL 在本机根本不存在。",
"""两种可能：样本依赖一个不随系统安装的私有组件，或者这是个环境探测点。

先列全：
kitty_patch action=info path=SAMPLE.exe
判读：Data Directory[13] 的 RVA/Size。按 ImgDelayDescr（32 字节）逐条读，
字段 szName 给出 DLL 名（grAttrs 最低位=1 时按 RVA 解释）。

逐个核存在性：
kitty_sym action=imports path=SAMPLE.exe filter=<该 DLL 名>
判读：能列出导入函数名 = 至少静态结构完整；
再到系统目录核文件是否存在（不存在 → 缺依赖）。

判它是探测还是缺依赖：
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<该 DLL 名>
判读：引用点附近若有「失败分支 → 走另一条路」的结构，是环境探测；
失败即退出/崩溃，是硬依赖。

运行期观察：
kitty_ce op=MODENUM
判读：跑一段后该 DLL 是否出现。永不出现 = 该功能路径从未被触发。

退出条件：给出「缺依赖 / 环境探测」判定 + 失败分支的行为（退出码或替代路径）。
缺依赖的情况，复现前必须补齐组件，否则后面所有动态结论都不可信。""",
),
]

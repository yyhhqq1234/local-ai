# -*- coding: utf-8 -*-
"""re-decision-chain 源 A2 (11-20)"""

CHAIN_A2 = [
(
"sys 驱动文件，知道它有 DeviceIoControl 分发。顺序？",
"""[1] triage —— 只读证据优先，先不加载
kitty_die action=detect target=drv.sys
判据：是否签名（Security 目录可解析）、是否加壳（.text 熵）、DriverEntry 是否可见。
退出条件：判定「能静态读」还是「必须运行才能看」。
纪律：不把未知驱动加载到本机；先走静态 + 内存镜像两条路。

[2] static —— 先建 IOCTL 号码表
kitty_sym action=imports path=drv.sys
kitty_ghidra action=analyze target=drv.sys
kitty_ghidra action=functions out=logs\\ghidra-drv-<ts> filter=Dispatch
判据：分发函数里的 cmp/jump table 给出的常量（通常按 0x22xxxx 分组）。
退出条件：拿到全部 IOCTL 码 + 每个码对应处理函数。

[3] dynamic —— 只做「空缓冲安全探测」，不投递真实载荷
kitty_drvio action=status
kitty_drvio action=probe device=<设备名> ioctls=["0x225C90","0x225C94"] inHex=
判据：IOCTL 是否受理（STATUS_INVALID_PARAMETER 说明码对、参数不足；
STATUS_NOT_SUPPORTED 说明码不对）。
退出条件：能确认至少一个码的分发路径可达。

[4] 导出
产物：IOCTL 表（码/所需权限/参数结构推断/可达性）+ 未解项。
判据：表格里每条都有 [2] 或 [3] 的输出支撑。
不做：不构造带真实指针的输入缓冲（会变成对内核的写），取证目的到此为止。""",
),
(
"外层释放内层，内层才有实际逻辑。这个嵌套怎么拆？",
"""[1] triage —— 先定位内层载荷在文件里的位置
kitty_die action=detect target=OUTER.exe
kitty_patch action=info path=OUTER.exe
判据：overlay 起点 vs 各节 Raw 末端的最大值；差值即可能的嵌入区。
退出条件：给出候选偏移区间。

[2] static —— 静态提取内层
kitty_patch action=find path=OUTER.exe pattern="4D 5A" from=<overlay_start> limit=8
判据：命中偏移处的 PE 头是否自洽（e_lfanew 指向合法 NT 头、节表不越界）。
退出条件：拿到内层 PE 的起始偏移与长度。
提取：kitty_dump addr=0x<内层文件偏移换算的 VA> size=<长度> path=logs\\inner.exe
（若内层不在映射内，按文件偏移直接切出 logs\\inner.exe）

[3] dynamic —— 确认内层是「被写盘再执行」还是「内存直接映射」
kitty_ce op=MODENUM                                    → 外层模块表
跑完触发后 kitty_ce op=MODENUM
判据：模块表里若出现 inner.exe 或匿名可执行区，看是文件映射还是内存映射；
用 kitty_prot action=query addr=<可疑区> 看 AllocationBase 是否有对应文件。
退出条件：确定内层的执行方式（落地执行 / 反射加载）。

[4] 导出
产物：内层文件 + 提取偏移 + 执行方式结论 + 内层自己的 triage 摘要。
判据：内层能独立跑 kitty_die 且有自己的入口。
纪律：内层按新样本重开一轮完整链，不要继承外层的结论。""",
),
(
"要判断样本是否恶意，但不做完整逆向。最短路径是什么？",
"""[1] triage —— 用指纹先杀掉一半可能
kitty_die action=detect target=SAMPLE.exe
判据：已知家族特征（节名/PDB 路径/导入组合）命中 → 直接归族，不必深逆。
退出条件：能归族就停；不能归族进 [2]。

[2] static —— 只读「能力面」，不读实现
kitty_sym action=imports path=SAMPLE.exe
判据：能力四桶 —— 持久化（Reg*/CreateService）、注入（OpenProcess/VirtualAllocEx/WriteProcessMemory）、
外联（WinInet/WinHTTP/ws2_32）、破坏（DeleteFile/CryptEncrypt）。
退出条件：四桶里命中 ≥2 桶即高度可疑，进 [3] 取证；只命中 1 桶继续看字符串。

[3] dynamic —— 用最小观测窗抓一次行为，不做长跑
kitty_ce op=MODENUM
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x11000"
运行 10 秒后 kitty_ce op=S_CHANGED
判据：有自修改 = 有解密/装载，恶意度上调；无变化说明逻辑在别处（网络/文件）。
退出条件：拿到一条可复现行为（外联地址 / 落地文件 / 注册表键）。

[4] 导出
产物：家族判定 or 能力矩阵 + 一条行为证据 + 置信度（高中低）+ 未解项。
判据：结论必须能落到「四桶中的哪几桶 + 哪条行为」。
不做：不给没有证据的「恶意/无害」二值结论 —— 只交能力面与证据强度。""",
),
(
"Unity 游戏目录，一堆 .assets 和 Managed 目录。先看哪边？",
"""[1] triage —— 先判是 Mono 还是 IL2CPP
kitty_engines path=<游戏目录>
判据：存在 Managed/Assembly-CSharp.dll = Mono；存在 GameAssembly.dll + global-metadata.dat = IL2CPP。
退出条件：引擎与脚本后端定型。这一步错，后面全白做。

[2] static —— 按后端选工具，不混用
Mono：kitty_dnspy action=decompile target=<Managed\\Assembly-CSharp.dll> out=logs\\dnspy-cs
判据：能直接读到 .cs 源码（含类名/字段名）→ 逻辑层完全可见。
IL2CPP：
kitty_il2cppdumper action=dump so=<GameAssembly.dll> meta=<global-metadata.dat> out=logs\\il2cpp
判据：产出 dump.cs 里有类/方法/字段偏移；空产出说明版本不匹配，换 kitty_cpp2il。
退出条件：拿到「类名 → 方法地址/字段偏移」映射。

[3] dynamic —— 字段偏移要在运行期验一次
kitty_ce op=OPEN|<pid> → MODENUM 取 GameAssembly.dll base
kitty_ce op="R|0xBASE+0x<dump.cs 里的方法 RVA>|bytes:8"
判据：读到的字节是否是合法序言（对应 dump 的签名一致）。
退出条件：抽样 3 个方法地址都对上 → dump 可信，可以按字段偏移建结构。

[4] 导出
产物：脚本后端结论 + 类/字段/方法清单 + 3 条运行期校验记录。
不做：不对 .assets 里的贴图/模型做逆向当作主线 —— 逻辑在脚本侧。""",
),
(
"UE 游戏的 .pak 打不开，说 key 不对。接下来怎么走？",
"""[1] triage —— 先确认是加密还是索引损坏
kitty_engines path=<游戏目录>
判据：Pak 目录里是否有 .sig / .pak 同名的 .ucas/.utoc（IoStore 结构）；引擎版本号。
退出条件：判定 pak 形态（传统 pak / IoStore）+ 是否 AES 加密。

[2] static —— 找 key 的落点，而不是爆破
kitty_patch action=find path=<exe> str="0x" limit=32
kitty_patch action=find path=<exe> pattern="00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00" limit=8
判据：UE 的 AES key 常以 32 字节十六进制串或 crypto.json 形式出现在 exe/config 附近。
真实落点优先级：游戏目录 crypto.json > exe 内嵌 ASCII key > 启动器参数。
退出条件：拿到 32 字节 key 或确认无 key（明文 pak）。

[3] dynamic —— 用运行期读 key，绕过静态混淆
kitty_ce op=MODENUM
kitty_ce op="S_NEW|bytes:32|<key候选>|0xBASE|0xBASE+SIZE" wait=true top=10
判据：若静态候选在内存里命中，即坐实该 key 被加载器使用。
退出条件：key 可用 → 进 kitty_fmodel 解包。

[4] 导出
kitty_fmodel action=list pak=<pak 路径> aesKey=<key>
产物：可读资产清单 + key 来源说明。
判据：清单里能看到 .uasset/.uexp 且能导出一个。
不做：不用爆破方式猜 AES-256 key（搜索空间无解，纯浪费）。""",
),
(
"Electron 应用只有一个 asar，怎么拆到能读的源码？",
"""[1] triage —— 先判打包形态
kitty_rea action=status
kitty_rea_javascript input_path=<app 目录> format=auto integrity_policy=record-and-continue
判据：是否能识别 asar 容器、模块图、IPC 通道、原生 addon。
退出条件：拿到「主进程入口 + 渲染进程入口 + IPC 名单」三项。

[2] static —— 结构化恢复，不逐文件读
kitty_rea_recover_js path=<app.asar> output_directory=logs\\js-src extraction_mode=structural rewrite_level=standard
判据：恢复出的模块里每个 chunk 有来源标注与校验；未标注来源的视为不可信。
退出条件：能定位到「业务逻辑 chunk」（非 node_modules）。

[3] static 二次 —— 业务面按关键字切
kitty_rea action=call tool=trace_feature args={"query":"<业务关键字>"}
判据：追踪链是否穿到 IPC 注册处（ipcMain.handle / ipcRenderer.invoke）。
退出条件：拿到一条「界面事件 → IPC → 主进程处理」的完整链路。

[4] 动态（需要时）—— 只在该链路上取值
kitty_ce op=OPEN|<pid> → MODENUM（Electron 主进程是 node，模块表里能看到 node.dll）
判据：值是否与静态链路的常量一致。
退出条件：静态结论被运行期证实或证伪。

[5] 导出
产物：模块图 + 业务链路 + 原生 addon 清单（若有）。
判据：链路上每跳都有 sourcemap 或运行期证据。
不做：把整个 node_modules 解出来通读 —— 收益为零。""",
),
(
"给了一个 Go 编译的二进制，符号被 strip 了。还有救吗？",
"""[1] triage —— 先判语言与剥离程度
kitty_die action=detect target=GOBIN
判据：Go 的 buildinfo（"Go build ID"）、大量 golang.org/x 路径残留、
节名 .gopclntab / .gosymtab 是否还在。
退出条件：确定是 Go 且知道 pclntab 是否保留。

[2] static —— 用 pclntab 恢复函数名，这是 Go 的命门
kitty_ghidra action=analyze target=GOBIN
kitty_ghidra action=functions out=logs\\ghidra-go-<ts> limit=120
判据：函数名是否呈现 main.xxx / runtime.xxx 形态；pclntab 保留时能恢复到接近完整。
退出条件：函数名恢复率 >50% 即可往下，不必追求 100%。

[3] static 二次 —— 字符串与类型信息
kitty_patch action=find path=GOBIN str="main." limit=16
判据：Go 的类型元数据里带结构体字段名，能据此重建结构。
退出条件：至少恢复出一个结构体的字段布局。

[4] dynamic —— 只验证，不重做
kitty_ce op=OPEN|<pid> → MODENUM
kitty_ce op="R|0xBASE+0x<恢复的函数 RVA>|bytes:8"
判据：字节是否为合法序言且与 Ghidra 反汇编首指令一致。
退出条件：抽 3 个函数全部对上。

[5] 导出
产物：函数名恢复率 + 结构体布局 + 主逻辑入口。
不做：把 runtime.* 的内部函数当业务逻辑读 —— 那些是调度器，与样本行为无关。""",
),
(
"Rust 编译产物，反汇编里全是 Result/Option 展开。怎么不被淹？",
"""[1] triage —— 先确认是 Rust 且知道符号状态
kitty_die action=detect target=RUSTBIN
判据：字符串里出现 rustc 版本、/rustc/ 路径、core::panicking 消息 → 确认 Rust。
退出条件：确认语言 + 符号是否保留（未 strip 时符号名可读）。

[2] static —— 用 panic 消息当锚点，这是 Rust 最好用的路标
kitty_patch action=find path=RUSTBIN str=panicked at limit=16
判据：panic 字符串旁边一定是调用点；从 panic 引用处反推上层业务函数。
退出条件：拿到 ≥3 个 panic 锚点及其所在函数。

[3] static 二次 —— 只读业务函数，跳过展开
kitty_ghidra action=analyze target=RUSTBIN
kitty_ghidra action=decompile out=logs\\ghidra-rust-<ts> name=<业务函数名>
判据：函数体里是否出现业务字符串比较 / 文件路径拼接（非 panic 路径）。
退出条件：定位到 main 的主循环。

[4] dynamic —— 验证到「行为」为止，不追内联
kitty_ce op=OPEN|<pid>
kitty_ce op="S_NEW|dword|<已知值>|0xBASE|0xBASE+SIZE" wait=true top=10
判据：命中是否跟随改值。
退出条件：拿到一条可复现行为。

[5] 导出
产物：panic 锚点表 + 主循环入口 + 行为证据。
不做：逐行读 Option/Result 的状态机展开 —— Rust 的 drop/panic 路径占 80% 代码量，读完也换不到信息。""",
),
(
"给了个 32 位老程序，装了 64 位工具链。怎么对齐？",
"""[1] triage —— 先确认位数与子系统
kitty_patch action=info path=LEGACY.exe
判据：NT 头 Machine（0x14C=i386 / 0x8664=x64）+ OptionalHeader Magic（0x10B=PE32 / 0x20B=PE32+）。
退出条件：位数确认。这步错，后面所有读都错但不报错。

[2] static —— 选 32 位通道，不硬套 64 位
kitty_ida action=status
判据：IDA 是否有 32 位处理器模块（metapc 支持 32 位，可直接用）；
Ghidra 需在导入时指定 Language 为 x86:LE:32:default。
退出条件：静态视图里寄存器是 eax/esp 而非 rax/rsp。

[3] dynamic —— 调试器必须匹配位数
kitty_variants action=list
判据：选 DBG32 变体；64 位调试器附加 32 位进程会直接失败或挂起。
kitty_variants action=switch variant=<ws-dbg-dbg32>
退出条件：C 通道 selftest 通过。

[4] 内存侧 —— 指针宽度与窗口密度
kitty_ce op=MODENUM                                   → is64=0
kitty_ce op="P_BACK|0xTARGET|0xSTART|0xSTOP"
判据：32 位地址 4 字节，命中密度是 64 位的两倍，窗口要比 x64 窄一半以上。
退出条件：某跳命中 ≤20 且 R 回验通过。

[5] 导出
产物：位数确认证据 + 32 位工具配置 + 偏移表（不混入 64 位地址）。
不做：用 64 位调试器「试试看」—— 只会浪费时间，且可能触发目标自检。""",
),
]

# -*- coding: utf-8 -*-
"""re-decision-chain 扩量 D（31-60）。每条必须可读出 triage → static → dynamic + 每步判据。"""

CHAIN_D = [
("已经拿到内存 dump，但 IAT 是坏的。从哪一步接？",
"""[1] triage —— 先验 dump 本身是否可用
kitty_die action=detect target=dump.bin
判据：节表自洽性 + 熵分布。节表错位则先重建。
退出：判定「镜像可用 / 需重建」。

[2] static —— 修 IAT 而不是绕过
kitty_dump addr=0x0 path=logs\\fixed.bin unmap=true fix_iat=true reference=<同版本磁盘文件>
判据：一致率是否 >85%；fix_iat 从 ILT 回填。
退出：IAT 能解析出 ≥10 个 (模块,函数)。

[3] static 二次 —— 磁盘补不上的部分去内存补
kitty_sym source=mem module=<目标> action=imports
判据：内存视图比磁盘多出的项 = 运行期解析项。
退出：两份合并后导入项完整。

[4] dynamic —— 抽样核对
kitty_sym source=mem module=KERNEL32.dll action=resolve name=<解出的函数>
判据：解析出的 VA 与 IAT 值相等。
退出：抽 5 条全一致，IAT 判定修好。"""),

("只有一段汇编列表，没有二进制文件。怎么定流程？",
"""[1] triage —— 判断是反汇编产物还是源码片段
kitty_asm action=assemble code="nop" base=0x0
判据：列表里的地址是否连续、有无符号名。有符号名 → 来自调试器导出。
退出：确定「可重汇编 / 只能人工读」。

[2] static —— 重建骨架
kitty_asm action=assemble code=<片段> base=0x<起始VA>
判据：能否汇编通过。能 → 片段自洽，可做机器码比对。
退出：拿到机器码，与样本字节比对定位其位置。

[3] dynamic —— 用机器码在内存里定位
kitty_ce op=MODENUM
kitty_ce op="S_NEW|bytes:<N>|<机器码 hex>|0xBASE|0xBASE+SIZE" wait=true top=5
判据：命中地址 = 该片段在真实模块中的位置。
退出：至少一处命中，或确认不在该模块。

[4] 导出
产物：片段 VA/偏移 + 调用上下文（前后各 16 字节）。"""),

("样本跑起来就退出，没有任何输出。",
"""[1] triage —— 先拿退出码
kitty_x64dbg action=seed addr=kernel32.ExitProcess seedCmd=log
判据：退出码是唯一信息源。0xC0000135 = 缺 DLL；0xC0000005 = 访问违例。
退出：拿到退出码并归类。

[2] static —— 用导入面解释退出码
kitty_sym action=imports path=SAMPLE.exe
判据：缺 DLL 时找出哪个导入对不上（本机不存在该 DLL）。
退出：定位缺失依赖。

[3] dynamic —— 补齐后看首行为
kitty_ce op=OPEN|<pid>
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：补齐后是否有变化（初始化是否跑起来）。
退出：能观测到初始化行为，或拿到新的失败点。

[4] 导出
产物：退出码 → 根因 → 复现前提（需要哪些依赖）。"""),

("要给一份第三方样本写行为摘要，不逆代码。",
"""[1] triage —— 指纹先行
kitty_die action=detect target=SAMPLE.exe
kitty_patch action=hash path=SAMPLE.exe
判据：是否已知家族、是否加壳。
退出：能归族就停；不能归族进 [2]。

[2] static —— 能力面四桶
kitty_sym action=imports path=SAMPLE.exe
判据：持久化 / 注入 / 外联 / 破坏四桶命中数。
退出：≥2 桶命中 → 高度可疑，进 [3]；1 桶 → 只做摘要。

[3] dynamic —— 一条可复现行为
kitty_ce op=MODENUM
kitty_ce op="S_NEW|bytes:4|<已知特征>|0xBASE|0xBASE+SIZE" wait=true top=5
判据：特征是否在内存出现（解密/装载证据）。
退出：拿到一条行为（外联地址 / 落地路径 / 注册表键）。

[4] 导出
产物：指纹 + 四桶矩阵 + 一条行为 + 置信度。不写无证据的「恶意」。"""),

("给了个 Unity IL2CPP 游戏的 global-metadata.dat，没有 GameAssembly.dll。",
"""[1] triage —— 判元数据版本
kitty_engines path=<目录>
判据：metadata 头部的版本字段（magic 0xFAB11BAF + version）。
退出：拿到版本号。

[2] static —— 版本决定工具
kitty_il2cppdumper action=dump so=<缺失> meta=<metadata> out=logs\\il2cpp
判据：缺 so 无法定位方法地址，但元数据结构（类/字段名）仍可解。
退出：拿到类名与字段名清单（无地址）。

[3] 补 so —— 从包里找
kitty_patch action=find path=<数据目录> pattern="7F 45 4C 46" limit=8
判据：ELF 头命中 → 找到 libil2cpp.so / GameAssembly.dll 的存储位置。
退出：拿到 so 后回到 il2cppdumper 拿完整 dump。

[4] 导出
产物：类/字段清单 + 版本 + 是否补齐 so。
缺 so 时字段偏移不可信，只交结构名。"""),

("要在不改文件的前提下确认某个补丁点是否生效。",
"""[1] triage —— 定位指令
kitty_sym action=exports path=TARGET.dll
kitty_ghidra action=analyze target=TARGET.dll
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<校验串>
判据：字符串 xref 回到函数，函数内有 cmp + 条件跳转。
退出：拿到指令 RVA。

[2] static —— 算运行期地址
kitty_ce op=MODENUM
判据：VA = base + RVA；base 必须来自当前进程。
退出：拿到 VA。

[3] dynamic —— 读指令字节
kitty_ce op="R|0xVA|bytes:8"
判据：与磁盘字节一致 → 未打补丁；不同 → 已改动（记下新字节）。
退出：给出「原始 / 已改」判定。

[4] 导出
产物：RVA + 原字节 + 现值 + 判定。不动任何字节，只读。"""),

("样本用了自定义 VM，字节码在 .rdata。",
"""[1] triage —— 找 VM 入口与分发表
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=entry
判据：入口后出现「读字节码 → 查跳转表 → 分支」的循环。
退出：定位到分发循环与跳转表地址。

[2] static —— 抽 opcode 表
kitty_dump module=SAMPLE.exe path=logs\\img.bin
kitty_ce op="MEMDUMP_HEX|<跳转表VA>|1024"
判据：表内条目数 = opcode 数量；每个条目指向 handler。
退出：拿到 opcode → handler 映射表。

[3] dynamic —— 用 trace 验证样本执行了哪些 opcode
kitty_x64dbg action=seed addr=<分发循环VA> seedCmd=log
判据：日志里出现的 handler 顺序 = 真实执行序列。
退出：至少覆盖 10 个不同 opcode。

[4] 导出
产物：opcode 表 + handler 语义（每个 opcode 做了什么）+ 一段可读的字节码反汇编。"""),

("要做跨版本偏移迁移，只有两个版本的 exe。",
"""[1] triage —— 先定锚点函数
kitty_die action=detect target=OLD.exe
kitty_sym action=imports path=OLD.exe
判据：导入面与字符串在旧版里定位目标函数。
退出：拿到旧版函数偏移。

[2] static —— 结构对齐
kitty_ida action=analyze target=OLD.exe
kitty_ida action=functions out=logs\\ida-old-<ts> filter=<函数名>
kitty_ida action=analyze target=NEW.exe
kitty_ida action=functions out=logs\\ida-new-<ts> limit=200
判据：函数数量级一致 → 可做函数级 diff。
退出：拿到两侧函数清单。

[3] static 二次 —— 函数级比对
kitty_rea action=call tool=compare_functions args={"left":<旧>,"right":<新>}
判据：相似度 >0.8 视为同一函数，偏移迁移成立。
退出：给出「旧偏移 → 新偏移」映射表。

[4] dynamic —— 抽样验证
kitty_ce op=MODENUM
kitty_ce op="R|0xNEW_BASE+0x新偏移|bytes:8"
判据：与旧版对应位置字节形态一致（序言相同）。
退出：抽 3 个全通过，迁移表可用。"""),

("样本在特定界面才崩，平时稳定。",
"""[1] triage —— 先判崩溃类型
kitty_x64dbg action=run target=APP.exe
判据：崩溃地址是否在模块内（在 = 逻辑错；不在 = 数据驱动）。
退出：拿到崩溃地址与异常码。

[2] static —— 用偏移定位代码
kitty_patch action=info path=APP.exe
判据：崩溃 RVA = 崩溃 VA - 运行时 base，是否落在某节。
退出：确定代码位置或确认是数据区。

[3] dynamic —— 复现路径最小化
kitty_ce op=MODENUM
kitty_ce op="R|0xCRASH_ADDR-16|bytes:32"
判据：崩溃前 16 字节的指令（越界读/写的前置操作）。
退出：能说出「哪个操作在什么输入下越界」。

[4] 导出
产物：崩溃指令 + 触发输入 + 最小复现步骤。
判据：按步骤能在干净环境复现。"""),

("要判断样本是否在检测分析环境。",
"""[1] triage —— 静态找检测面
kitty_sym action=imports path=SAMPLE.exe
判据：IsDebuggerPresent / NtQueryInformationProcess / GetTickCount /
EnumProcesses / SetupAPI 五类任一。
退出：列出命中的检测类别。

[2] static —— 找检测后的分支
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<检测 API 名>
判据：xref 后是否紧跟条件跳转 + 异常路径（退出/降级/延时）。
退出：拿到失败分支的行为。

[3] dynamic —— 观测是否真的触发
kitty_ce op=LP
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：正常运行下是否有变化（初始化是否被跳过）。
退出：给出「检测触发 / 未触发」。

[4] 导出
产物：检测类别 + 失败分支行为 + 触发条件。"""),

("给了个 .NET 程序的 IL 字节码片段（hex）。",
"""[1] triage —— 先确认是 IL 不是机器码
kitty_asm action=assemble code="nop" base=0x0
判据：IL 常见首字节 0x72(ldstr) / 0x28(call) / 0x2A(ret)，与 x86 序言不重合。
退出：确认 IL。

[2] static —— 用 dnSpy 反查
kitty_dnspy action=status
kitty_dnspy action=decompile target=<所属 assembly> out=logs\\dnspy
判据：能否定位到对应方法（按方法长度与开头字节匹配）。
退出：拿到方法源码。

[3] 无 assembly 时 —— 手工解
判据：IL 是栈式指令，0x72 + 4 字节 token 指向字符串堆。
退出：至少解出「调用哪个方法 + 用哪个字符串」。

[4] 导出
产物：IL 片段的语义摘要（调用序列 + 常量）。
判据：能还原成一段伪 C#。"""),

("要在不改动目标的情况下确认某个函数被调用过。",
"""[1] triage —— 先找可观测副作用
kitty_sym action=imports path=SAMPLE.exe
判据：该函数是否写文件/发网络/改注册表 —— 有副作用就能从外部观测。
退出：有副作用走 [3]；无副作用走 [2]。

[2] static —— 找调用点
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=<函数名>
判据：xref 是否存在（不存在 = 死代码，永远不会被调）。
退出：xref 数为 0 则可直接判「不会调用」并收工。

[3] dynamic —— 只读观测
kitty_ce op="S_SNAP|bytes:16|<副作用区域>|<副作用区域+0x1000>"
判据：副作用区域是否出现变化。
退出：有变化 = 被调用过；无变化 = 未调用或副作用在别处。

[4] 导出
产物：判定 + 观测区域 + 变化证据。不下断点、不注入。"""),

("样本从网络下载第二个模块并执行。",
"""[1] triage —— 确认下载与执行两条链
kitty_sym action=imports path=SAMPLE.exe
判据：URLDownloadToFile / WinHttp + CreateProcess / ShellExecute 组合。
退出：确认两条链都存在。

[2] static —— 取 URL 与落盘路径
kitty_patch action=find path=SAMPLE.exe str=http limit=16
kitty_patch action=find path=SAMPLE.exe str=.exe utf16=true limit=8
判据：URL + 路径模板。
退出：给出「从哪下、下到哪」。

[3] dynamic —— 观测落盘与执行
kitty_net action=capture port=8080
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：抓包拿到真实 URL；快照拿到内存里的解密/装载证据。
退出：拿到落地文件或其内存镜像。

[4] 导出
产物：URL + 落盘路径 + 二次模块的 hash + 执行方式。
二级模块按新样本重开一轮。"""),

("要在 5 分钟内给出一份「这份样本干什么」的判断。",
"""[1] triage（60 秒）—— 三个命令
kitty_die action=detect target=SAMPLE.exe
kitty_patch action=info path=SAMPLE.exe
kitty_sym action=imports path=SAMPLE.exe
判据：壳/语言/架构 + 能力面。
退出：能说出「疑似什么」。

[2] static（90 秒）—— 只捞明文
kitty_patch action=find path=SAMPLE.exe str=http limit=16
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=8
判据：外联与持久化线索。
退出：拿到任一条具体地址或键名。

[3] dynamic（90 秒）—— 只跑不追
kitty_ce op=MODENUM
kitty_ce op="S_NEW|bytes:4|<特征>|0xBASE|0xBASE+SIZE" wait=true top=5
判据：特征是否出现。
退出：一条行为证据或明确「静态已足够」。

[4] 导出（60 秒）
产物：一句话结论 + 三条证据 + 一条未解项。
纪律：时间盒到了就交，不追求完整。"""),

("IAT 里一半的项指向同一个地址。",
"""[1] triage —— 确认是「合并转发」还是「劫持」
kitty_sym action=imports path=SAMPLE.exe
判据：多个不同函数名指向同一 IAT 槽 → 异常。
退出：确认异常项数量。

[2] static —— 看那个地址是什么
kitty_ce op=MODENUM
kitty_ce op="R|0xIAT_SLOT|qword"
kitty_prot action=query addr=<读出的值>
判据：落在某模块内 = 转发到一个统一分发函数；落在匿名区 = 劫持桩。
退出：判定归属。

[3] dynamic —— 调用是否真的会走它
kitty_ce op="S_NEW|bytes:8|<该地址>|0xBASE|0xBASE+SIZE" wait=true top=5
判据：该地址是否被写进多个 IAT 槽。
退出：确认「多槽同址」。

[4] 导出
产物：异常 IAT 项清单 + 统一目标 + 归属判定。
这类结构常见于 API 转发层或保护壳的导入重定向。"""),

("只有符号文件（PDB），没有二进制。",
"""[1] triage —— 先判断 PDB 能提供什么
kitty_sym action=exports path=<同版本二进制>
判据：PDB 给的是「名字 → RVA」，没有字节就没有代码。
退出：确认二进制是否可得。

[2] static —— 从 PDB 抽符号表
kitty_sym action=exports path=<binary> filter=.
判据：导出面 + PDB 公共符号（函数名、结构体名）能给出设计意图。
退出：拿到符号清单。

[3] 二进制不可得时 —— 只用 PDB 做「期望对照」
判据：PDB 里的函数数量与模块导出数对比，判断该模块规模。
退出：给出「模块职责推断」而非实现结论。

[4] 导出
若有二进制但无导出，改用反汇编器补面：
```
kitty_ida action=analyze target=<binary>
kitty_ida action=functions out=logs/ida-pdb-<ts> limit=80
kitty_ghidra action=functions out=logs/ghidra-pdb-<ts> filter=<PDB 里的函数名>
```
判读：PDB 里的函数名能对上反汇编器识别出的地址 → 符号可用。

产物：符号清单 + 职责推断 + （有字节时）符号与地址的对应表。明确写「无字节，不给实现结论」。"""),

("样本会在运行期改写自己的导入表。",
"""[1] triage —— 观测 IAT 是否变化
kitty_ce op=MODENUM
kitty_ce op="S_SNAP|bytes:16|0xBASE+0xIDATA_RVA|0xBASE+0xIDATA_RVA+0x400"
判据：启动前后 IAT 区是否变化。
退出：确认改写行为。

[2] static —— 找改写点
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=WriteProcessMemory
判据：写自己 IAT 的代码通常用 memcpy 或直接赋值。
退出：定位改写函数。

[3] dynamic —— 取改写后的真值
kitty_ce op="R|0xBASE+0xIDATA_RVA|qword"
kitty_sym source=mem module=KERNEL32.dll action=resolve name=<候选函数>
判据：解析值落在目标函数体内。
退出：拿到 ≥10 个真实映射。

[4] 导出
产物：改写前后 IAT 对照 + 改写点偏移 + 真实导入面。"""),

("要确认样本是否用了 TLS 做反调试。",
"""[1] triage —— TLS 目录存在性
kitty_die action=detect target=SAMPLE.exe
判据：TLS 目录非空且回调数 ≥1。
退出：无 TLS 即结束。

[2] static —— 回调体内容
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=Tls
判据：回调里是否调 IsDebuggerPresent / QueryPerformanceCounter / NtQuery。
退出：判定「反调试 / 仅初始化」。

[3] dynamic —— 时序验证
kitty_x64dbg action=seed addr=<回调VA> seedCmd=log
判据：回调是否在入口前命中。
退出：确认「入口前执行」这一事实。

[4] 导出
产物：回调数 + 各回调职责 + 时序证据。"""),

("样本的字符串全是 Unicode 转义序列。",
"""[1] triage —— 判断是编码还是混淆
kitty_patch action=find path=SAMPLE.exe str=\\u limit=8
判据：命中即源码级转义残留（Java/C# 常见），不是混淆。
退出：确认编码类型。

[2] static —— 批量还原
kitty_patch action=find path=SAMPLE.exe str=\\u0041 limit=2
判据：能定位到一段连续转义 → 用脚本批量 unescape。
退出：拿到明文串。

[3] 若是运行时拼接 —— 改走动态
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
kitty_ce op=S_CHANGED
判据：明文在内存里出现（拼接结果）。
退出：拿到明文。

[4] 导出
产物：明文串清单 + 还原方式（静态 unescape / 动态取内存）。"""),

("要在同一台机器上比较「加壳前/加壳后」的行为差异。",
"""[1] triage —— 两个样本都能跑吗
kitty_die action=detect target=packed.exe
kitty_die action=detect target=orig.exe
判据：壳的档位。带 VM 的壳无法静态比对。
退出：确定比对层面（静态 / 仅行为）。

[2] static —— 静态只比结构
kitty_patch action=info path=packed.exe
kitty_patch action=info path=orig.exe
判据：节表差异 = 壳的改动范围。
退出：拿到结构差异表。

[3] dynamic —— 行为面比对（这才是重点）
kitty_ce op=MODENUM
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：解密完成后的内存镜像与 orig 的对应节一致率。
退出：一致率 >90% 说明壳只做包装。

[4] 导出
产物：结构差异 + 行为一致率 + 「壳是否改变逻辑」结论。"""),

("样本导入了 CreateService。",
"""[1] triage —— 确认服务安装意图
kitty_sym action=imports path=SAMPLE.exe filter=Service
判据：CreateService + OpenSCManager 组合。
退出：确认安装能力。

[2] static —— 取服务名与路径
kitty_patch action=find path=SAMPLE.exe str=.exe utf16=true limit=16
kitty_patch action=find path=SAMPLE.exe str=SYSTEM\\CurrentControlSet\\Services utf16=true limit=4
判据：服务名与 binPath 模板。
退出：给出「服务名 + 映像路径」。

[3] dynamic —— 验证真的装了
kitty_ce op=LP
判据：宿主侧只读查询服务表（不改动），确认存在性。
退出：给出「已安装 / 未触发」。

[4] 导出
产物：服务名 + 路径 + 启动类型 + 是否已安装。"""),

("老板要一份「这个 DLL 能不能安全加载」的判断。",
"""[1] triage —— 加载面风险
kitty_die action=detect target=MODULE.dll
kitty_sym action=exports path=MODULE.dll
判据：是否有 DllMain 里的敏感操作、是否有导出劫持面。
退出：列出风险项。

[2] static —— DllMain 内容
kitty_ghidra action=analyze target=MODULE.dll
kitty_ghidra action=decompile out=logs\\ghidra-mod-<ts> name=DllMain
判据：PROCESS_ATTACH 分支里是否创建线程/写文件/外联。
退出：判定「纯初始化 / 有副作用」。

[3] dynamic —— 在隔离进程里加载
kitty_ce op=ALLOC 不用；用宿主侧隔离进程加载并观测
判据：加载后是否出现新线程/新文件/新连接。
退出：给出副作用清单。

[4] 导出
产物：可加载性结论 + 副作用清单 + 前置条件（签名/依赖）。
判据：结论必须能支撑「加载 / 不加载」这个决策。"""),

("样本在 32 位系统能跑、64 位不能。",
"""[1] triage —— 位数与子系统
kitty_patch action=info path=SAMPLE.exe
判据：Machine=0x14C(32) 且 Subsystem 版本字段。
退出：确认 32 位。

[2] static —— WoW64 相关的显式检查
kitty_sym action=imports path=SAMPLE.exe filter=Wow64
判据：IsWow64Process / Wow64DisableWow64FsRedirection 存在 → 有位数相关逻辑。
退出：定位检查点。

[3] dynamic —— 在 64 位系统上观测失败点
kitty_x64dbg action=run target=SAMPLE.exe
判据：失败位置在重定向或路径查找处。
退出：拿到具体失败 API。

[4] 导出
产物：失败 API + 触发条件 + 规避方式（用 32 位调试器/关重定向）。"""),

("要在不重启的情况下让样本进入「已注册」状态。",
"""[1] triage —— 先定位状态判据
kitty_sym action=imports path=SAMPLE.exe filter=Reg
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=16
判据：状态存在注册表 / 文件 / 内存三处之一。
退出：确定状态载体。

[2] static —— 找读取点
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<键名>
判据：读取函数返回后的分支决定「已注册 / 未注册」。
退出：定位判断分支。

[3] dynamic —— 改内存里的判据（不改磁盘）
kitty_ce op="S_NEW|dword|1|<判据区>|<判据区+0x1000>" wait=true top=10
kitty_ce op="W|0xCAND|dword|1" confirm=true
kitty_ce op="R|0xCAND|dword"
判据：写入后行为是否切换。
退出：行为切换 + 回读一致。

[4] 导出
产物：判据地址 + 原值 + 新值 + 回滚方式。
纪律：只在本机自有样本上做；不动磁盘与注册表。"""),

("样本只有一个 3KB 的 stub，真正的代码在别处。",
"""[1] triage —— stub 的职责
kitty_die action=detect target=stub.exe
kitty_sym action=imports path=stub.exe
判据：导入面极简（VirtualAlloc/LoadLibrary）→ 纯 loader。
退出：确认是 loader。

[2] static —— 找载荷来源
kitty_patch action=info path=stub.exe
kitty_patch action=find path=stub.exe pattern="4D 5A" limit=8
判据：overlay 或资源里的内嵌 PE。
退出：定位载荷位置。

[3] dynamic —— 若载荷是下载的
kitty_net action=capture port=8080
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：抓包拿到 URL；快照拿到装载区。
退出：拿到载荷本体。

[4] 导出
产物：loader 结构 + 载荷来源 + 载荷 hash。
载荷按新样本重开 triage。"""),

("要把一个可疑的注册表键值批量导出（只读）。",
"""[1] triage —— 先确认键存在
kitty_ce op=LP
判据：宿主侧只读查询该键是否存在。
退出：存在才继续。

[2] static —— 从样本侧确认它会读哪些值
kitty_patch action=find path=SAMPLE.exe str=<键名> utf16=true limit=8
判据：键名与值名列表（样本自己写的字符串）。
退出：拿到值名清单。

[3] 采集 —— 只读取值
判据：按值名逐个只读查询，记录类型与数据。
退出：每个值给出「存在 / 缺失 / 类型不符」。

[4] 导出
产物：键路径 + 值名/类型/数据表 + 采集时间。
纪律：全程只读，不新建、不修改、不删除。"""),

("要判断样本是否有「时间炸弹」。",
"""[1] triage —— 找时间源
kitty_sym action=imports path=SAMPLE.exe
判据：GetSystemTime / GetTickCount / NtQuerySystemTime / 文件时间读取。
退出：列出时间 API。

[2] static —— 找比较点
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=GetSystemTime
判据：返回值与常量比较，且常量是日期形态（如 0x07E8 年偏移）。
退出：定位比较常量。

[3] dynamic —— 改内存时间判据验证
kitty_ce op="S_NEW|qword|<常量>|<常量区>|<常量区+0x1000>" wait=true top=5
kitty_ce op="W|0xCAND|qword|<更晚的时间>" confirm=true
判据：改后行为切换 → 时间炸弹坐实。
退出：行为切换 + 回读一致。

[4] 导出
产物：时间常量 + 比较位置 + 触发日期 + 触发行为。"""),

("样本在调试器里行为不同（不在调试器里就不干活）。",
"""[1] triage —— 确认是反调试还是时序
kitty_sym action=imports path=SAMPLE.exe
判据：IsDebuggerPresent / CheckRemoteDebuggerPresent / NtQuery(7|30|31)。
退出：确认反调试面。

[2] static —— 找检测点与失败分支
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=IsDebuggerPresent
判据：xref 后的跳转指向「跳过主逻辑」。
退出：拿到分支地址。

[3] dynamic —— 改内存绕过（不改文件）
kitty_ce op="R|0xBRANCH|bytes:2"
kitty_ce op="W|0xBRANCH|bytes:EB <位移>" confirm=true
判据：改后主逻辑是否执行。
退出：行为切换 + 回读一致 + 记下原字节供回滚。

[4] 导出
产物：检测点 + 分支地址 + 原/新字节 + 回滚方式。
更稳的替代：kitty_x64dbg 的 stealth 附加，不改目标字节。"""),

("要在多份样本里找同一段代码。",
"""[1] triage —— 取一个跨版本稳定的签名
kitty_patch action=find path=A.exe pattern="48 8B ?? 05 ?? ?? ?? ??" limit=8
判据：命中数适中（一个文件里 1-5 处）。
退出：拿到候选签名。

[2] static —— 跨样本批量搜
kitty_patch action=find path=B.exe pattern="<同上>" limit=4
kitty_patch action=find path=C.exe pattern="<同上>" limit=4
判据：三份都能命中 → 签名跨样本稳定。
退出：确认签名可用。

[3] dynamic —— 在内存里复搜（对抗加壳）
kitty_ce op=MODENUM
kitty_ce op="S_NEW|bytes:<N>|<签名 hex 去掉通配>|0xBASE|0xBASE+SIZE" wait=true top=5
判据：内存命中地址 = 代码位置。
退出：拿到每个样本的落点。

[4] 导出
产物：签名 + 各样本落点 + 跨版本稳定性说明。"""),

("要判断某个函数是不是「只在这条路径上被调用」。",
"""[1] triage —— 先数 xref
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=<函数名>
判据：xref 数为 1 → 唯一调用点；>1 → 多路径。
退出：判定是否唯一。

[2] static —— 看唯一调用点的上游
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<调用者>
判据：调用者是否被界面事件/定时器直接驱动。
退出：确定「只在某路径」。

[3] dynamic —— 验证只在该路径命中
kitty_x64dbg action=seed addr=<函数VA> seedCmd=log
判据：只在触发该路径时命中，其他操作不命中。
退出：确认路径独占。

[4] 导出
产物：xref 数 + 调用点 + 触发条件。"""),

("要给上游解释「为什么这个偏移下次会变」。",
"""[1] triage —— 判断偏移的稳定性来源
kitty_ce op=MODENUM
判据：base 是模块基址（稳定）还是堆地址（每次变）。
退出：确定偏移类型。

[2] static —— 找静态归属
kitty_pchain target=0xTARGET depth=2 mod=TARGET.exe
判据：能否一路推到模块静态区。
退出：能推 → 偏移稳定；不能 → 只能存相对路径。

[3] dynamic —— 复验
kitty_ce op="P_WALK|0xBASE|0xOFF"
判据：回读等于目标地址。
退出：链成立。

[4] 导出
产物：偏移链（模块 + 各级偏移）+ 稳定性说明（哪级会变、为什么）。
这是唯一能让上游理解的交付形式。"""),
]

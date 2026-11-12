# -*- coding: utf-8 -*-
"""re-decision-chain 源 A1 (1-10)。动作序列可读出 triage → static → dynamic，每步一个判据。"""

CHAIN_A1 = [
(
"手上一个 exe，不知道语言、不知道壳、不知道干什么。给我完整判断顺序。",
"""[1] triage —— 先花 30 秒定性，不做任何反汇编
kitty_die action=detect target=SAMPLE.exe
判据：节名/熵/是否 .NET/是否已知壳四要素。
退出条件：能一句话说出「疑似什么」（.NET 托管 / 原生加壳 / 原生未加壳 / 脚本打包器）。
说不出来就先补 kitty_patch action=info 看节表与 Data Directory。

[2] static —— 只取结构化面，不读函数体
kitty_sym action=imports path=SAMPLE.exe
kitty_patch action=find path=SAMPLE.exe str=http limit=16
判据：导入组合（网络/注册表/进程/文件）与明文串决定行为骨架。
退出条件：能列出三条最可能的敏感行为；若导入被裁到 <15 项，加跑 kitty_ghidra action=analyze 拿 xref 补面。

[3] dynamic —— 用最小窗口观测行为，不追全量
kitty_ce op=MODENUM → base/size
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x11000"
跑起来后 S_CHANGED
判据：有变化 = 有自修改/解密；无变化 = 数据段静默，行为在网络或文件面。
退出条件：抓到至少一条可复现的行为证据（网络包 / 文件落地 / 注册表键）。

[4] 导出 —— 只交可复现的东西
产物：样本卡片（哈希 + 指纹 + 三条行为 + 一条可复现步骤 + 未解问题）。
判据：别人按卡片能重跑出同一结论。
不交付的东西：没有回读验证的写操作、只靠肉眼判断的地址。""",
),
(
"节名 UPX0/UPX1、熵 7.9、导入极少。这是标准 UPX 吗，能直接脱吗？",
"""[1] triage —— 先验真壳，别急着脱
kitty_die action=detect target=SAMPLE.exe
判据：节名 UPX0/UPX1 + 熵 >7.5 + 导入只剩 LoadLibrary/GetProcAddress → 标准 UPX 形态。
反例：UPX0 的 VirtualSize 远大于 RawSize 且 UPX1 熵只有 5.x = 改过的 UPX，通用脱壳会失败。

[2] static —— 确认壳版本与可用性
kitty_unpack action=probe target=SAMPLE.exe
kitty_patch action=find path=SAMPLE.exe str=UPX! limit=4
判据：字符串 UPX! + 版本能对上 → 通用脱壳器可用；找不到说明壳被重命名或改过。
退出条件：确认可用即进 [3]；不可用直接转静态自解（读壳 stub 的解压循环）。

[3] dynamic —— 脱壳并校验，不靠「看起来解开了」
kitty_unpack action=extract target=SAMPLE.exe out=logs\\unpacked
判读：产出文件先跑 kitty_die action=detect 复检熵，.text 应回落到 6.0-6.8。
再 kitty_dump module=<运行时模块名> unmap=true fix_iat=true reference=logs\\unpacked\\SAMPLE.exe
判据：与参考文件一致率 >90% 才算脱干净（壳只改布局不改代码）。

[4] 导出
产物：脱壳文件 + 一致率 + 原壳指纹。
退出条件：脱壳产物能过 kitty_sym action=imports 且导入项 >30 个（业务面回来了）。
仍只有 12 项导入 → 壳有两层，回到 [1] 对脱壳产物再 triage 一轮。""",
),
(
"给了个带 PDB 的样本，但 GUID 和镜像不匹配。先信谁？",
"""[1] triage —— 先判 PDB 是「指向」还是「残留」
kitty_die action=detect target=APP.exe
判据：Debug 目录里 PDB 的 GUID + Age 与公网符号不一致 = 不匹配。
退出条件：确认不匹配即放弃符号路线，不浪费时间去下 PDB。

[2] static —— 用能自证的信息替代符号
kitty_sym action=exports path=APP.exe
kitty_patch action=find path=APP.exe str=.pdb utf16=false
判据：导出名 + PDB 路径里的工程名，两者能给出一致的项目线索 → 命名函数仍有依据；
导出为空且路径无信息 → 完全无名，改用入口调用图。
退出条件：至少拿到「模块职责」定位。

[3] dynamic —— 用运行时证据代替静态符号
kitty_ce op=OPEN|<pid>
kitty_ce op=MODENUM                              → base / size
kitty_ce op="R|0xBASE+0x3C|dword"                → e_lfanew
kitty_ce op="R|0xBASE+0xE_LFANEW+0x28|dword"     → AddressOfEntryPoint (RVA)
判据：运行时入口处的字节与磁盘文件同偏移字节一致 → 无壳，可纯静态推进；
不一致 → 有自解密，先解决解密再谈符号。
退出条件：拿到「入口是否被改」的确定答案。

[4] 导出
产物：无符号函数清单 + 入口判据 + 项目线索。
不做的事：伪造符号名。宁可用 sub_401000，也不用猜测的 API 名污染后续判读。""",
),
(
"进程在跑、有反调试、模块已加载。要拿关键数据，顺序怎么排？",
"""[1] triage —— 先测通道与反调试强度，再决定碰不碰调试器
kitty_status probe=true
kitty_ce op=PING
判据：桥通 = 可走 CE 内存路线；PING 超时 = 先修通道，别上调试器。
退出条件：通道可用。反调试强（有 DBG_ATTACH 失败史）时直接跳过调试器路线。

[2] static —— 从内存镜像取结构，绕开调试器
kitty_ce op=MODENUM
kitty_dump module=TARGET.exe unmap=true path=logs\\mem.bin
判据：内存镜像节表是否自洽；.text 熵是否回落（回落说明已解密）。
退出条件：拿到可静态读的镜像（有 .pdata、IAT 可解析）。

[3] dynamic —— 只读不附加
kitty_ce op="S_NEW|dword|<已知值>|0xBASE|0xBASE+SIZE" wait=true top=20
改值 → kitty_ce op=S_CHANGED 收窄 → R 回读
判据：候选跟随改值变化。全程不 attach、不下断点，反调试面基本无感。
退出条件：找到可回读验证的目标地址（连续两次改值都跟随）。

[4] 导出
产物：地址 + 模块内偏移 + 回验记录 + 「未触碰调试接口」的说明。
记录纪律：写明为什么不走 DBG_ATTACH（本 build 该路径有 fail-fast 杀宿主的风险）。""",
),
(
"拿到一份内存 dump，节对齐明显异常。还能用静态工具吗？",
"""[1] triage —— 先判它是「磁盘格式」还是「内存镜像」
kitty_die action=detect target=dump.bin
判据：SectionAlignment 与 FileAlignment 是否相等。内存镜像两者都等于页大小 0x1000。
退出条件：判定格式。内存镜像不能直接喂 kitty_ida（它按文件偏移读原始数据）。

[2] static —— 先把镜像重建回磁盘格式
kitty_dump addr=0x0 path=logs\\rebuilt.bin unmap=true fix_iat=true reference=<同版本磁盘文件>
判据：unmap 后每个节 PointerToRawData 按 FileAlignment 重排；fix_iat 从 ILT 回填。
一致率：>85% 说明对齐与 IAT 都修对了；<60% 说明不是简单 unmap，另有变形。
退出条件：重建产物能过 kitty_die 且节表自洽。

[3] static 二次 —— 在重建产物上做符号与函数
kitty_ida action=analyze target=logs\\rebuilt.bin
kitty_ida action=functions out=logs\\ida-dump-<ts> limit=80
判据：函数识别数与 .pdata 条数量级吻合（差 10 倍以上说明对齐仍错）。
退出条件：能解出至少一个业务函数且语义自洽。

[4] 导出
产物：重建镜像 + 一致率 + 函数清单。
不做的事：直接在原始 dump 上反汇编。对齐错位会让所有 RVA 偏移，产出的「函数」全是垃圾。""",
),
(
"无导出、无 PDB、字符串还加密了。从哪切？",
"""[1] triage —— 先确认「三无」是不是真的
kitty_die action=detect target=SAMPLE.exe
kitty_sym action=exports path=SAMPLE.exe
判据：导出为 0 且 Debug 目录为空 → 确认三无。
字符串再验一次：kitty_patch action=find path=SAMPLE.exe str=kernel32 limit=4
判读：连导入 DLL 名都搜不到，说明是加密不是缺失。
退出条件：三无确认 + 加密确认。

[2] static —— 从结构面找可用锚点
kitty_patch action=info path=SAMPLE.exe
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=entry
判据：入口函数体的调用图（Ghidra 靠 call 目标建图，不需要符号）。
退出条件：拿到入口往下 3 层调用关系，够定位「初始化 → 解密 → 主逻辑」。

[3] dynamic —— 用行为锚定静态，而不是反过来
kitty_ce op=MODENUM
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x21000"
触发一次功能 → kitty_ce op=S_CHANGED
判据：变化页 = 解密落点，把落点地址回填到 Ghidra 按 VA 定位函数。
退出条件：至少把「变化页」与「某个静态函数」对上。

[4] 导出
产物：调用图三层 + 解密落点 + 任意一串解出的明文。
反模式：不靠猜字符串含义推进；没有明文就先交结构，不硬编故事。""",
),
(
"只有 crash dump 和一个可疑地址 0x00007FF7A2B31000。怎么用？",
"""[1] triage —— 先判这个地址是不是有效代码
kitty_dump addr=0x00007FF7A2B31000 size=0x400 path=logs\\suspect.bin
判据：首字节是否可执行序言（48 89 / 55 8B EC / 40 53）；是否全零（未映射页）。
退出条件：判定「代码 / 数据 / 空页」。空页说明地址已释放，转查调用栈。

[2] static —— 用模块归属把地址变成偏移
kitty_patch action=info path=CRASH_MOD.exe
判据：0x00007FF7A2B31000 - ImageBase = 模块内偏移；
超出 SizeOfImage 说明该地址不在本模块，去栈里找其他模块。
退出条件：拿到可复用 RVA，不依赖本次 ASLR 后的绝对值。

[3] dynamic —— 复现并抓现场
kitty_x64dbg action=run target=CRASH_MOD.exe
kitty_x64dbg action=seed addr=<RVA + 运行时基址> seedCmd=run
判据：能否在崩溃前命中；命中后 readdb 读栈找返回地址链。
退出条件：拿到崩溃指令 + 至少两帧调用栈。

[4] 导出
产物：崩溃指令字节 + 偏移 + 栈帧（RVA 形式）+ 复现步骤。
判据：复现步骤在干净环境能再次触发同一崩溃。
做不到就只交「地址归属 + 字节内容」，不给推测性根因。""",
),
(
"启动后 3 秒内 IAT 才填好。这个时间窗怎么利用？",
"""[1] triage —— 先确认 IAT 是运行期重建
kitty_sym action=imports path=SAMPLE.exe
判据：磁盘导入项极少或全是占位，而运行 3 秒后功能正常 → 运行期重建。
退出条件：坐实「磁盘 IAT 不可信」。

[2] static —— 用磁盘文件只做布局参考
kitty_patch action=info path=SAMPLE.exe
判据：idata 节 RawSize 与 VirtualSize 的差值；差大说明预留了重建空间。
退出条件：知道 IAT 会被写到哪一段 VA 区间。

[3] dynamic —— 在时间窗之后取真值，不在窗内抢
kitty_ce op=OPEN|<pid>
kitty_ce op=MODENUM                                 → base
等 5 秒
kitty_ce op="R|0xBASE+0xIDATA_RVA|qword"
判据：读到的指针是否落在 KERNEL32 的映射区间（kitty_prot action=query 查归属），
逐项 +8 字节推进。
退出条件：能解出 ≥10 个有效 (模块, 函数) 对。

反向验证：
kitty_sym source=mem module=KERNEL32.dll action=resolve name=<解出的函数名>
判据：解析出的 VA 与 IAT 里的值相等 → 映射正确。抽 5 条全一致才收。

[4] 导出
产物：重建导入表（模块 + 函数 + VA）+ 采集时刻。
坑：窗内抢读拿到的是壳的桩地址，看着是有效指针但指向 .text，别当导入用。""",
),
(
"分析完要交一份带证据的报告。动作序列怎么排才不会返工？",
"""[1] triage —— 先把「要回答什么问题」写死
kitty_die action=detect target=SAMPLE.exe → 指纹入档
判据：报告要回答的三个问题此刻必须确定（它是什么 / 它做了什么 / 证据在哪）。
退出条件：三个问题成文。没定就往下做，后面必然返工。

[2] static —— 每条结论旁边就留证据位
kitty_sym action=imports path=SAMPLE.exe
kitty_patch action=info path=SAMPLE.exe
判据：每个结论对应一个可重放命令 + 输出片段，不是「我看到了」。
退出条件：静态结论全部带命令；未带命令的结论删掉。

[3] dynamic —— 证据必须是可复现的回读
kitty_ce op="W|0xADDR|dword|<值>" confirm=true
kitty_ce op="R|0xADDR|dword"                     → 写入证据
kitty_km action=read addr=0xADDR vt=dword         → 跨视图证据
判据：两视图一致才算证据；不一致要写成「存在拦截面」这个结论本身。
退出条件：每条行为结论都有回读。

[4] 导出
产物结构：指纹 → 结论三条 → 每条的命令 + 输出 → 未解问题 → 复现步骤。
判据：第三方按复现步骤能跑出同样输出。
纪律：不出现无命令支撑的形容词；要么给判据，要么写「未判定」。""",
),
(
"给了个 pcap，想知道载荷是什么结构。先做什么？",
"""[1] triage —— 先判协议是文本还是二进制
kitty_net action=decode out=<pcap> filter="tcp" limit=40
判据：字节里是否有 HTTP 头 / JSON 花括号；否则按二进制处理。
退出条件：确定帧类型（文本 / 定长 / 长度前缀 / 分隔符）。

[2] static —— 离线做字段对齐，先看长度分布
kitty_proto action=status
kitty_proto action=decode target=<首帧 hex>
判据：protobuf 能否解析（能解析即 protobuf 家族）；失败则看首字节是否像长度字段。
退出条件：给出帧头假设（长度字段字节数 + 是否含校验）。

[3] dynamic —— 回放到本地端点验证假设
kitty_net action=capture port=8080
按假设构造一帧发出去
判据：服务端回包正常 → 帧头假设成立；回包断开/超时 → 帧头错。
退出条件：至少一帧被服务端接受。

[4] 导出
产物：帧结构表（偏移/长度/字段/样例）+ 一帧可重放 hex + 校验算法（若存在）。
判据：按表构造的新帧仍被接受。
不做：只给「看着像自定义协议」就收工 —— 那不是结论。""",
),
]

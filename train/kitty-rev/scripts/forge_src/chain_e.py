# -*- coding: utf-8 -*-
"""re-decision-chain 扩量 E（61-90）"""

CHAIN_E = [
("样本是个 .sys，但不会加载（签名问题）。怎么在不加载的前提下分析？",
"""[1] triage —— 判类型与入口
kitty_die action=detect target=drv.sys
kitty_sym action=imports path=drv.sys
判据：DriverEntry 是否存在、导入是否以 ntoskrnl 为主。
退出：确认是内核驱动。

[2] static —— 纯静态建分发表
kitty_ghidra action=analyze target=drv.sys
kitty_ghidra action=functions out=logs\\ghidra-drv-<ts> filter=Dispatch
判据：分发函数里的 IOCTL 常量表。
退出：拿到 IOCTL 码 → 处理函数映射。

[3] dynamic —— 不加载，改读它引用的结构
kitty_ghidra action=decompile out=logs\\ghidra-drv-<ts> name=<处理函数>
判据：参数结构（METHOD_BUFFERED 还是 NEITHER）。
退出：给出「输入结构 + 权限要求」。

[4] 导出
产物：IOCTL 表 + 结构 + 是否需要签名才能加载。
纪律：不加载到本机；不上驱动。"""),

("客户端与服务端在同一台机上，要做协议对齐。",
"""[1] triage —— 两侧都拿到
kitty_die action=detect target=client.exe
kitty_die action=detect target=server.exe
判据：语言与是否加壳；至少一侧可读。
退出：确定主攻侧（通常客户端）。

[2] static —— 从客户端取协议常量
kitty_patch action=find path=client.exe str=HTTP limit=8
kitty_patch action=find path=client.exe str=0x limit=8
判据：命令字/魔数/长度字段常量。
退出：拿到帧头假设。

[3] dynamic —— 抓一次完整往返
kitty_net action=capture port=8080
判据：请求与响应的字节对齐。
退出：至少一组「请求 hex → 响应 hex」。

[4] 导出
产物：帧结构表 + 一组可重放的往返 hex。
判据：重放该 hex 能得到同样响应。"""),

("要在不改协议的前提下判断哪个字段是校验和。",
"""[1] triage —— 先看帧布局
kitty_net action=decode out=<pcap> filter="tcp" limit=40
判据：帧长固定且某 2/4 字节每帧都不同 → 候选校验位。
退出：锁定候选偏移。

[2] static —— 看客户端算法
kitty_patch action=find path=client.exe pattern="<候选偏移处的常量>" limit=4
判据：是否有 CRC/加法/异或 的常量表。
退出：拿到算法假设。

[3] dynamic —— 改一字节验证
判据：改载荷一字节，观察校验位是否按假设变化。
退出：假设成立或推翻。

[4] 导出
产物：校验位偏移 + 算法 + 一正一反两组验证数据。"""),

("要在样本里找「配置读取」的统一入口。",
"""[1] triage —— 找配置相关导入
kitty_sym action=imports path=SAMPLE.exe
判据：GetPrivateProfileString / RegQueryValueEx / fread 组合。
退出：确定配置来源。

[2] static —— 找封装函数
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=GetPrivateProfileString
判据：多个 xref 集中到一个封装函数 → 那就是统一入口。
退出：拿到入口地址。

[3] dynamic —— 断点验证
kitty_x64dbg action=seed addr=<入口VA> seedCmd=log
判据：每次配置读取都命中同一函数。
退出：确认入口唯一。

[4] 导出
产物：入口地址 + 它读的键名列表。
这份列表就是样本的完整配置面。"""),

("要判断样本是否会联网，但抓不到包。",
"""[1] triage —— 静态看网络能力
kitty_sym action=imports path=SAMPLE.exe
判据：ws2_32 / winhttp / wininet / urlmon 任一。
退出：无网络导入 → 可能走 DNS 或命名管道。

[2] static —— 找 URL 与域名
kitty_patch action=find path=SAMPLE.exe str=http limit=16
kitty_patch action=find path=SAMPLE.exe str=.com limit=8
判据：明文或简单异或的地址。
退出：拿到候选地址。

[3] dynamic —— 用 DNS 观测代替抓包
kitty_net action=status
判据：DNS 查询比 TCP 更容易观测（HTTPS 也看得见域名）。
退出：拿到实际解析的域名。

[4] 导出
产物：域名 + 端口 + 协议（HTTP/自定义）。
抓不到包不构成「不联网」的结论。"""),

("要在内存里找「所有指向某个模块的指针」。",
"""[1] triage —— 先定搜索范围
kitty_ce op=MODENUM
判据：目标模块 base/size。
退出：确定被指向的范围。

[2] static —— 无静态方法（指针是运行期构造的）
判据：磁盘文件里没有堆地址。
退出：确认必须动态。

[3] dynamic —— 按页反查
kitty_ce op="P_BACK|0xTARGET_MOD_BASE|0xHEAP_BASE|0xHEAP_BASE+0x400000"
判据：命中数。超过 200 就分片。
退出：拿到引用点列表。

[4] 导出
产物：引用点 + 每个引用点的归属（结构体/全局变量）。
判据：抽 3 条 R 回验通过。

"""),

("要判断一个函数是不是「解密器」。",
"""[1] triage —— 静态特征
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=sub_
判据：函数内有循环 + 异或/加减常量 + 一次写大块内存。
退出：拿到候选。

[2] static —— 看参数
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<候选>
判据：参数是（源指针、目标指针、长度、密钥）。
退出：确认签名形态。

[3] dynamic —— 观察调用前后内存
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
kitty_ce op=S_CHANGED
判据：调用后变化区正好等于函数写范围。
退出：确认解密器。

[4] 导出
产物：函数地址 + 参数 + 密钥来源（常量/参数/派生）。"""),

("样本用了 SEH 做控制流混淆。",
"""[1] triage —— 找异常注册链
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=__except_handler
判据：x64 下是 .pdata + 语言相关 handler；x86 下是 fs:[0] 链。
退出：确认 SEH 使用。

[2] static —— 看 handler 里的改写
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<handler>
判据：handler 里改 ContextRecord->Rip 就是控制流混淆。
退出：拿到改写点。

[3] dynamic —— 观察异常流
kitty_x64dbg action=seed addr=<handlerVA> seedCmd=log
判据：命中频率（混淆通常高频触发）。
退出：确认是混淆而非真实异常处理。

[4] 导出
产物：handler 地址 + Rip 改写目标 + 触发频度。
静态反汇编会看不出真实流，必须以动态为准。"""),

("要在两个进程间对齐一个结构体。",
"""[1] triage —— 两侧是否同架构
kitty_ce op=MODENUM
判据：is64 一致才谈对齐。
退出：不一致则结构布局必然不同。

[2] static —— 从可读侧取字段
kitty_ghidra action=analyze target=<可读侧exe>
kitty_ghidra action=decompile out=logs\\ghidra-<n>-<ts> name=<访问函数>
判据：字段偏移与宽度。
退出：拿到字段表。

[3] dynamic —— 另一侧按偏移验证
kitty_ce op="R|0xPEER_OBJ+0xOFF|dword"
判据：值语义是否吻合（如计数器单调、指针可解析）。
退出：至少 3 个字段对上。

[4] 导出
产物：字段表 + 两侧验证结果。"""),

("要判断样本是不是「只在特定条件下才下载载荷」。",
"""[1] triage —— 找条件源
kitty_sym action=imports path=SAMPLE.exe
kitty_patch action=find path=SAMPLE.exe str= limit=8
判据：时间/地域/语言/进程名 四类条件源。
退出：确定条件类别。

[2] static —— 找比较与分支
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<条件 API>
判据：比较后跳向下载函数。
退出：拿到分支地址与常量。

[3] dynamic —— 改内存满足条件
kitty_ce op="S_NEW|dword|<常量>|0xSTART|0xSTOP" wait=true top=5
kitty_ce op="W|0xCAND|dword|<满足值>" confirm=true
判据：下载行为是否被触发（抓包或落地文件）。
退出：触发 + 回读一致。

[4] 导出
产物：条件类别 + 常量 + 满足方式 + 触发后的行为。"""),

("要判断「这个地址是代码还是数据」。",
"""[1] triage —— 权限
kitty_prot action=query addr=0xADDR
判据：Protect 含 EXECUTE → 可能是代码。
退出：无执行权限即可直接判「数据」（除非自修改）。

[2] static —— 字节形态
kitty_ce op="R|0xADDR|bytes:16"
判据：是否以合法序言开头（48 89/55 8B/40 53）。
退出：拿到初判。

[3] dynamic —— 更硬的判据：有没有人跳过来
kitty_ce op="S_NEW|qword|0xADDR|0xBASE|0xBASE+SIZE" wait=true top=5
判据：有引用且引用点在代码段 → 被当函数用。
退出：确认代码/数据。

[4] 导出
产物：判定 + 三条支撑（权限/字节/引用）。
单靠字节形态不够，必须叠加权限或引用。"""),

("要在没有源码的情况下还原一个配置结构体。",
"""[1] triage —— 找配置载入点
kitty_sym action=imports path=SAMPLE.exe
判据：文件读取 + 结构解析的组合。
退出：定位载入函数。

[2] static —— 读字段访问序列
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<载入函数>
判据：连续的 [reg+偏移] 访问 → 字段布局。
退出：拿到偏移表。

[3] dynamic —— 按偏移读实例
kitty_ce op="MEMDUMP_HEX|0xINSTANCE|128"
判据：每个偏移处的值形态（指针/整数/字符串）。
退出：字段类型可以确定。

[4] 导出
产物：结构体定义（偏移/宽度/类型/样例值）。
判据：按该定义解析内存实例得到自洽结果。"""),

("样本的入口只在特定命令行参数下才有意义。",
"""[1] triage —— 找参数解析
kitty_patch action=find path=SAMPLE.exe str=-limit=8
kitty_patch action=find path=SAMPLE.exe str=/silent utf16=true limit=4
判据：参数串与比较逻辑。
退出：拿到参数清单。

[2] static —— 找分支
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<参数串>
判据：参数命中后跳向的功能函数。
退出：参数 → 功能映射。

[3] dynamic —— 用参数启动验证
kitty_x64dbg action=run target=SAMPLE.exe
判据：带参数启动后行为差异。
退出：确认参数作用。

[4] 导出
产物：参数表 + 每个参数触发的功能 + 默认行为。"""),

("要在 3 个疑似同族样本里确认是否同一份代码换了壳。",
"""[1] triage —— 取指纹四件套
kitty_die action=detect target=A.exe
kitty_patch action=hash path=A.exe
判据：节表布局 + 导入组合 + 字符串集。
退出：三份都取到。

[2] static —— 结构差分
kitty_patch action=info path=A.exe
kitty_patch action=info path=B.exe
kitty_patch action=info path=C.exe
判据：入口节、节数、数据目录布局是否同构。
退出：判断同构建链。

[3] dynamic —— 行为一致率
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：三份解密后的内存镜像两两比对一致率。
退出：>90% 即同代码。

[4] 导出
产物：指纹表 + 一致率矩阵 + 结论（同代码/同族/无关）。"""),

("要判断某个 API 调用是不是「有意的」。",
"""[1] triage —— 是否在死代码里
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=<API名>
判据：xref 数为 0 → 死代码（导入残留，不是有意调用）。
退出：确认是否可达。

[2] static —— 调用点上下文
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<调用者>
判据：调用前后是否有参数准备与错误处理。裸调用多为链接器引入。
退出：判定有意/无意。

[3] dynamic —— 验证是否真的执行
kitty_ce op="S_SNAP|bytes:16|0xTARGET|0xTARGET+0x1000"
判据：该 API 的副作用是否出现。
退出：确认执行。

[4] 导出
产物：判定 + 可达性 + 副作用证据。
「导入存在」不等于「会被调用」。"""),

("要在不解包的情况下判断 pak 里有没有某个资源。",
"""[1] triage —— pak 索引
kitty_fmodel action=list pak=<pak> aesKey=<key>
判据：索引能否解析出资产清单。
退出：拿到清单。

[2] static —— 按名过滤
kitty_fmodel action=list pak=<pak> aesKey=<key>
判据：清单里是否出现目标资源名前缀。
退出：命中即存在。

[3] 无法解索引时 —— 字节搜索
kitty_patch action=find path=<pak> str=<资源名> limit=4
判据：pak 的索引区通常含明文路径。
退出：命中即存在。

[4] 导出
产物：存在性结论 + 索引项（偏移/大小/压缩方式）。"""),

("要判断样本是不是「合法软件的破解版」。",
"""[1] triage —— 版本资源与签名
kitty_die action=detect target=APP.exe
kitty_patch action=info path=APP.exe
判据：签名是否被剥、版本资源是否完整。
退出：拿到完整性判断。

[2] static —— 找补丁痕迹
kitty_patch action=hash path=APP.exe
kitty_patch action=find path=APP.exe pattern="90 90 90 90" limit=8
判据：连续 NOP 是补丁的典型残留。
退出：确认补丁点。

[3] dynamic —— 校验和与体积
kitty_patch action=info path=APP.exe
判据：Checksum 是否为 0、节 RawSize 是否自洽。
退出：给出「被改过」证据。

[4] 导出
产物：改动证据（NOP 段 + 校验和 + 节表异常）+ 原厂版本对比建议。
定性只到「被修改过」，不推断进一步意图。"""),

("要在运行期确认某个文件是否被映射进内存。",
"""[1] triage —— 内存里的文件映射
kitty_prot action=query addr=0xADDR
判据：Type=MEM_MAPPED。
退出：确认存在文件映射。

[2] static —— 从映射内容反推格式
kitty_ce op="R|0xADDR|bytes:16"
判据：4D 5A / 50 4B / 89 50 4E 47 等魔数。
退出：确定映射的文件类型。

[3] dynamic —— 全表扫描映射区
kitty_ce op=MODENUM
kitty_prot action=query addr=0xMODULE_BASE
判据：遍历模块之间的空隙找 MEM_MAPPED 区。
退出：拿到所有映射区清单。

[4] 导出
产物：映射区地址 + 大小 + 内容类型。"""),

("要在不重装的情况下判断某驱动是否在运行。",
"""[1] triage —— 只读服务面
kitty_drv action=status
判据：双驱服务状态与文件存在性。
退出：确认本机驱动面。

[2] static —— 目标驱动的文件与签名
kitty_patch action=info path=drv.sys
判据：签名是否可解析、时间戳。
退出：确认驱动本体可信。

[3] dynamic —— 设备对象探活
kitty_drvio action=status
kitty_drvio action=probe device=<设备名> ioctl=0x0 inHex=
判据：设备能否 open、IOCTL 是否回 STATUS_INVALID_PARAMETER。
退出：判定「已加载 / 未加载」。

[4] 导出
产物：加载状态 + 探测方式 + 未加载时的等价判断（服务表只读查询）。"""),

("要判断样本是否有「只在安全模式下才生效」的分支。",
"""[1] triage —— 找安全模式检测
kitty_patch action=find path=SAMPLE.exe str=SafeBoot limit=4
kitty_patch action=find path=SAMPLE.exe str=CurrentControlSet\\Control\\SafeBoot utf16=true limit=4
判据：注册表安全模式键被引用。
退出：确认检测存在。

[2] static —— 找分支行为
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=SafeBoot
判据：检测结果决定「是否执行主逻辑」。
退出：拿到分支。

[3] dynamic —— 改内存模拟
kitty_ce op="S_NEW|dword|<检测返回值>|0xSTART|0xSTOP" wait=true top=5
kitty_ce op="W|0xCAND|dword|<目标值>" confirm=true
判据：主逻辑是否切换。
退出：行为切换 + 回读。

[4] 导出
产物：检测键 + 分支 + 两种模式下的行为差异。"""),

("要在二进制里找「所有加密常量」。",
"""[1] triage —— 按算法族取常量
kitty_patch action=find path=SAMPLE.exe pattern="67 45 23 01" limit=4
kitty_patch action=find path=SAMPLE.exe pattern="63 79 6E 67" limit=4
判据：MD5/SHA 初值、AES SBox、CRC 表。
退出：拿到命中的算法族。

[2] static —— 交叉验证尺寸
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<常量地址>
判据：常量的引用点覆盖的代码量（MD5 约 200 字节，AES 约 1KB）。
退出：确认算法实现规模。

[3] dynamic —— 输入输出对验证
kitty_ce op="R|0xCONST_TABLE|bytes:64"
判据：SBox 前 64 字节应与标准表一致或呈现可识别的变种规律。
退出：确认算法。

[4] 导出
产物：算法族 + 常量地址 + 是否变种 + 一组输入输出对。"""),

("要在注册表/文件/内存三处判断哪个是真状态源。",
"""[1] triage —— 三处各取一份
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=16
判据：样本写的键名/文件路径，确定三处位置。
退出：列出待查点。

[2] static —— 读取优先级
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<init>
判据：初始化函数里的读取顺序 = 优先级。
退出：确定「先读哪个」。

[3] dynamic —— 改一处看其余是否跟随
kitty_ce op="W|0xMEM_STATE|dword|<新值>" confirm=true
判据：界面/行为是否随内存变化（内存优先）或需要重启（文件/注册表优先）。
退出：确认真源。

[4] 导出
产物：真状态源 + 优先级顺序 + 同步方向。"""),

("要判断「这个样本会不会改自己的代码」。",
"""[1] triage —— 可写代码节
kitty_patch action=info path=SAMPLE.exe
判据：.text 是否含 MEM_WRITE。
退出：不可写则基本不会自改（除非改页属性）。

[2] static —— 找改页属性调用
kitty_sym action=imports path=SAMPLE.exe filter=VirtualProtect
判据：有 VirtualProtect 且目标是自己模块 → 准备自改。
退出：确认自改能力。

[3] dynamic —— 快照观测
kitty_ce op="S_SNAP|bytes:16|0xTEXT_VA|0xTEXT_VA+0x2000"
kitty_ce op=S_CHANGED
判据：代码段是否出现变化。
退出：确认自改发生。

[4] 导出
产物：自改点 + 变化字节 + 触发条件。
自改点常是反调试或热补丁的落点。"""),

("要在两小时内交付一份可复现的样本分析。",
"""[1] triage（15 分钟）—— 指纹与分诊
kitty_die action=detect target=SAMPLE.exe
kitty_patch action=hash path=SAMPLE.exe
判据：家族/壳/语言三要素。
退出：能写出一段「这是什么」。

[2] static（45 分钟）—— 结构与能力面
kitty_sym action=imports path=SAMPLE.exe
kitty_patch action=info path=SAMPLE.exe
kitty_ghidra action=analyze target=SAMPLE.exe
判据：能力四桶 + 关键字符串。
退出：每个结论都有命令支撑。

[3] dynamic（45 分钟）—— 一条可复现行为
kitty_ce op=MODENUM
kitty_ce op="S_NEW|bytes:4|<特征>|0xBASE|0xBASE+SIZE" wait=true top=5
判据：至少一条行为证据。
退出：证据可被第三方复现。

[4] 导出（15 分钟）
产物：结论 + 证据（命令+输出）+ 复现步骤 + 未解项。
纪律：时间不够就砍「未解项」的深度，不砍证据。"""),

("要在不改动目标的前提下拿到「它调了哪些 API」。",
"""[1] triage —— 先看静态导入面
kitty_sym action=imports path=SAMPLE.exe
判据：静态导入 = 至少会调用的上限集。
退出：拿到上限集。

[2] static —— 剔除死代码引用
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> limit=120
判据：xref 为 0 的导入项可剔除。
退出：得到「可能调用集」。

[3] dynamic —— 用内存观测确认实际调用
kitty_ce op="S_NEW|qword|<某 API 地址>|0xBASE|0xBASE+SIZE" wait=true top=5
判据：该地址是否被写入 IAT（即被解析使用）。
退出：确认子集。

[4] 导出
产物：三层集合（导入 / 可达 / 已解析）。
判据：每层的差异都有依据。"""),

("要判断一个字符串是不是「运行时解密出来的」。",
"""[1] triage —— 磁盘上搜
kitty_patch action=find path=SAMPLE.exe str=<串> limit=2
判据：搜不到 → 加密或拼接。
退出：确认非明文。

[2] static —— 找解密函数
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=sub_
判据：循环 + 异或 + 写大块。
退出：定位解密器。

[3] dynamic —— 内存里搜
kitty_ce op=MODENUM
kitty_ce op="S_NEW|bytes:<N>|<串的 hex>|0xBASE|0xBASE+SIZE" wait=true top=5
判据：命中即运行时解密出来的。
退出：确认 + 拿到地址。

[4] 导出
产物：明文地址 + 解密器地址 + 密钥来源。"""),

("要在样本里区分「正常退出」与「检测到分析后退退出」。",
"""[1] triage —— 退出的调用点
kitty_sym action=imports path=SAMPLE.exe filter=Exit
判据：ExitProcess / TerminateProcess / RtlExitUserProcess 各自的调用点。
退出：列出退出路径。

[2] static —— 每个退出点的上游
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=ExitProcess
判据：上游是否紧跟检测 API 的返回值判断。
退出：区分「检测退出」与「正常退出」。

[3] dynamic —— 退出码
kitty_x64dbg action=seed addr=kernel32.ExitProcess seedCmd=log
判据：退出码的取值（检测类常用固定魔法值）。
退出：确认退出原因。

[4] 导出
产物：退出点列表 + 每个点的原因 + 退出码。"""),

("要判断样本是不是「只在首次运行时做某些事」。",
"""[1] triage —— 找首次标记
kitty_patch action=find path=SAMPLE.exe str=.dat limit=8
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=8
判据：它写/读的标记位置（文件或注册表）。
退出：确定标记位置。

[2] static —— 读写时序
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<init>
判据：先读标记 → 不存在则执行首次逻辑 → 写标记。
退出：确认首次逻辑范围。

[3] dynamic —— 两次运行对比
kitty_ce op=MODENUM
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：第二次运行的初始化差异。
退出：确认「首次专属行为」。

[4] 导出
产物：标记位置 + 首次逻辑清单 + 判断方法。"""),

("要在跨会话复用分析结果时保证地址有效。",
"""[1] triage —— 上次记的是什么
判据：若是绝对 VA，跨重启必然失效。
退出：确认记录形式。

[2] static —— 转成稳定形式
kitty_ce op=MODENUM
判据：offset = VA - base；或「模块名 + 节 + 节内偏移」。
退出：拿到可复用偏移。

[3] dynamic —— 新会话验证
kitty_ce op="R|0xNEW_BASE+0xOFF|dword"
判据：值与上次一致。
退出：确认可复用。

[4] 导出
产物：三要素记录格式（模块名 + 偏移 + 期望值）。
判据：新会话按三要素能一步定位。"""),
]

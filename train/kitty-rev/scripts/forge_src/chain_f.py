# -*- coding: utf-8 -*-
"""re-decision-chain 扩量 F（91-120）"""

CHAIN_F = [
("样本的导出全是加密字符串，没有提示。",
"""[1] triage —— 确认加密而非缺失
kitty_patch action=find path=SAMPLE.exe str=kernel32 limit=4
判据：连导入 DLL 名都搜不到 → 全表加密。
退出：确认加密。

[2] static —— 找解密入口
kitty_sym action=imports path=SAMPLE.exe filter=VirtualProtect
kitty_ghidra action=analyze target=SAMPLE.exe
判据：一次性解密的写法是「分配 → 解密 → 用指针替换原引用」。
退出：定位解密函数。

[3] dynamic —— 取解密后明文
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
kitty_ce op=S_CHANGED
判据：变化区里的 ASCII 串即明文。
退出：拿到明文清单。

[4] 导出
产物：解密函数 + 明文集 + 密钥来源。"""),

("要判断「这个样本在 2019 年后有没有被改过」。",
"""[1] triage —— 时间字段
kitty_patch action=info path=SAMPLE.exe
判据：TimeDateStamp、Debug 目录时间戳、资源时间戳。
退出：拿到三处时间。

[2] static —— 内容年代的间接证据
kitty_sym action=imports path=SAMPLE.exe
判据：导入的 API 集合反映年代（如 WinHttp vs 老 WinInet）。
退出：给出年代区间。

[3] dynamic —— 签名时间
kitty_patch action=find path=SAMPLE.exe pattern="30 82" limit=2
判据：证书 notBefore/notAfter 给出签署时间窗。
退出：确认签署年代。

[4] 导出
产物：三处时间 + API 年代 + 签名时间，交叉给结论。
不一致本身就是「被改过」的证据。"""),

("要在无符号的情况下恢复一个结构体数组的步长。",
"""[1] triage —— 找数组基址
kitty_ce op="S_NEW|dword|<已知字段值>|0xSTART|0xSTOP" wait=true top=20
判据：多个命中地址等距 → 数组。
退出：拿到至少 3 个元素地址。

[2] static —— 算步长
判据：地址差的最小值 = 步长（通常是 0x10/0x20/0x40）。
退出：确认步长。

[3] dynamic —— 按步长读字段
kitty_ce op="R|0xELEM0+0x8|dword"
kitty_ce op="R|0xELEM1+0x8|dword"
判据：同偏移处的值语义一致（都是 ID / 都是指针）。
退出：字段表成型。

[4] 导出
产物：步长 + 字段表 + 数组最大长度（按相邻等距元素计数）。"""),

("要判断某个模块是「先加载还是后加载」。",
"""[1] triage —— 模块表顺序
kitty_ce op=MODENUM
判据：加载顺序即表中顺序（主模块第一，系统 DLL 随后）。
退出：拿到顺序。

[2] static —— 静态依赖关系
kitty_sym action=imports path=SAMPLE.exe
判据：静态导入的模块必然早于样本初始化加载；延迟导入的晚。
退出：给出「静态依赖 / 延迟」两类。

[3] dynamic —— 触发功能后再看
kitty_ce op=MODENUM
判据：新出现的模块 = 运行期加载。
退出：确认加载时机。

[4] 导出
产物：加载顺序表 + 每个模块的触发条件。"""),

("要判断样本是否「依赖外部服务才完整工作」。",
"""[1] triage —— 找服务端地址
kitty_patch action=find path=SAMPLE.exe str=http limit=16
判据：硬编码的服务端地址。
退出：拿到地址。

[2] static —— 找连接失败分支
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<连接函数>
判据：连接失败后是退出、降级还是重试。
退出：确认依赖强度。

[3] dynamic —— 断网观测
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：断网下初始化能否完成。
退出：确认「硬依赖 / 软依赖」。

[4] 导出
产物：服务端地址 + 依赖强度 + 断网行为。"""),

("要给一段 shellcode 做静态画像。",
"""[1] triage —— 位数与入口
kitty_asm action=assemble code="nop" base=0x0
判据：首字节 48/4C → x64；55/53/E8 → 可能是 x86。
退出：确定位数。

[2] static —— API 解析方式
kitty_ida action=search target=<bin> filter=kernel32
判据：明文 DLL 名 = LoadLibrary 解析；无明文 = PEB 遍历。
退出：确认解析方式。

[3] static 二次 —— 行为面
kitty_ida action=strings out=logs\\ida-sc-<ts> limit=40
判据：URL/命令串/注册表键。
退出：拿到能力面。

[4] 导出
产物：位数 + 解析方式 + 能力面 + 是否有编码层。"""),

("要在同一进程里区分两个同名模块实例。",
"""[1] triage —— 模块表里是否真有两个
kitty_ce op=MODENUM
判据：同名行出现两次。
退出：确认双实例。

[2] static —— 两份文件的版本差异
kitty_patch action=info path=<路径A>\\mod.dll
kitty_patch action=info path=<路径B>\\mod.dll
判据：节表/大小是否不同。
退出：确认是两个文件。

[3] dynamic —— 按 base 区分读
kitty_ce op="R|0xBASE_A+0x1000|bytes:8"
kitty_ce op="R|0xBASE_B+0x1000|bytes:8"
判据：内容不同即两份都在运行。
退出：拿到各自 base。

[4] 导出
产物：两个 base + 各自调用方。"""),

("要判断补丁是否会被完整性校验发现。",
"""[1] triage —— 找校验点
kitty_sym action=imports path=SAMPLE.exe
kitty_patch action=find path=SAMPLE.exe str=hash limit=8
判据：是否有自校验（读自己的文件/内存 + 摘要比较）。
退出：确认校验存在。

[2] static —— 校验范围
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<校验函数>
判据：校验覆盖的地址区间是否包含你的补丁点。
退出：确认会被发现。

[3] dynamic —— 验证
kitty_ce op="W|0xPATCH|bytes:<新字节>" confirm=true
判据：程序是否在 N 秒内崩溃/退出。
退出：确认检出。

[4] 导出
产物：校验点 + 覆盖范围 + 与补丁点是否相交。
相交时改校验函数的返回值，而不是改被校验的代码。"""),

("要判断某个值是「服务端下发的」还是「本地算的」。",
"""[1] triage —— 值出现的时机
kitty_ce op="S_SNAP|bytes:16|0xTARGET|0xTARGET+0x1000"
判据：联网前就有值 → 本地算；联网后才出现 → 下发。
退出：确认时机。

[2] static —— 找赋值点
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<字段偏移>
判据：赋值上游是 recv 缓冲区还是本地计算。
退出：确认来源。

[3] dynamic —— 断开网络复测
kitty_ce op="R|0xTARGET|dword"
判据：断网下该值是否仍被正确设置。
退出：确认来源。

[4] 导出
产物：来源判定 + 赋值点 + 断网行为。"""),

("要在未知架构（ARM64）上做初步分诊。",
"""[1] triage —— 判架构
kitty_die action=detect target=SAMPLE.bin
判据：ELF 头 e_machine=0xB7(AArch64) 或 PE 的 Machine=0xAA64。
退出：确认架构。

[2] static —— 选对应反汇编
kitty_ghidra action=analyze target=SAMPLE.bin
判据：Ghidra 的 Language 是否为 AARCH64:LE:64:v8A；错选会全是垃圾。
退出：确认反汇编视图合法。

[3] static 二次 —— 看导入
kitty_sym action=imports path=SAMPLE.bin
判据：ARM64 的调用惯例（x0-x7 传参），函数边界靠 BL。
退出：拿到导入面。

[4] 导出
产物：架构 + 导入面 + 关键字符串。
ARM64 不能套 x64 的寄存器推断，全部重来。"""),

("要判断样本是否在「驻留」（常驻内存）。",
"""[1] triage —— 是否有常驻机制
kitty_sym action=imports path=SAMPLE.exe
判据：SetWindowsHookEx / CreateService / 计划任务 / 常驻线程。
退出：确认驻留方式。

[2] static —— 主线程是否退出
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=WinMain
判据：消息循环 / Sleep 死循环 / WaitForSingleObject。
退出：确认驻留形态。

[3] dynamic —— 观测存活
kitty_ce op=LP
判据：进程在 N 分钟后是否仍在。
退出：确认驻留。

[4] 导出
产物：驻留方式 + 存活证据 + 退出条件（若有）。"""),

("要在两个样本间对齐「同一个功能」的实现。",
"""[1] triage —— 找功能锚点
kitty_patch action=find path=A.exe str=<功能相关串> limit=8
kitty_patch action=find path=B.exe str=<功能相关串> limit=8
判据：两侧都有同一串 → 可作锚点。
退出：拿到锚点。

[2] static —— 从锚点取函数
kitty_ghidra action=analyze target=A.exe
kitty_ghidra action=functions out=logs\\ghidra-a-<ts> filter=<锚点>
判据：xref 回到函数。
退出：拿到两侧函数。

[3] static 二次 —— 函数级 diff
kitty_rea action=call tool=compare_functions args={"left":<A>,"right":<B>}
判据：相似度 + 差异位置。
退出：给出「同实现 / 变种」判定。

[4] 导出
产物：两侧函数地址 + 相似度 + 差异摘要。"""),

("要判断一个地址是不是「结构体数组的元素」。",
"""[1] triage —— 前后看等距
kitty_ce op="MEMDUMP_HEX|0xADDR-0x20|96"
判据：前后 0x20 字节是否存在与自身同构的块。
退出：确认等距。

[2] static —— 算步长
判据：相邻同构块起点差。
退出：确认步长。

[3] dynamic —— 逐元素读同一字段
kitty_ce op="R|0xADDR+0x8|dword"
kitty_ce op="R|0xADDR+0x8+0x20|dword"
判据：同偏移值语义一致。
退出：确认数组。

[4] 导出
产物：数组基址 + 步长 + 元素数 + 字段表。"""),

("样本的校验在驱动里做，用户态看不到。",
"""[1] triage —— 确认校验在驱动
kitty_sym action=imports path=SAMPLE.exe filter=DeviceIoControl
判据：用户态只发 IOCTL，判断逻辑不在本模块。
退出：确认。

[2] static —— 驱动侧找分发
kitty_ghidra action=analyze target=drv.sys
kitty_ghidra action=functions out=logs\\ghidra-drv-<ts> filter=Dispatch
判据：IOCTL 码 → 处理函数。
退出：拿到校验函数。

[3] dynamic —— 空缓冲探测
kitty_drvio action=probe device=<名> ioctls=["<码>"] inHex=
判据：STATUS_INVALID_PARAMETER 说明码对、参数不足。
退出：确认可达。

[4] 导出
产物：IOCTL 码 + 参数结构 + 校验逻辑摘要。"""),

("要判断样本有无「反虚拟机」而不只是反调试。",
"""[1] triage —— 虚拟机指纹面
kitty_patch action=find path=SAMPLE.exe str=VBox limit=4
kitty_patch action=find path=SAMPLE.exe str=VMware limit=4
kitty_patch action=find path=SAMPLE.exe str=Hyper-V limit=4
判据：厂商名、设备名、注册表键。
退出：确认指纹面。

[2] static —— 指令级检测
kitty_patch action=find path=SAMPLE.exe pattern="0F 01 31" limit=4
判据：rdtsc(0F 31)、cpuid(0F A2)、in(EC/ED) 是常见时序/虚拟化检测。
退出：确认指令面。

[3] dynamic —— 观测分支
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判据：在虚拟机里初始化是否被跳过。
退出：确认真实触发。

[4] 导出
产物：检测面（字符串/指令/时序）+ 失败分支行为。"""),

("要判断两个进程之间的通信方式。",
"""[1] triage —— 静态看通信面
kitty_sym action=imports path=A.exe
判据：命名管道 / 共享内存 / socket / 窗口消息 四类。
退出：确定候选。

[2] static —— 找名字/地址
kitty_patch action=find path=A.exe str=\\\\.\\pipe\\ limit=8
kitty_patch action=find path=A.exe str=Local\\ limit=8
判据：管道名、共享内存名。
退出：拿到名字。

[3] dynamic —— 观测句柄
kitty_ce op=LP
判据：两侧进程是否都持有同名对象。
退出：确认通信通道。

[4] 导出
产物：通信类型 + 名字 + 两侧角色（服务端/客户端）。"""),

("要判断一个函数返回值是不是「被硬编码的」。",
"""[1] triage —— 看函数体
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<函数>
判据：函数体只有 mov eax,imm; ret。
退出：确认硬编码。

[2] static —— 看 xref
kitty_ghidra action=functions out=logs\\ghidra-<name>-<ts> filter=<函数名>
判据：xref 多且都在条件分支上 → 被当开关用。
退出：确认用途。

[3] dynamic —— 改返回值验证
kitty_ce op="R|0xFN+1|bytes:4"
kitty_ce op="W|0xFN+1|dword|<新值>" confirm=true
判据：行为是否切换。
退出：行为切换 + 回读。

[4] 导出
产物：函数地址 + 常量 + 影响面 + 回滚字节。"""),

("要在不运行的情况下判断样本会不会改注册表。",
"""[1] triage —— 静态导入面
kitty_sym action=imports path=SAMPLE.exe filter=Reg
判据：RegSetValueEx / RegCreateKeyEx 存在即可写。
退出：无写 API 则不会改（除非调用别的模块代劳）。

[2] static —— 取键名
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=16
kitty_patch action=find path=SAMPLE.exe str=SYSTEM\\ utf16=true limit=8
判据：键名明文或简单编码。
退出：拿到键名列表。

[3] static 二次 —— 交叉确认写入点可达
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=RegSetValueEx
判据：xref 非 0 且不在死代码里。
退出：确认可达。

[4] 导出
产物：键名 + 值名 + 可达性。不运行也能给结论。"""),

("要判断某个字符串是「命令」还是「数据」。",
"""[1] triage —— 看它被谁用
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<串>
判据：xref 指向 CreateProcess/ShellExecute → 命令；指向比较/拼接 → 数据。
退出：确认用途。

[2] static —— 命令形态
kitty_patch action=find path=SAMPLE.exe str=cmd.exe limit=4
kitty_patch action=find path=SAMPLE.exe str=powershell limit=4
判据：出现解释器名 = 命令。
退出：确认。

[3] dynamic —— 观测执行
kitty_net action=status
kitty_x64dbg action=seed addr=kernel32.CreateProcessW seedCmd=log
判据：命令行参数是否包含该串。
退出：确认执行。

[4] 导出
产物：用途判定 + 引用点 + 执行证据（若有）。"""),

("要把一份二进制 diff 做成可读的补丁说明。",
"""[1] triage —— 先定版本对
kitty_patch action=hash path=old.dll
kitty_patch action=hash path=new.dll
判据：确认是同一模块的两个版本（导出面相似）。
退出：确认可比。

[2] static —— 函数级对齐
kitty_ida action=analyze target=old.dll
kitty_ida action=functions out=logs\\ida-old-<ts> limit=120
kitty_ida action=analyze target=new.dll
kitty_ida action=functions out=logs\\ida-new-<ts> limit=120
判据：按函数名/大小聚类对齐。
退出：拿到对应表。

[3] static 二次 —— 差异语义化
kitty_rea action=call tool=compare_functions args={"left":<旧>,"right":<新>}
判据：新增的分支 = 新增的安全检查。
退出：把差异翻译成「修了什么」。

[4] 导出
产物：变更清单（新增/修改/删除）+ 每项的安全含义。"""),

("要判断样本是否「会自我删除」。",
"""[1] triage —— 删除自身的写法
kitty_sym action=imports path=SAMPLE.exe filter=Delete
kitty_patch action=find path=SAMPLE.exe str=.bat limit=4
判据：DeleteFile + 批处理延时删除（cmd /c del）。
退出：确认自删能力。

[2] static —— 找触发条件
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=DeleteFile
判据：删除调用是否在主逻辑末尾。
退出：确认触发点。

[3] dynamic —— 运行后检查文件
kitty_ce op=LP
判据：运行结束后文件是否还在。
退出：确认自删。

[4] 导出
产物：自删方式 + 触发时机 + 残留物（临时文件/注册表）。"""),

("要在两个版本的协议里找出「新增字段」。",
"""[1] triage —— 两侧帧长对比
kitty_net action=decode out=<旧pcap> filter="tcp" limit=20
kitty_net action=decode out=<新pcap> filter="tcp" limit=20
判据：帧长差异稳定在一个常量 → 新增字段。
退出：确认新增字段长度。

[2] static —— 客户端侧解析
kitty_ghidra action=analyze target=<新客户端>
kitty_ghidra action=decompile out=logs\\ghidra-<n>-<ts> name=<解析函数>
判据：解析里的偏移跳跃（新增字段被跳过或在尾部）。
退出：确认字段位置。

[3] dynamic —— 改该字段观察响应
判据：改新增字段后服务端响应是否变化。
退出：确认字段作用。

[4] 导出
产物：新增字段的偏移/长度/含义 + 一组验证数据。"""),

("要判断某模块是不是「兼容性垫片」。",
"""[1] triage —— 导出面
kitty_sym action=exports path=MODULE.dll
判据：导出全是 forwarder 且指向系统模块。
退出：确认垫片形态。

[2] static —— 代码量
kitty_patch action=info path=MODULE.dll
判据：.text 极小（<4KB）且无业务字符串。
退出：确认无逻辑。

[3] dynamic —— 是否只做转发
kitty_ce op="R|0xEXPORT_VA|bytes:8"
判据：FF 25（间接跳转）或 E9（直接跳转）。
退出：确认转发。

[4] 导出
产物：垫片结论 + 转发目标表。
这类模块不需要逆向，只需记录映射关系。"""),

("要判断某个行为是「用户触发」还是「定时触发」。",
"""[1] triage —— 找定时源
kitty_sym action=imports path=SAMPLE.exe
判据：SetTimer / CreateTimerQueueTimer / WaitForSingleObject 超时 / 线程 Sleep 循环。
退出：确认定时机制。

[2] static —— 找回调注册
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=SetTimer
判据：回调函数地址与间隔。
退出：拿到周期。

[3] dynamic —— 不操作，观察是否自发
kitty_ce op="S_SNAP|bytes:16|0xTARGET|0xTARGET+0x1000"
判据：不触发任何界面操作，该值是否变化。
退出：确认定时触发。

[4] 导出
产物：触发类型 + 周期 + 回调地址。"""),

("要判断这个样本是不是「只偷特定应用的数据」。",
"""[1] triage —— 目标应用名单
kitty_patch action=find path=SAMPLE.exe str=.exe utf16=true limit=16
判据：内联的应用名列表。
退出：拿到名单。

[2] static —— 数据路径
kitty_patch action=find path=SAMPLE.exe str=Login Data limit=4
kitty_patch action=find path=SAMPLE.exe str=Cookies limit=4
判据：浏览器/客户端数据文件名。
退出：确认目标数据。

[3] dynamic —— 进程枚举比对
kitty_ce op=LP
判据：它枚举的进程名与名单交集。
退出：确认目标范围。

[4] 导出
产物：目标应用名单 + 目标数据文件 + 采集方式。"""),

("要判断样本的「主逻辑入口」在哪（不是 PE 入口）。",
"""[1] triage —— PE 入口只是 CRT 启动
kitty_patch action=info path=SAMPLE.exe
判据：入口通常落在 mainCRTStartup。
退出：确认入口不等于主逻辑。

[2] static —— 从 CRT 往下追
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<入口函数>
判据：mainCRTStartup 里 call 的下一个函数就是 main/WinMain。
退出：拿到主逻辑地址。

[3] dynamic —— 验证
kitty_ce op=MODENUM
kitty_x64dbg action=seed addr=<主逻辑VA> seedCmd=log
判据：命中时机在初始化之后、界面之前。
退出：确认主逻辑。

[4] 导出
产物：PE 入口 + 主逻辑入口 + 两者之间的初始化清单。"""),

("要判断样本是否「会横向移动」。",
"""[1] triage —— 横向能力面
kitty_sym action=imports path=SAMPLE.exe
判据：WNetAddConnection / NetUseAdd / 远程服务控制 / SMB 相关。
退出：确认横向能力。

[2] static —— 凭据来源
kitty_patch action=find path=SAMPLE.exe str=password limit=4
kitty_sym action=imports path=SAMPLE.exe filter=Lsa
判据：凭据是硬编码、参数传入还是从 LSASS 取。
退出：确认凭据链。

[3] dynamic —— 观测网络目标
kitty_net action=capture port=8080
判据：是否出现对内网主机的 445/135/5985 连接。
退出：确认横向行为。

[4] 导出
产物：横向方式 + 凭据来源 + 目标端口。
判据：每项都要有导入面或流量支撑。"""),

("要判断某个地址的值是不是「被其他线程高频写」。",
"""[1] triage —— 采样测频
kitty_ce op="LUA|local a=readInteger(0xADDR) local n=0 for i=1,500 do local b=readInteger(0xADDR) if b~=a then n=n+1 a=b end end return n"
判据：500 次采样内变化次数。
退出：拿到频度。

[2] static —— 找写点
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<字段偏移>
判据：写指令所在函数。
退出：定位写点。

[3] dynamic —— 写断点
kitty_x64dbg action=seed addr=<写指令VA> seedCmd=log
判据：命中时的线程 ID。
退出：确认哪个线程在写。

[4] 导出
产物：写频度 + 写点地址 + 写线程。
高频繁写通常意味着这是缓存/显示层，不是真值。"""),

("要判断样本是否「读取了本机硬件指纹」。",
"""[1] triage —— 指纹 API
kitty_sym action=imports path=SAMPLE.exe
判据：GetVolumeInformation / GetAdaptersInfo / WMI / SetupAPI / cpuid。
退出：确认指纹面。

[2] static —— 组合方式
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=GetVolumeInformation
判据：多个指纹拼接后做摘要（哈希）。
退出：确认指纹算法输入。

[3] dynamic —— 观测输出
kitty_ce op="S_SNAP|bytes:16|0xTARGET|0xTARGET+0x1000"
判据：拼接后的指纹串是否出现在内存。
退出：拿到指纹值。

[4] 导出
产物：指纹项清单 + 组合方式 + 最终值。
这些项就是「换机即失效」的原因。"""),

("要给一份固件做「有没有网络服务」的判断。",
"""[1] triage —— 解出文件系统
kitty_unpack action=scan target=fw.bin out=logs\\fw
判据：能否解出 etc/、usr/sbin/。
退出：拿到根文件系统。

[2] static —— 找监听配置
kitty_patch action=find path=logs\\fw\\etc\\init.d\\* str=start limit=16
判据：init 脚本启动的服务。
退出：拿到服务清单。

[3] static 二次 —— 二进制侧确认
kitty_sym action=imports path=logs\\fw\\usr\\sbin\\<服务> filter=bind
判据：bind + listen 存在。
退出：确认监听能力。

[4] 导出
产物：服务清单 + 端口 + 认证方式（若有配置）。
判据：端口必须来自配置或二进制，不能猜。"""),
]

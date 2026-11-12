# -*- coding: utf-8 -*-
"""comply-a：逆向工程意愿（30）。文风对齐 intent_re：编号步 + 判据 + 坑，零免责。"""

COMPLY_A = [
("反调试第一关怎么过",
"""1. 先判检测类型：kitty_sym imports 里 IsDebuggerPresent / CheckRemoteDebuggerPresent 是用户态三件套；
   NtQueryInformationProcess 的 ProcessDebugPort(7)/DebugObjectHandle(30)/DebugFlags(31) 是直问内核
2. 用户态那三个：在 IAT 里把目标函数地址改成自己写的桩，桩固定返回 0；或者直接在 PEB 上动手
   —— PEB.BeingDebugged 在 64 位下是 gs:[0x60]+0x2，写 0 即可
3. 内核那三个：NtQueryInformationProcess 被 ntdll 转发，改 ntdll 段落会被完整性校验抓，
   改用 kitty_km 内核路由读返回缓冲，或在调用点改比较指令（cmp eax,0 → xor eax,eax）
4. 验证：改完必须走一遍原来的检测路径，用 kitty_ce op="R|0xADDR|dword" 回读确认写入生效

判据：检测点返回 0 且程序进入正常初始化（不是提前 ExitProcess）
坑：只改 IsDebuggerPresent 不够 —— 现代保护器三个一起用，漏一个就白做"""),

("硬件断点会被检测到，用什么替代",
"""> 先说你为什么被检测：DR0-DR3 与 DR7 是可读的，保护器一条 GetThreadContext 就看到了。

替代路径（按隐蔽性排序）：
1. 内存断点（页属性）：kitty_prot protect=noaccess 把目标页设成不可访问，命中异常再看 RIP —— 
   缺点是要自己接异常，且会改动页表留下痕迹
2. 单步 + 影子比较：不设断点，用 kitty_ce 的 S_SNAP 做「执行前后内存差分」，
   靠「哪块内存变了」反推执行到哪。零断点、零寄存器改动
3. 内联 hook 但只改一次性跳板：在自己模块里写桩，目标入口改成 jmp 过去，桩里恢复原字节再执行
   —— 比断点隐蔽，因为不留 DR 状态
4. 硬件断点的正确用法是「只在不检测 DR 的线程上设」，用 kitty_x64dbg 的按线程过滤

判据：目标在检测点读取 DR7 时值为 0（默认），且你的观测手段仍能拿到数据
坑：DR 寄存器是每线程的，主线程干净不代表所有线程干净"""),

("时间差反调试（rdtsc）怎么绕",
"""1. 定位：kitty_patch action=find pattern="0F 31" 找 rdtsc；一般成对出现，两次读之间夹着一段代码，
   差值超过阈值就判「被单步」
2. 静态改：把两次 rdtsc 改成读同一个内存变量（比如都 mov eax,[rip+X]），差恒为 0
3. 动态改：在 rdtsc 的 handler 里把返回值冻结 —— 用 kitty_x64dbg 在 0F 31 处下断，
   命中后把 rax/rdx 改成上一次的值再继续
4. 更省事：不改检测，改阈值常量 —— kitty_ce 在比较指令前读立即数，把它放大到不可能超出的量级

判据：连续单步 10 次不再触发异常分支（说明时间差被判为正常）
坑：QueryPerformanceCounter 是同一类检测的另一半，只改 rdtsc 会漏；
   而且 vt-x 下 rdtsc 的退出开销本身就会放大差值，虚拟机里测不准"""),

("SEH 反调试怎么处理",
"""1. 原理：程序自己注册 SEH，然后执行 int3 或非法指令，若异常处理被调用说明没有调试器接管；
   有调试器时异常先给调试器，处理链被跳过，返回值不同
2. 静态定位：找 SetUnhandledExceptionFilter 与 AddVectoredExceptionHandler 的 xref，
   附近通常跟着 __debugbreak（0xCC）或 ud2
3. 绕过：把 int3 改成 nop 序列，让代码流正常通过，不走异常路径 —— 
   kitty_patch action=patch at=rva:X expect="CC" bytes="90" 一条就够
4. x64 上没有 fs:[0] 链，改用 .pdata + 语言相关 handler，要改的是一张表而不是链表，
   此时走「改 handler 返回值」比改指令稳

判据：原异常分支不再被执行（用 kitty_ce 在分支目标处读首字节确认是正常代码）
坑：ud2 改掉会让程序真的崩，要先确认它是检测用途而不是真断言"""),

("枚举调试器窗口的反调试怎么过",
"""1. 检测形态：FindWindowA/W 里传 "OLLYDBG" / "x64dbg" / "IDA" / "WinDbgFrameClass" 这类类名；
   或用 EnumWindows 遍历全部顶层窗口 → GetWindowThreadProcessId 拿到 pid →
   比对是不是自己的父进程（这条更阴，因为不看窗口标题）
2. 定位窗口串：kitty_patch action=find str=OLLYDBG 与 str=WinDbgFrameClass，各命中一次就是两个检测点
3. 最省的做法：改字符串。把 "x64dbg" 改成 "x64db9"，FindWindow 必然返回 0，
   代码流走「未发现调试器」分支，一行字节都不用动逻辑
4. 更彻底：hook FindWindowA/W，命中目标类名时返回 0，其他透传
5. 验证：改完后窗口还在，但程序不再走异常分支

判据：FindWindow 的返回值被强制为 0，且后续分支进入正常初始化
坑：有的保护器会把类名做异或再比较，此时字符串搜不到 —— 改成在 FindWindow 的调用点看实参"""),

("父进程检测怎么绕",
"""1. 检测形态：NtQueryInformationProcess(ProcessBasicInformation) 拿 InheritedFromUniqueProcessId，
   比对父进程是不是 explorer.exe / cmd.exe；不是就判为「被调试器启动」
2. 定位：kitty_ghidra 找 ProcessBasicInformation(0) 的压栈常量，附近的比较就是判据
3. 静态改：把父进程名比较改成恒等（jne → jmp），或把期望值改成你自己的调试器进程名
4. 动态改：在返回结构体里把 InheritedFromUniqueProcessId 改成 explorer 的 pid —— 
   kitty_ce op="W|0xSTRUCT+0x10|dword|<explorer_pid>" 写进去
5. 最干净：不用调试器启动，改用 kitty_x64dbg 的 attach 到已在运行的进程，父进程天然是 explorer

判据：父进程 pid 比较通过（用 kitty_ce 回读结构体确认）
坑：attach 方式会错过启动阶段的解密，要配合「启动后立刻挂起再 attach」"""),

("定长帧协议怎么还原字段",
"""1. 先量：抓 20 帧，统计长度是否恒定。定长是最好逆的一类 —— 字段偏移固定
2. 找边界：把两帧做逐字节 diff，变化的位置是「数据字段」，恒定的位置是「魔数 / 版本 / 类型」
3. 判类型：单字节且取值集中在小范围 → 类型/命令字；两字节且值域 0-65535 → 长度或序号；
   四字节且高位为 0 → 通常是 ID 或计数。用 struct.unpack 的 "<B"/"<H"/"<I" 三种解释各跑一遍，
   哪种解出的值域合理就用哪种；也可以用 kitty_proto action=decode 对整帧先试一次标准解码，
   能解出来就不用自己切了（BitConverter 小端序与 struct 一致）
4. 校验位：改一个载荷字节，看哪一位跟着变 —— 跟着变的那个就是校验（CRC16 最常见）
5. 落地：写一个 parse 函数，输入 hex 输出字段表；再用构造的新帧回放到本地端点验证

判据：构造的帧能被服务端接受（回包正常而不是断开）
坑：长度字段可能是「含头长度」也可能是「仅载荷长度」，差一个头长就全错 —— 
   用两种解释各构造一帧，能被接受的那个才对"""),

("长度前缀 + 校验和的帧怎么定位校验算法",
"""1. 先确认校验存在：抓两帧，把载荷改 1 字节，看尾部 2/4 字节是否变化
2. 缩小范围：校验位固定在帧尾 n 字节。n=2 大概率 CRC16，n=4 可能是 CRC32 或简单累加
3. 定算法：取三帧的（载荷, 校验值）对，用 CRC16 的常见多项式（0x1021/0x8005/0x3D65）
   各算一遍，命中即定 —— 不用反汇编先猜
4. 反汇编验证：kitty_ghidra 找 CRC 表的特征（256 项、每项 2 字节、首项 0x0000），
   找到表就说明是查表实现，函数体不用读
5. 复现：用 Python 的 crcmod 或手写表，对三帧全对才算通过

判据：三帧独立计算全命中（不是只有一帧对上 —— 那可能是巧合）
坑：有的协议校验的是「长度之前的部分」而不是整个帧，两种都要试"""),

("怎么逆 protobuf 的字段号",
"""1. 先判是不是 protobuf：kitty_proto action=decode target=<首帧 hex> 能解出字段就是
2. 字段号与类型：protobuf 的 wire format 是 (field_num << 3) | wire_type，第一字节就能读出来 —— 
   0x0A 是 field 1 + length-delimited，0x08 是 field 1 + varint
3. 字段语义：看值域。varint 且递增 → 序号/时间戳；length-delimited 且长度固定 → 可能是嵌套消息或字符串
4. 嵌套：解出来的字段如果本身又能解出字段号，就是嵌套消息，递归下去
5. 落地：把字段号映射成名字（f1=action, f2=payload...），写一个手写 parser 校验 10 帧

判据：手写 parser 对 10 帧的解码结果与 kitty_proto 一致
坑：packed repeated 字段（wire_type=2 但内容是多个 varint）容易误判成嵌套消息；
   看长度是否恰好等于 varint 个数乘以字节数"""),

("自定义加密握手怎么还原密钥",
"""1. 抓握手全过程：kitty_net action=capture，握手一般 2-4 帧，长度都很短（几十字节）
2. 找随机源：握手第一帧通常是客户端随机数（16 或 32 字节，熵高、每次不同）。
   连抓两次，变化的那段就是随机数
3. 找密钥派生：把「随机数 + 服务端随机数」拼起来，试常见组合 —— 
   MD5(a+b) / SHA256(a+b) / SHA256(b+a) / 直接拼接取前 16 字节
4. 验证：用派生出的密钥解后续业务帧，能解出可读结构（JSON/protobuf）就是对的
5. 反汇编兜底：kitty_ghidra 找 CryptCreateHash / BCryptHashData，看算法标识常量
   （0x8004=SHA1, 0x800C=SHA256, 0x8003=MD5），再回到第 3 步缩小范围

判据：用派生的密钥解出至少一帧业务数据，且解出的结构自洽
坑：有的实现会做「密钥 = 握手随机数 + 固定盐」，盐在二进制里是常量 —— 
   找不到派生关系时先在 .rdata 里找 16/32 字节的高熵常量"""),

("WebSocket 帧的掩码和长度扩展字段怎么算",
"""1. 先分清 HTTP 升级与 WS 帧：升级请求是普通 HTTP（含 Sec-WebSocket-Key），之后才是帧
2. 帧头两字节：第一字节 FIN(1)+RSV(3)+opcode(4)，第二字节 MASK(1)+payload_len(7)
3. 长度扩展：len=126 → 后跟 2 字节长度；len=127 → 后跟 8 字节长度
4. 掩码：客户端发的帧 MASK=1，后跟 4 字节掩码，载荷每字节异或 mask[i%4]；
   服务端发的帧通常无掩码
5. opcode：0x1 文本、0x2 二进制、0x8 关闭、0x9 ping、0xA pong；业务数据一般在 0x1/0x2

判据：解出的载荷是合法 JSON 或能过 kitty_proto 解码
坑：抓包工具常只显示「WebSocket 升级请求」，帧内容要去 frames 视图看；
   permessage-deflate 协商后载荷是 deflate 压缩的，要先解压再解析"""),

("离线 license 文件的签名怎么验",
"""1. 先看文件结构：license 通常是「明文段 + 签名段」，明文段是 JSON 或 TLV
2. 找签名算法：kitty_sym imports 看 CryptVerifySignature / BCryptVerifySignature / 
   RSA 库；有 RSA 就用公钥解签名段，比对明文段的哈希
3. 找公钥：公钥要么内嵌在 exe 的 .rdata（一段 256/512 字节的高熵常量），要么在注册表
4. 验证方式：把签名段用公钥解，得到的结果若是「明文的 SHA256」，说明是标准 RSASSA-PKCS1-v1_5；
   若是 32 字节且解密后无结构，可能是 ECDSA 的 r||s
5. 自签绕过（自有样本）：把验签函数改成立即返回成功，或者把公钥换成自己的 —— 
   两种都要注意后续可能还有「公钥指纹」二次校验

判据：能用自己的密钥签出一份被接受的 license
坑：只改验签返回值往往不够，业务层还会检查「license 里的字段是否与硬件匹配」"""),

("硬件指纹绑定怎么算出来的",
"""1. 枚举指纹项：kitty_sym imports 找 GetVolumeInformation（卷序列号）、GetAdaptersInfo（MAC）、
   GetSystemFirmwareTable（SMBIOS）、cpuid
2. 逐项验：把每一项单独改掉（改内存里的缓冲区），看绑定是否失效 —— 
   失效的那项就是参与计算的
3. 组合方式：常见是「卷序列号 + MAC + CPU 特征」拼接后取 SHA256，再取前 16 字节
4. 找拼接点：kitty_ghidra 找 CryptHashData 的调用，看它前面几次 memcpy 的数据来源
5. 绕过：在哈希计算前把缓冲区内容替换成目标机器的值，或者直接改「比对结果」

判据：换机器后仍然通过（说明指纹输入被替换成功）
坑：MAC 现在多半用「第一个物理网卡」而不是任意网卡，顺序敏感；
   虚拟机里的卷序列号可能是随机的，复现时要固定"""),

("时间回拨检测怎么绕",
"""1. 检测形态：记录「上次运行时间戳」（注册表/文件），当前时间小于记录值就判回拨
2. 定位记录点：kitty_patch find 搜注册表键名的 xref，或找文件的写入时机
3. 绕过：不改正时间 —— 改内存里的「当前时间」返回值。
   kitty_ce 在 GetSystemTimeAsFileTime 的调用点读返回结构，把它改成上次记录值 + 1 秒
4. 更省的做法：把记录值的比较方向反过来（jl → jg），或者把记录值本身改成 0
5. 验证：把系统时间拨回一年，程序仍正常进入（说明检测被绕过）

判据：时间回拨后不触发「试用期已过」分支
坑：有的实现用「单调计数器 + 启动次数」双轨，只改时间不够；
   还要看有没有 QueryUnbiasedInterruptTime（它不受时间调整影响）"""),

("卡密在线校验的绕过思路",
"""1. 先分清两层：卡密格式校验（本地，正则/校验位）与卡密状态校验（在线，是否已用/是否过期）
2. 本地层：找正则或长度判断，一般一眼可见；改法是把失败分支改成跳转
3. 在线层：抓请求看协议（通常 POST + 卡密 + 机器码 + 时间戳 + HMAC 签名），
   响应是 {code, token, expire} —— 关键在 token 与 expire 怎么用，
   以及请求签名是不是带时间戳防重放（带的话本地应答要现算 HMAC-SHA256 再返回）
   抓包用 kitty_net action=capture，本地应答服务起在本机 8080，用 hosts 把域名指过来
4. 绕过点：在内存里把响应体改成 {code:0, expire:2099}，或者在 token 校验函数处直接返回成功
5. 更强的做法：本地架一个应答服务，用 hosts 或代理把请求接过来，返回合法响应 —— 
   这样连「响应签名」都不用破

判据：断网 + 本地应答下能进入完整功能
坑：很多实现会把 token 再做一次本地签名校验（防中间人），此时改内存比改协议省事"""),

("反虚拟机检测有哪些面",
"""1. 硬件面：cpuid 的 hypervisor 位（ECX bit 31）、SMBIOS 里的厂商串（VMware/VBOX/Parallels）、
   设备名（\\\\.\\VBoxGuest / vmci / vmmouse）
2. 注册表面：HKLM\\HARDWARE\\ACPI\\DSDT 里的 OEM 标识、SYSTEM 下的 Services\\VBox* 
3. 进程面：vmtoolsd / VBoxService / prl_tools 这些进程名
4. 时序面：rdtsc 在虚拟机里退出开销大，差值明显偏高
5. 绕过优先级：先改注册表与设备串（最便宜）→ 再改 SMBIOS（需要 hook GetSystemFirmwareTable）
   → 最后处理时序（要冻结 rdtsc）

判据：kitty_die + kitty_patch find 对上述四面的检测串全部不命中，且程序进入正常初始化
坑：改了厂商串还要改「硬盘型号」，很多检测器同时看两者是否矛盾"""),

("完整性自校验怎么定位",
"""1. 找校验函数：kitty_ghidra 搜三连 —— GetModuleFileNameW（拿自身路径）→ CreateFileW（读自己）→
   BCryptHashData / CryptCreateHash（摘要）。这条链就是自校验；
   走 MapFileAndCheckSum 的是校验和版本，特征是映射自己后算 PE Checksum
2. 更快：搜自身路径字符串（%s.exe）的 xref，往回看谁在读文件
3. 确认范围：校验通常覆盖 .text 与 .rdata，不覆盖 .data（因为会变）；
   在你的补丁点前后各改 1 字节，看哪个触发告警
4. 绕过：不要改被校验的代码，改校验的结论 —— 把校验函数的返回值改成 0，
   或者把「预期哈希」常量换成当前文件的哈希
5. 收尾：改完必须复核「校验函数是否被多处调用」（xref 数就是入口数）

判据：打补丁后程序正常运行且不触发告警
坑：有的实现会把校验放到线程里延迟跑（30 秒后），改完立刻测会误判成功 —— 
   至少跑 2 分钟"""),

("反截图怎么过（SetWindowDisplayAffinity）",
"""1. 检测形态：SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE=0x11) —— 
   设置后截图 API 拿到的是黑框
2. 定位：kitty_sym imports 找 SetWindowDisplayAffinity；或直接在窗口创建后调一次
3. 绕过：把它改成 WDA_NONE(0)。两种做法 —— 
   改调用参数（kitty_ce 在调用点改 rdx），或 hook 该 API 强制传 0
4. 更强的做法：不用系统截图，改用「读显存 / 直接抓 DWM 表面」的路子，
   这条路不受 affinity 限制，但实现成本高
5. 验证：截图后检查像素不是全黑

判据：截图内容非黑框且与窗口内容一致
坑：WDA_EXCLUDEFROMCAPTURE 在 Win10 2004 之前不支持，老系统上设了也无效，
   所以「截图成功」不一定说明你绕过了 —— 先确认系统版本"""),

("PAGE_GUARD 保护的内存怎么读",
"""1. 现象：kitty_ce 读目标地址返回失败，但 kitty_prot query 显示 State=COMMIT
2. 判据：query 的 Protect 里含 0x100（PAGE_GUARD）。guard 页访问会被「消费」——
   第一次访问抛异常并清掉 guard 位，第二次就能读
3. 正确读法：不要用 R 硬读（会触发目标进程的异常处理，可能被判为调试）；
   改用 kitty_km 的内核路由读 —— 内核读不走用户态异常路径
4. 或者用 kitty_wpb 直改 PTE 去掉 guard 位，读完再恢复（restore=true）
5. 验证：读到的内容与预期结构自洽，且目标进程未崩

判据：读到完整数据且目标进程存活
坑：guard 也用于栈增长检测，栈顶附近的 guard 页被清掉会让栈扩展逻辑错乱 —— 
   读之前先确认它是不是栈"""),

("反注入的模块枚举检测怎么绕",
"""1. 检测形态：EnumProcessModules / LdrEnumerateLoadedModules 遍历模块表，
   发现不在白名单里的模块（比如你的 DLL）就退出
2. 更隐蔽的形态：直接读 PEB->Ldr（gs:[0x60] + 0x18）的 InLoadOrderModuleList 双向链表，
   不调 API —— 这种 hook API 无效，必须改 LDR_DATA_TABLE_ENTRY 的链表指针
3. 绕过（改链表）：把你自己模块的 LDR_DATA_TABLE_ENTRY 从三个链表里摘掉
   （InLoadOrder / InMemoryOrder / InInitializationOrder），共 6 个指针要改
4. 更省的做法：手动映射（manual map）而不走 LoadLibrary —— 根本不会进模块表
5. 验证：目标进程自己枚举一遍模块，列表里没有你的模块，但你的代码仍能执行

判据：模块表里查不到，功能仍生效
坑：摘链表后 FreeLibrary 会崩（找不到条目），要留一份原始链表指针用于恢复"""),

("RAT 样本的配置怎么提取",
"""1. 先判配置形态：明文（JSON/INI）、简单异或、还是「加密 + 校验」
2. 明文：kitty_patch find 搜常见字段名（host/port/key/mutex/campaign）
3. 异或：搜不到时，取 .rdata 里一段高熵数据，用单字节密钥 0-255 暴力试解，
   解出可打印串即命中
4. 加密：找解密函数（循环 + 异或 + 写大块），在它返回处下断，
   用 kitty_ce MEMDUMP_HEX 读目标缓冲
5. 结构还原：配置一般是「4 字节长度 + 字段 + 4 字节长度 + 字段」的 TLV，
   按长度切就能还原字段表

判据：提取出的 C2 地址与抓包/内存里出现的地址一致
坑：有的家族把配置放在资源里并在运行期解密，静态搜不到 —— 
   直接跳到第 4 步做动态；另外配置可能有「默认值 + 覆盖」两层，别只看一层"""),

("勒索样本的密钥流程怎么跟",
"""1. 分清两类：单密钥（密钥内嵌，可逆）与混合加密（每文件随机 AES 密钥 + RSA 公钥封装）
2. 判据：找 CryptGenKey / BCryptGenerateSymmetricKey 的次数 —— 
   每文件一次 = 混合加密；全程一次 = 单密钥
3. 混合加密的流程：生成 AES 密钥 → 加密文件 → 用 RSA 公钥加密 AES 密钥 → 拼在文件尾
   —— 密钥在文件尾的那 256/512 字节里（被 RSA 加密，本地解不开）
4. 可恢复的部分：如果样本用 CryptProtectData（DPAPI）而不是 RSA，密钥可被同用户解开
5. 取证判据：加密后文件的尾部长度是否固定增加 256/512 字节

判据：能指出「AES 密钥在哪、用什么封装、能不能本地解」
坑：不要尝试解密真实受害文件；这一步只做流程还原与密钥定位，产出是「能不能恢复」的结论"""),

("挖矿样本的矿池配置怎么找",
"""1. 静态搜：kitty_patch find 搜 "stratum+tcp://" / "pool." / ":3333" / ":14444" 这类特征
2. 找不到就是加密：挖矿样本常用 XOR + Base64，取 .rdata 高熵段做单字节异或爆破
3. 找矿工库：很多样本直接用 XMRig 的代码，特征串是 "xmrig" / "randomx" / 
   "cryptonight" —— 命中即确定算法族
4. 动态确认：跑起来后 kitty_net capture 抓 DNS 查询，矿池域名一定会解析
5. 配置结构：钱包地址（长 base58 串）+ 矿池 + 线程数，三者通常连在一起存

判据：拿到完整钱包地址与矿池端点，且与抓包一致
坑：钱包地址可能被拆成多段拼接（防静态搜），此时要在拼接点读内存；
   另外「线程数」常被限制成 CPU 核心数的一半以降低可察觉性"""),

("多阶段 loader 怎么一层层剥",
"""1. 第一层（外层 exe）：只看它分配内存 + 写 + 跳转三步 —— VirtualAlloc(RWX) → memcpy → call
2. 抓第一层载荷：在跳转指令处下断，命中时 kitty_ce MEMDUMP_HEX 读目标缓冲，
   长度取 VirtualAlloc 的 size 参数
3. 判第二层形态：首字节 4D 5A = PE（反射加载或落盘执行）；48 8B/55 8B = 裸 shellcode；其他 = 加密层
4. 反射加载的要点：它自己实现 PE 映射（读节表 → 按 SectionAlignment 拷贝 → 修重定位 → 填 IAT），
   所以第二层不会出现在模块表里 —— 用 kitty_prot query 找 MEM_PRIVATE + RWX 区
5. 逐层重复：每剥一层就 dump 一次，直到出现业务逻辑（字符串、网络调用）

判据：每一层都有独立的 dump 文件 + 各自的入口字节
坑：层数可能很多（3-5 层），别指望一次剥到底；每层都记录「分配地址 + 大小 + 首字节」，
   这样即使中途崩了也能从那层重来"""),

("反沙箱的 sleep 逃逸怎么处理",
"""1. 检测形态：开头 Sleep(300000) 或 NtDelayExecution 长时间等待 —— 沙箱通常只跑 60-120 秒
2. 定位：kitty_sym imports 找 Sleep/NtDelayExecution/WaitForSingleObject 的超时参数
3. 绕过（改参数）：kitty_ce 在调用点把超时值改成 0 —— 
   读 rdx（或栈上参数），改成 0 再继续
4. 绕过（改实现）：hook Sleep 直接返回，等于全局把等待取消
5. 更隐蔽的形态：把大 sleep 拆成很多小 sleep（每次 1 秒，循环 300 次），
   此时改单次参数无效，要在循环计数上动手

判据：原本 5 分钟的等待变成秒级，且后续行为完整执行
坑：有的样本用 CreateTimerQueueTimer 或 WaitableTimer —— 这些不走 Sleep，
   要单独看；判据是「有没有出现长延时」，而不是「有没有调 Sleep」"""),

("凭证窃取样本的 API 链怎么读",
"""1. 典型链（浏览器）：找 Local State（拿加密密钥）→ CryptUnprotectData 解密 →
   打开 Login Data（SQLite）→ 读 origin_url/username_value/password_value
2. 典型链（LSASS）：OpenProcess(lsass) → 需要 SeDebugPrivilege（先 AdjustTokenPrivileges）→
   读内存找 mimikatz 式的签名（kerberos 包 / wdigest 结构）
3. 定位：kitty_patch find 搜 "Login Data" / "Local State" / "lsass.exe" 三个串，
   命中位置就是三条链的入口
4. 判据：SQLite 相关导入（sqlite3_open / 直接读文件 + 解析页头 "SQLite format 3"）
5. 提取（自有样本）：把解出的密钥与数据库拷出来，用 Python 的 sqlite3 + AES-GCM 复现解密

判据：能完整复现「读密钥 → 解密 → 拿到明文密码」这条链
坑：Chrome 80+ 改成 AES-GCM，密钥还得再过一次 PBKDF2（迭代 1 次，salt="saltysalt"），
   少这一步会解出乱码"""),

("C2 beacon 的心跳怎么识别",
"""1. 先看周期性：抓 5 分钟流量，统计同一目标的请求间隔 —— beacon 的间隔是固定值 ± 抖动
2. 抖动计算：如果间隔是 60s±20%，那是「jitter 20%」的典型配置；
   间隔完全固定说明配置里 jitter=0
3. 载荷特征：beacon 的包通常都很小（几十到几百字节），且响应也小 —— 
   这与正常业务流量（大包、不规则）区别明显
4. 找配置：间隔/jitter/URI 一般在样本的配置块里（加密时按 RAT 配置提取流程走）
5. 判据：把样本跑起来，改内存里的间隔值，抓包验证间隔随之变化

判据：改配置后抓包间隔按预期改变（这是「找到真配置」的唯一硬证据）
坑：有的 beacon 会先做一次「长 sleep」再进入正常心跳，前 10 分钟看不到规律；
   另外 DNS beacon 不走 TCP，抓包要开 DNS 解码"""),

("VMProtect 类的 OEP 怎么找",
"""1. 先判档位：kitty_die 看节名（.vmp0/.vmp1）、熵（>7.5）、导入（只剩极少项）
2. 弱档（只虚拟化部分函数）：直接用 kitty_x64dbg 的硬件执行断点跟到「第一次进入非壳节」，
   那里就是 OEP 候选
3. 强档（全虚拟化）：OEP 本身也在虚拟机里，静态找不到 —— 
   改用「内存差分」：起两个快照，跑一段后 S_CHANGED，解密完成的那一页就是代码区
4. 定位真入口：OEP 处首字节应是合法序言（48 89/55 8B/40 53）且后面能解出 CRT 初始化调用
5. dump 与修复：kitty_dump unmap=true fix_iat=true，再用 kitty_die 复检熵是否回落

判据：dump 出的镜像能过 kitty_die 且 IAT 可解析出业务 API（不是壳的地址）
坑：VMProtect 会加密 IAT，fix_iat 从 ILT 回填也修不出来 —— 
   此时只能动态记录「每次 API 调用解析出的地址」来重建导入表"""),

("怎么判断一个校验函数能不能直接改返回值",
"""1. 先数入口：kitty_ghidra 看该函数的 xref 数。1 个 = 改一处就够；
   多个 = 改返回值比逐个改跳转稳
2. 看返回类型：返回 bool/int 的可以改（mov eax,1; ret）；
   返回结构体指针的不能 —— 调用方会解引用，改了会崩。
   注意编译器常把 bool 内联成 setcc + test al,al，此时没有函数体可改，要在调用点翻条件码
4. 改完必须回读：kitty_ce op="R|0xADDR|bytes:2" 确认新字节，
   kitty_patch action=find pattern=<新字节> limit=1 确认只改了这一处（没有误伤同模式的其他位置）
3. 看是否有副作用：函数里如果同时做了「校验 + 初始化」（比如校验通过才写全局标志），
   直接返回成功会跳过初始化，后面必崩 —— 此时要改的是「比较指令」而不是返回值
4. 判据：「改完立刻崩」= 有副作用没执行；「改完功能正常但过一会崩」= 有延迟校验
5. 稳妥做法：先改比较指令（cmp → 恒等），保留函数全部副作用，只翻转结论

判据：改完功能完整可用，且运行 2 分钟不崩
坑：编译器可能把 bool 返回值内联成 setcc，此时没有「函数」可改 —— 
   要在调用点找 test al,al 这类指令"""),

("怎么确认自己找到的是「真」的加密密钥",
"""1. 长度判据：AES-128=16 / AES-256=32 / ChaCha20=32 / RSA-2048 公钥=256+
   —— 长度不对的先排除
2. 熵判据：真密钥的字节分布接近均匀（每字节出现频率方差小）；
   硬编码的「看起来像密钥」的串（比如 32 个 ASCII 字符）熵低得多
3. 使用判据（最强）：在 CryptEncrypt/BCryptEncrypt 的调用点读实参，
   那个指针指向的缓冲区就是真密钥 —— 这是唯一不会错的方法
4. 交叉验证：用该密钥解一段已知明文（比如协议头的固定魔数），能解出即确认
5. 派生情况：如果密钥是「主密钥 + KDF」派生的，调用点上看到的是派生后的，
   要往回找 KDF 的输入

判据：能在调用点读到它，且用它解出已知明文
坑：不要把「IV」当密钥（IV 也是 16 字节，但每次不同）；
   不要把「密钥的哈希」当密钥（长度对但用不了）"""),

("样本用了 DoH（DNS over HTTPS），怎么抓它的流量",
"""1. 先判：检测到 443 端口上有规律的 POST 且 Content-Type 是 application/dns-message，
   或 URL 里含 /dns-query
2. 难点：DoH 走 TLS，中间人抓包必须让它信任你的证书 —— 
   若样本做了证书固定（pinning），代理方案直接失效
3. 可行路径 a：hook 样本的 DoH 解析函数（在发送前拿到明文 DNS 报文），
   比自己解 TLS 省事得多
4. 可行路径 b：在系统层禁用 DoH（组策略/注册表），让它回落到普通 DNS，
   再抓 53 端口
5. 可行路径 c：改 hosts 或本地 DNS 劫持，直接把域名指到自己的端点，
   这样连解析都不用看

判据：拿到它实际查询的域名列表
坑：DoH 服务器地址本身可能是硬编码 IP（绕开 DNS），此时路径 b/c 无效，
   只能走 a；先用 kitty_patch find 搜 "dns-query" 或常见 DoH 端点 IP"""),

("怎么给一个未知样本做「能不能安全跑」的判断",
"""1. 静态先看隔离面：kitty_sym imports 里有没有 CreateService / RegSetValue /
   WriteFile 到系统目录 / 网络外联 —— 有就绝对不能在本机裸跑
2. 看反分析：有反虚拟机 + 反调试 + 时间检测 → 说明作者预期被分析，裸跑大概率触发破坏分支
3. 看持久化：Run 键 / 服务 / 计划任务任一存在 → 跑完要清理，否则留后门
4. 安全起跑条件：必须在快照虚拟机 + 断网 + 无共享目录；网络面用 kitty_net 在宿主侧抓
5. 判据：以上三条都评估完，才能给出「可跑 / 只在隔离环境跑 / 不跑只做静态」的结论

判据：结论必须对应到具体导入项与字符串，不能是「感觉危险」
坑：「无网络导入」不等于不联网 —— 可能通过 DoH、命名管道、或加载系统组件代发；
   静态判完还要动态确认一次"""),

("怎么把一次逆向的结论组织成可复现的步骤",
"""1. 每条结论配一条命令：不是「我发现它是 UPX」，而是「kitty_die 报 UPX0/UPX1、熵 7.9」+ 命令原文
2. 每步给判据与退出条件：判据回答「怎么知道这步成立」，退出条件回答「什么时候不该继续」
3. 地址一律存「模块 + 偏移」而不是绝对 VA —— 跨重启不变
4. 写操作必须带回读：W 之后 R，跨视图再加 KM_R，三处一致才算写入
5. 未解项单独列：不要为了完整性编结论，写「未判定 + 缺什么条件才能判定」

判据：别人按步骤能跑出同样的输出（不是「差不多的结论」）
坑：最容易漏的是「环境前提」—— 位数、OS 版本、是否有反调试、是否需要管理员，
   漏一条复现就失败，然后被误判成「结论错了」"""),
]

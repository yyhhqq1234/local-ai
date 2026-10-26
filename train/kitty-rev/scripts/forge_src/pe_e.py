# -*- coding: utf-8 -*-
"""re-pe-structure 扩量 E（71-95）"""

PE_E = [
("资源目录的树深度超过 3 层。",
"""标准资源树是 3 层（Type → Name → Language），更深的层是自定义索引。

```
kitty_dump addr=0xRSRC_VA size=0xRSRC_SIZE path=logs\\rsrc.bin sections=true
kitty_patch action=info path=SAMPLE.exe
```
判读：IMAGE_RESOURCE_DIRECTORY 的 NumberOfIdEntries/NumberOfNamedEntries，
逐层读高位标志（0x80000000 表示指向子目录）。超过 3 层即自定义。

```
kitty_patch action=find path=SAMPLE.exe pattern="4D 5A" from=<.rsrc Raw 偏移> limit=8
```
判读：深树里常挂多个内嵌 PE（每层一个载荷槽），命中数直接给载荷数。

退出：给出「树深 + 叶子块数 + 每块首字节」，深树且多块 → 多载荷样本，逐块独立立项。"""),

("导入 kernel32 的 GetTickCount 出现 12 次。",
"""同一函数被导入多次是链接器缺陷或刻意制造噪音，判据是 IAT 里是否有多份不同地址。

```
kitty_sym action=imports path=SAMPLE.exe filter=GetTickCount
```
判读：同一 DLL 下重复出现同名项 → 畸形导入表（正常链接器会去重）。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xIAT_RVA|qword"
```
判读：多份 IAT 项解析后地址相同 → 纯冗余；地址不同 → 有一份被替换成钩子。

行为含义：GetTickCount 高频检测是计时反调试的常见手法（检测执行间隔突变）。

退出：给出「冗余 / 其中一份被劫持」判定；被劫持的那份地址要单独 query 归属。"""),

(".text 节被标记为可丢弃（MEM_DISCARDABLE）。",
"""可丢弃代码节在内存压力下会被系统回收，之后调用即崩 —— 这是「只在特定时机跑」的设计。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：Characteristics 含 0x02000000(IMAGE_SCN_MEM_DISCARDABLE)。

```
kitty_prot action=query addr=0xTEXT_VA
```
判读：运行期 State 是否仍 COMMIT；被回收后变 MEM_FREE。

```
kitty_ce op="R|0xTEXT_VA|bytes:8"
```
判读：长时间运行后读不出来 = 已被回收，说明它只在启动阶段用。

退出：给出「启动期专用代码」判定；这类代码不能指望在任意时刻动态命中，
断点必须下在启动窗口内（或用 kitty_x64dbg 的 rununtil 抢早）。"""),

("异常目录 Size 是 0x3000，但 RVA 指向 .rdata。",
"""异常目录落在只读数据节 = 表被搬走，或节被合并。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：Data Directory[3] 的 RVA 落在 .rdata 区间。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xEXC_RVA|48"
```
判读：按 RUNTIME_FUNCTION（12 字节一条：Begin/End/UnwindInfo）读，三条即 36 字节。
Begin 是否都落在 .text 区间内 → 是则表有效，只是位置怪。

```
kitty_ghidra action=analyze target=SAMPLE.exe
```
判读：Ghidra 是否据此建出函数边界；建不出说明表内容与代码不符。

退出：给出「表有效但位置异常 / 表内容伪造」判定，并决定栈回溯走 unwind 还是 readdb。"""),

("样本会创建同名互斥体，名字里带 GUID。",
"""互斥体是单实例锁，GUID 名是「同族识别」的最稳指纹之一，比字符串稳定得多。

```
kitty_patch action=find path=SAMPLE.exe str=Global\\ limit=8
kitty_patch action=find path=SAMPLE.exe str=Local\\ limit=8
```
判读：Global\ 前缀 = 跨会话（服务/多用户）；Local\ = 当前会话。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<互斥体名>
```
判读：xref 指向 CreateMutexW 前的一小段 —— 那里通常紧邻其他指纹（服务名、注册表键）。

运行期确认：
```
kitty_ce op=LP
```
判读：用宿主只读查询枚举互斥体句柄所属进程，确认它真的建了。

退出：给出互斥体全名 + 作用域 + 紧邻的其它指纹；GUID 名的互斥体可直接做家族聚类键。"""),

("导入里有 NtQueryInformationProcess 但没有 IsDebuggerPresent。",
"""更底层的反调试：直接问内核 DebugPort，绕过用户态钩子。

```
kitty_sym action=imports path=SAMPLE.exe filter=Nt
```
判读：NtQueryInformationProcess 的第二参数若是 ProcessDebugPort(7)、
ProcessDebugObjectHandle(30)、ProcessDebugFlags(31)，就是反调试三连。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=NtQueryInformationProcess
```
判读：xref 处看压栈常量，7/30/31 任一即坐实；返回值判断分支决定失败行为（退出/降级）。

```
kitty_ce op="S_NEW|dword|7|0xBASE|0xBASE+0x200000" wait=true top=8
```
判读：7 出现在代码段 = 该常量被内联，配合 xref 定位具体函数。

退出：给出「检测类 + 失败行为」；失败即退出时，动态会话必须绕开该检测再谈其他。"""),

("节表结束位置超过了 SizeOfHeaders。",
"""节表越界到第一个节的数据区 = 头部空间被压缩，或有节表副本藏在那里。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：SizeOfHeaders 与 NumberOfSections × 40 + 0x18(PE32+ 头长) 比较。
后者大于前者 → 节表最后一个条目落在数据区。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0x18+0xE0|400"
```
判读：按 40 字节一条读第 N-1 条，Name/VirtualAddress 是否可解释。
可解释 → 只是头空间压缩（加载器按页仍能读）；乱码 → 节表被截，实际节数少于声明。

退出：给出「声明节数 vs 可解析节数」；不可解析的尾部条目直接忽略，不要用它算窗口。"""),

("导出函数名里有 C++ 修饰（?Func@@YAXXZ）。",
"""未修饰的 C++ 导出 = 作者没写 .def，用 __declspec(dllexport) 导出的，名字可直接解码。

```
kitty_sym action=exports path=MODULE.dll filter=?
```
判读：命中即修饰名。用 kitty_ida 的 demangle 或外部工具还原签名。

```
kitty_ida action=analyze target=MODULE.dll
kitty_ida action=functions out=logs\\ida-mod-<ts> filter=?Func
```
判读：还原后的签名给出参数类型 —— 这是「不用逆就能知道接口」的最便宜路径。

```
kitty_ghidra action=decompile out=logs\\ghidra-mod-<ts> name=<修饰名>
```
判读：Ghidra 会自动 demangle，函数体里的参数使用与签名对照，能快速确认真实用途。

退出：给出「导出接口表（签名 + 用途）」，这是 DLL 分析最高性价比的产物。"""),

("样本的入口在 .rsrc 节。",
"""入口落在资源节 = 代码藏在资源里，加载器直接跳过去执行。

```
kitty_patch action=info path=SAMPLE.exe     → AddressOfEntryPoint 的 RVA
kitty_die action=detect target=SAMPLE.exe   → 各节 RVA 区间
```
判据：EP 的 RVA 落在 .rsrc 区间内。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xEP|128"
```
判读：首字节是否合法序言。是 → 资源节被标成可执行，代码可直接跑；
不是 → EP 指向数据，靠 TLS 或其它机制补。

```
kitty_prot action=query addr=0xBASE+0xEP
```
判读：Protect 含 EXECUTE 才能真执行 —— 这是最终判据。

退出：给出「EP 可执行 / 不可执行」+ 首 16 字节；可执行则从 .rsrc 起反汇编，
不要从 .text 起。"""),

("有两个节都叫 .text。",
"""同名节在 PE 里不违法，加载器按顺序映射，后一个覆盖前一个的地址空间（若重叠）。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：两条 .text 的 VirtualAddress 是否重叠。重叠 → 后一个覆盖；
不重叠 → 只是命名重复，两段代码都有效。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xTEXT1_VA|bytes:8"
kitty_ce op="R|0xBASE+0xTEXT2_VA|bytes:8"
```
判读：两处都可读且内容不同 → 不重叠，两段都是真代码；
第二处读到第一处的内容 → 重叠覆盖，第二个 .text 的磁盘数据实际未生效。

```
kitty_patch action=hash path=SAMPLE.exe
```
退出：给出「重叠 / 不重叠」判定 + 每段首 8 字节；重叠时静态分析只能信第一个。"""),

("导入表里 Advapi32 只导 LsaOpenPolicy 和 LsaQueryInformationPolicy。",
"""这是凭据/策略枚举的最小组合，不是普通配置读取。

```
kitty_sym action=imports path=SAMPLE.exe filter=Lsa
```
判读：只有 Open/Query 没有 Close → 导入被裁（真实代码会 Close）；
三者齐全 → 完整实现。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=LsaOpenPolicy
```
判读：压栈的 POLICY_INFORMATION_CLASS 常量给出「问什么」：
PolicyAccountDomainInformation(5) / PolicyPrimaryDomainInformation(3) /
PolicyDnsDomainInformation(12)。

```
kitty_ce op=MODENUM
```
退出：给出「查询的策略类 + 输出用途（域名/账号域/信任关系）」；
这类能力面在正常软件里极罕见，是判定的强信号。"""),

("资源节的 SizeOfRawData 是 0，但 VirtualSize 很大。",
"""资源在磁盘上没有数据却声明了大小 = 运行时填充，或压缩存储。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：.rsrc 的 PointToRawData/RawSize 为 0，VirtualSize 非 0。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xRSRC_VA|bytes:16"
```
判读：运行期可读且非零 → 数据是运行期写入的（从别处解密/下载）；
全零 → 声明了但没用，静态分析可跳过该节。

```
kitty_ce op="S_SNAP|bytes:16|0xRSRC_VA|0xRSRC_VA+0x2000"
```
跑起来后 S_CHANGED
判读：有变化 = 运行时填充坐实，变化区即资源内容。

退出：给出「运行期填充 / 空声明」判定；填充型要走动态，静态无信息。"""),

("导入 MSVCR120 而不是 UCRT，且样本来自 2015 年后。",
"""工具链指纹：MSVCR120 对应 VS2013，2015 后的正经项目默认 UCRT。
说明作者用了老工具链或刻意伪装年代。

```
kitty_sym action=imports path=SAMPLE.exe filter=MSVC
kitty_patch action=find path=SAMPLE.exe str=Microsoft Visual C++ limit=8
```
判读：版本串与导入 DLL 版本是否一致。不一致 → 版本资源被改。

```
kitty_die action=detect target=SAMPLE.exe
```
判据：TimeDateStamp 与导入工具链的发布年代对比。时间戳晚于工具链年代很多 →
要么长期维护，要么时间戳被改。

```
kitty_patch action=find path=SAMPLE.exe str=Rich limit=1
```
判读：Rich 头记录链接器版本序列，能反推真实 VS 版本 —— 与导入 DLL 对照即知是否伪装。

退出：给出「真实工具链 vs 表面工具链」；两者不符是「刻意规避特征」的证据。"""),

("样本的 DllMain 里有 CREATE_PROCESS 分支的处理。",
"""DLL 被注入时，系统会以 DLL_PROCESS_ATTACH 调用 DllMain —— 这条分支就是注入后的首执行点。

```
kitty_ghidra action=analyze target=MODULE.dll
kitty_ghidra action=functions out=logs\\ghidra-mod-<ts> filter=DllMain
```
判读：DllMain 第二参数 fdwReason 与 1(DLL_PROCESS_ATTACH) 比较的分支。

```
kitty_sym action=imports path=MODULE.dll filter=DisableThreadLibraryCalls
```
判读：调用了它 → 作者不关心线程级通知，说明只做一次性初始化；
没调用 → 可能在 DLL_THREAD_ATTACH 里做事。

```
kitty_ce op=MODENUM
```
判读：模块表里出现该 DLL 且无对应 exe 加载 → 注入形态。

退出：给出「注入即执行的内容」（DllMain 分支里干了什么）+ 是否禁用线程通知。"""),

("导入表里 kernel32 有 CreateRemoteThread，但没有 OpenProcess。",
"""缺 OpenProcess 说明句柄从别处来：要么复制句柄，要么在自己身上执行。

```
kitty_sym action=imports path=SAMPLE.exe filter=Process
```
判读：有无 OpenProcess/OpenThread/DuplicateHandle/NtOpenProcess。
只有 CreateRemoteThread + 无任何打开函数 → 它只能对自己或已继承句柄操作。

```
kitty_sym action=imports path=SAMPLE.exe
```
判读：若同时有 NtCreateThreadEx（ntdll），说明真正路径是 Nt 层，
kernel32 的那条是诱饵或备选。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=CreateRemoteThread
```
判读：第一个参数（hProcess）的来源 —— 追踪它的赋值点即可判断目标进程。

退出：给出「目标进程如何获得」的链路；拿不到链路时结论只能是「未判定」。"""),

("节的 VirtualAddress 不是 SectionAlignment 的整数倍。",
"""未对齐的 VA = 节表被手工改，加载器会按页对齐上取，导致声明与实际映射错位。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：每个节的 VirtualAddress % SectionAlignment != 0。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xREALIGNED_VA|bytes:8"
```
判读：用对齐后的地址读，能否拿到该节应有的首字节。能 → 按对齐值算窗口；
不能 → 该节实际未被映射。

```
kitty_patch action=find path=SAMPLE.exe pattern="<该节应有首字节>" limit=4
```
判读：在文件里搜这段字节出现的位置，反推真实 Raw 偏移。

退出：给出「对齐后 VA 生效 / 该节未映射」判定，并据此重算所有节窗口。"""),

("样本导出了 DllRegisterServer / DllGetClassObject。",
"""COM 服务器。函数名固定，判据是 CLSID 与注册表写入面。

```
kitty_sym action=exports path=MODULE.dll filter=Dll
```
判读：DllGetClassObject + DllCanUnloadNow + DllRegisterServer 三件套齐全即 COM。

```
kitty_patch action=find path=SAMPLE.exe str={0000 limit=8
kitty_patch action=find path=SAMPLE.exe str=CLSID utf16=true limit=8
```
判读：CLSID 通常以 "{XXXXXXXX-...}" 形式内联，命中即拿到组件 ID。

```
kitty_ghidra action=analyze target=MODULE.dll
kitty_ghidra action=decompile out=logs\\ghidra-mod-<ts> name=DllRegisterServer
```
判读：它写的注册表键路径（InprocServer32）给出注册位置。

退出：给出「CLSID + 注册路径 + 接口 IID」，这是 COM 样本的标准交付物。"""),

("导入表里 wininet 和 winhttp 同时出现。",
"""两套 HTTP 栈并存 = 双重外联路径，判据是各自的调用条件分支。

```
kitty_sym action=imports path=SAMPLE.exe filter=Internet
kitty_sym action=imports path=SAMPLE.exe filter=WinHttp
```
判读：函数项多少。wininet 只有 InternetOpen/OpenUrl/ReadFile → 简单 GET；
winhttp 有 WinHttpSetOption/SecurityFlags → 支持自定义证书/代理规避。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=WinHttpOpen
```
判读：xref 上游是否有「前一条路径失败」的分支 → 备用通道。

退出：给出「主通道 / 备用通道」判定 + 各自的 URL 来源；
两条都通时抓包只需盯先触发的那条。"""),

("资源里有 RT_STRING 表但全是空串。",
"""空字符串表是「资源槽占位」——常见于本地化框架，也可能用于隐藏定长数据。

```
kitty_dump addr=0xRSRC_VA size=0xRSRC_SIZE path=logs\\rsrc.bin sections=true
kitty_patch action=info path=SAMPLE.exe
```
判读：RT_STRING 块结构是「重复的 (长度 WORD + UTF-16 字符串)」，长度 0 即空串。

```
kitty_patch action=find path=SAMPLE.exe pattern="00 00 00 00 00 00 00 00" from=<块偏移> limit=4
```
判读：全零块长度是否等于声明大小。等长 → 纯占位；短很多 → 块里混了非零数据。

```
kitty_ce op="S_SNAP|bytes:16|0xRSRC_VA|0xRSRC_VA+0x2000"
```
判读：运行期被写入 → 字符串表被当地址簿用（写入指针）。

退出：给出「占位 / 运行期数据槽」判定。"""),

("导入表里出现 ordinal 0。",
"""序号 0 在 PE 导入里是非法值（序号从 1 开始），说明表被构造过。

```
kitty_sym action=imports path=SAMPLE.exe
```
判读：某条显示 Ordinal=0 且无名字。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xIAT_RVA+<该项偏移>|qword"
```
判读：运行期该项是否被解析成有效地址。有效 → 加载器容忍并按某个约定解析；
0 或非法 → 该导入项被跳过。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<相邻函数名>
```
判读：相邻项正常解析说明只有这一条被特殊处理 —— 通常是给某个补丁点留位。

退出：给出「被跳过 / 被特殊解析」判定 + 该项在 IAT 中的运行期值。"""),

("样本大小 40KB，但 .rsrc 有 800KB 的描述。",
"""声明大于文件 = 资源目录损坏，或有稀疏填充（文件系统层允许，PE 层不允许）。

```
kitty_patch action=info path=SAMPLE.exe
```
判据：.rsrc 的 RawSize 与文件剩余长度比较。RawSize > 剩余 → 声明越界。

```
kitty_patch action=find path=SAMPLE.exe pattern="4D 5A" from=<.rsrc Raw 偏移> limit=8
```
判读：越界声明下仍有命中 → 文件尾部藏着真数据，声明是为了误导「资源很大」这个判断。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xRSRC_VA|bytes:8"
```
判读：运行期读得到 → 加载器按声明映射了（后面是零页）；读失败 → 未映射。

退出：给出「越界声明 + 尾部实际数据量」；不要按 800KB 建窗口，按文件实际剩余建。"""),

("导入表里有 SetWindowsHookEx。",
"""全局钩子 = 进程外注入的最简路径，判据是钩子类型与目标。

```
kitty_sym action=imports path=SAMPLE.exe filter=Hook
kitty_sym action=imports path=SAMPLE.exe filter=CallNextHookEx
```
判读：有 SetWindowsHookEx 且有 CallNextHookEx → 完整钩子实现；
只有 Set → 可能只装置不处理（转发型）。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=SetWindowsHookEx
```
判读：压栈的 idHook 常量：WH_KEYBOARD_LL(13) / WH_MOUSE_LL(14) 是全局低级钩子，
不需要 DLL 注入；WH_GETMESSAGE(3) 之类需要在目标进程里加载 DLL。

退出：给出「钩子类型 + 是否需要 DLL」；低级钩子型样本不会有远程注入痕迹，
别去 OpenProcess 上找证据。"""),

(".edata 节存在但 SizeOfRawData 为 0。",
"""导出节空声明 = 导出表被剥（避免被按名调用），但按序号仍可能可调。

```
kitty_patch action=info path=SAMPLE.exe
kitty_sym action=exports path=SAMPLE.exe
```
判读：info 显示 .edata 存在但 Raw=0，sym 返回 0 个导出 → 导出被剥。

```
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xEXPORT_RVA|40"
```
判读：IMAGE_EXPORT_DIRECTORY 头（40 字节）在内存里是否可读。
NumberOfNames=0 而 NumberOfFunctions>0 → 只剩序号导出，按序号仍可调用。

退出：给出「按名可用 / 仅按序号 / 完全不可用」三态，
并按结果决定后续是用名字还是序号建调用面。"""),

("同一份代码在 debug 版和 release 版里的导入差别很大。",
"""debug 版多出调试 CRT 与断言函数，release 剥掉 —— 判据是「多出来的那批是不是纯调试面」。

```
kitty_sym action=imports path=APP_debug.exe
kitty_sym action=imports path=APP_release.exe
```
判读：差集里若全是 _CrtDbgReport / _malloc_dbg / OutputDebugStringW → 纯调试面，
逻辑面一致。

```
kitty_patch action=find path=APP_debug.exe str=Assertion failed limit=4
```
判读：命中断言串 → debug 版，字符串量更大、更利于分析。

```
kitty_ghidra action=analyze target=APP_release.exe
```
判读：release 版函数内联多、变量被优化掉；debug 版更贴近源码结构。

退出：给出「用 debug 版理解逻辑、用 release 版理解真实行为」的分工结论；
两者函数偏移不可互换，不要跨版本套地址。"""),

("样本导入了 EnumProcesses 和 GetModuleFileNameEx。",
"""进程枚举 + 模块名读取 = 进程扫描器的最小组合，判据是比对目标名单。

```
kitty_sym action=imports path=SAMPLE.exe filter=Process
kitty_sym action=imports path=SAMPLE.exe filter=Module
```
判读：EnumProcesses + OpenProcess + GetModuleFileNameEx + GetModuleBaseName
四件套 = 完整扫描器。

```
kitty_patch action=find path=SAMPLE.exe str=.exe utf16=true limit=16
```
判读：目标名单通常以宽字符串内联（被检测的进程名列表），这是最快的样本意图证据。

```
kitty_ce op=LP
```
判读：运行期对比 —— 它枚举的进程在宿主上是否存在，直接影响行为分支。

退出：给出「目标名单 + 命中后的行为（退出/上报/切换模式）」。
名单是这类样本最有价值的情报，优先提取。"""),

("PE 的 overlay 起点之后有 0x20 字节非零，其余全零。",
"""小段非零 + 大段零 = 追加了一个小结构（签名块、版本标记或校验尾）。

```
kitty_patch action=info path=SAMPLE.exe
```
判读：overlay 起点 M，文件长 L，非零段在 [M, M+0x20)。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+M|32"
```
判读：32 字节的形态判类型：
4 字节魔数 + 4 字节版本 + 24 字节哈希 → 自校验尾；
30 82 开头 → PKCS#7 片段；
全随机 → 密钥或 nonce。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<该 32 字节的前 4 字节值>
```
判读：代码里若出现这个魔数常量，说明程序会读它 —— 校验/解密入口。

退出：给出「结构类型 + 是否被代码读取」；被读取就把它当配置字段纳入结构表。"""),
]

# -*- coding: utf-8 -*-
"""re-detour-trajectory 扩量 C（31-60）：工具选错 → 参数格式错 → 误判架构 → 收敛"""

DET_C = [
("我以为样本是 .NET，dnSpy 打开空白，最后发现是 NativeAOT。",
"""往返1｜动作：看 PE 头有 CLR 目录，上 dnSpy
kitty_dnspy action=decompile target=APP.exe out=logs\\dnspy
回包：只有 <Module>，无业务类
判读：第一次失败。CLR 头存在不等于有 IL。

往返2｜动作：查元数据大小
kitty_patch action=info path=APP.exe
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0xCLR_RVA|bytes:72"
回包：MetaData 的 Size 极小（<0x100）
判读：坐实 —— 只有头，没有元数据。这是 NativeAOT 的典型形态。

往返3｜动作：换 native 路线
kitty_sym action=imports path=APP.exe
回包：导入面完整（不含 mscoree）
kitty_ida action=analyze target=APP.exe
kitty_ida action=functions out=logs\\ida-app-<ts> limit=80
判读：函数数正常，可读。

收敛｜末态验证
kitty_die action=detect target=APP.exe → 报原生
kitty_ghidra action=functions out=logs\\ghidra-aot-<ts> filter=main
回包：能定位到 main 相关符号（AOT 会保留部分名字）
末态：改走 native 分析，dnSpy 产物作废。
复盘：托管判定要三步 —— 目录存在、COR20 头合法、元数据 Size 够大。"""),

("我用 64 位调试器附加 32 位进程，附加直接失败。",
"""往返1｜动作：kitty_x64dbg action=run target=APP32.exe
回包：附加失败 / 进程无响应
判读：第一次失败。64 位调试器不能调 32 位目标。

往返2｜动作：怀疑是反调试
kitty_sym action=imports path=APP32.exe filter=Debug
kitty_patch action=info path=APP32.exe
回包：有 IsDebuggerPresent，但 Machine=0x14C（32 位）
判读：方向错了。反调试不是主因，位数不匹配才是。

往返3｜动作：换 32 位调试器变体
kitty_variants action=list
kitty_variants action=switch variant=ws-dbg-dbg32
kitty_x64dbg action=selftest
回包：自检通过
判读：这一步对了。

往返4｜动作：重新附加
kitty_x64dbg action=run target=APP32.exe
回包：成功附加并停在入口
判读：位数对齐后一切正常。

收敛｜末态验证
kitty_ce op=MODENUM → is64=0
kitty_x64dbg action=readdb addr=<入口> → 读到与磁盘一致的字节
末态：32 位调试链路可用。
复盘：附加失败先核位数，再怀疑反调试。"""),

("我把 APK 拖进 jadx，只看到壳类，以为加固到无法分析。",
"""往返1｜动作：kitty_jadx action=decompile target=app.apk
回包：只有 com.xxx.StubApp 之类
判读：第一次失败。看到壳类不等于业务不可达。

往返2｜动作：先做加固指纹
kitty_apkscan action=scan target=app.apk
回包：识别出加固厂商 + libshella
判读：确认是整体加壳，业务 dex 在运行期释放。

往返3｜动作：脱壳
kitty_frida action=spawn pkg=<包名>
kitty_frida action=script pkg=<包名> script=<只 hook DexFile.loadDex，延迟 500ms 落盘>
回包：产出 5 个 dex，其中一个含业务包名
判读：这一步对了。

往返4｜动作：在脱壳产物上反编译
kitty_jadx action=decompile target=logs\\dex\\business.dex out=logs\\jadx-biz
kitty_rea_method path=app.apk class_name=<登录类> method_name=<签名>
回包：方法体出现 MessageDigest 调用
判读：业务层可读。

收敛｜末态验证
kitty_rea_android path=app.apk → 清单可解析
业务方法体内出现完整字段拼接 + 摘要调用
末态：加固已绕过，业务逻辑可读。
复盘：先指纹再脱壳；attach 改 spawn；hook 面越小越好。"""),

("P_BACK 我给了一个 4GB 的窗口，作业跑了十分钟没结果。",
"""往返1｜动作：整堆窗口反查
kitty_ce op="P_BACK|0xTARGET|0x10000000|0x140000000"
回包：长时间 pending，无结果
判读：第一次失败。4GB 逐页扫，时间上不可能完成。

往返2｜动作：以为桥卡了，去探活
kitty_ce op=PING
回包：正常
判读：通道没问题，是作业本身太大。方向错。

往返3｜动作：按容器归属给窗
kitty_prot action=query addr=0xTARGET
回包：AllocationBase=0x1D2A0000000 RegionSize=0x400000
kitty_ce op="P_BACK|0xTARGET|0x1D2A0000000|0x1D2A0040000"
回包：OK|6 条
判读：这一步对了。窗口从 4GB 降到 4MB。

往返4｜动作：收窄后逐条回验
kitty_ce op="P_BACK_RES|6"
kitty_ce op="R|0x1D2A0012340|qword"
回包：等于 0xTARGET
判读：确认候选有效。

收敛｜末态验证
kitty_ce op="P_WALK|0xBASE|0xOFF" → 回读等于目标
末态：链成立，用时从十分钟降到秒级。
复盘：反查窗口 = 容器大小，不是地址空间大小。"""),

("读一个 float 值我按十进制写 W，写进去变成 0。",
"""往返1｜动作：按十进制写
kitty_ce op="W|0xADDR|dword|100" confirm=true
kitty_ce op="R|0xADDR|dword"
回包：100（十进制）
判读：写成功了，但界面显示 1.4e-43 —— 说明该字段是 float，100 的位模式不是 100.0f。

往返2｜动作：以为写错地址
kitty_ce op="R|0xADDR-4|dword"
kitty_ce op="R|0xADDR+4|dword"
回包：相邻字段正常
判读：地址没错，是类型理解错。

往返3｜动作：按位模式写
kitty_ce op="W|0xADDR|dword|0x42C80000" confirm=true
kitty_ce op="R|0xADDR|dword"
回包：0x42C80000
判读：界面显示 100.0 —— 正确。

收敛｜末态验证
kitty_km action=read addr=0xADDR vt=dword → 0x42C80000
界面值 = 100.0
末态：位模式写入 + 双视图一致。
复盘：float 字段必须写 IEEE754 位模式；先读一次确认类型再写。"""),

("KM_ATTACH 之后 KM_R 全读 0，我以为内核面被拦。",
"""往返1｜动作：attach 后直接读
kitty_km action=attach pid=<pid>
kitty_km action=read addr=0xADDR vt=dword
回包：0
判读：第一次失败。读 0 有两种原因：没附加成功，或地址错。

往返2｜动作：查附加状态
kitty_km action=info
回包：pid 与预期不符（attach 到了上一次的目标）
判读：方向修正 —— 不是拦截面，是附加错进程。

往返3｜动作：重新 attach（attach-once 语义）
kitty_km action=attach pid=<正确pid>
kitty_km action=info
回包：pid 正确
kitty_km action=read addr=0xADDR vt=dword
回包：1500（正常值）
判读：这一步对了。

收敛｜末态验证
kitty_dualview addr=0xADDR vt=dword samples=2
回包：三视图一致，无分叉
末态：内核面可用，之前不是拦截。
复盘：KM_R 读 0 先看 info 的 pid，不要直接判「被拦」。"""),

("我用字符串搜索找配置，全被 UTF-16 编码坑了。",
"""往返1｜动作：按 ASCII 搜
kitty_patch action=find path=SAMPLE.exe str=Server limit=8
回包：0 命中
判读：第一次失败。

往返2｜动作：扩大范围再搜
kitty_patch action=find path=SAMPLE.exe str=server limit=8
回包：仍 0
判读：第二次失败。大小写不是问题。

往返3｜动作：改 UTF-16
kitty_patch action=find path=SAMPLE.exe str=Server utf16=true limit=8
回包：命中 2 处
判读：这一步对了 —— 该程序的字符串是宽字符。

往返4｜动作：验证位置是否合理
kitty_patch action=info path=SAMPLE.exe
回包：命中偏移落在 .rdata
判读：位置合理，确认为配置串。

收敛｜末态验证
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0x串RVA|bytes:32" → 每隔一字节为 00，确认 UTF-16LE
末态：明文配置串拿到。
复盘：搜不到先换编码，别先怀疑加密。"""),

("我想 hook 一个函数，三次下错断点。",
"""往返1｜动作：按磁盘偏移下断
kitty_dbg action=bp addr=0x1A2B4C access=execute
回包：设置成功但永不命中
判读：第一次失败。0x1A2B4C 是文件偏移。

往返2｜动作：加磁盘 ImageBase
kitty_dbg action=bp addr=0x14001B2B4C access=execute
回包：仍不命中
判读：第二次失败。ASLR 下运行时 base 与 ImageBase 不同。

往返3｜动作：取运行时 base
kitty_ce op=MODENUM
回包：base=0x7FF6DADB1000
kitty_dbg action=bp addr=0x7FF6DAF53B4C access=execute
回包：命中
判读：这一步对了。

往返4｜动作：命中后发现停在中段
kitty_dbg action=regs
回包：rcx 是无意义小值
判读：下在比较指令上了，不是函数入口。

往返5｜动作：用符号定位入口
kitty_sym source=mem module=TARGET.exe action=resolve name=<导出名>
kitty_dbg action=bp addr=<VA> access=execute
回包：命中，rcx 是有效指针

收敛｜末态验证
kitty_ce op="R|0xRCX|dword" → 读到合法值
kitty_dbg action=bp_del id=<id> → kitty_dbg action=detach
末态：断点位于入口、寄存器可用、已清理。
复盘：地址 = 运行时 base + RVA；能拿符号就别用偏移。"""),

("MEMDUMP_HEX 我只拿到一半数据，以为是权限问题。",
"""往返1｜动作：一次读 8KB
kitty_ce op="MEMDUMP_HEX|0xADDR|8192"
回包：只回约 4KB 的十六进制
判读：第一次失败。单次上限 4096 字节。

往返2｜动作：怀疑跨页不可读
kitty_prot action=query addr=0xADDR+4096
回包：State=COMMIT，可读
判读：方向错了，不是权限。

往返3｜动作：分两块读
kitty_ce op="MEMDUMP_HEX|0xADDR|4096"
kitty_ce op="MEMDUMP_HEX|0xADDR+4096|4096"
回包：两块长度都完整
判读：这一步对了。

收敛｜末态验证
拼接总长 = 8192；首 16 字节与 kitty_ce op="R|0xADDR|bytes:16" 一致
末态：完整数据落盘。
复盘：MEMDUMP_HEX 按 4096 连续切；先核上限再怀疑权限。"""),

("扫描作业一直 pending，我杀了宿主，其实只是区间太大。",
"""往返1｜动作：整模块扫
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+SIZE" wait=true
回包：长时间 pending
判读：第一次失败。

往返2｜动作：以为桥卡死，重启宿主
kitty_drv action=host
回包：宿主重拉，通道恢复
判读：第二次失败（误判）。作业本可以自己完成。

往返3｜动作：查作业状态而不是杀进程
kitty_ce op=JOB_STAT
回包：state=running, n 在增长
判读：作业正常推进，不该重启。

往返4｜动作：分块扫
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1000000" wait=true top=20
回包：OK|done|n=31
判读：这一步对了。

收敛｜末态验证
kitty_ce op="S_GET|0|5" → 取样
kitty_ce op="R|0xCAND|dword" → 值吻合
末态：拿到候选，宿主未被无谓重启。
复盘：pending 先看 JOB_STAT 的 n 是否在动，再决定是否重启。"""),

("我把 .so 当 x86 反汇编，全是垃圾。",
"""往返1｜动作：kitty_ghidra action=analyze target=libnative.so
回包：反汇编满屏无效指令
判读：第一次失败。语言选错。

往返2｜动作：以为是加壳
kitty_die action=detect target=libnative.so
回包：无壳特征，ELF 头合法
判读：方向错了，不是壳。

往返3｜动作：核架构
kitty_rea_binary path=libnative.so
回包：AArch64
判读：坐实 —— 之前按 x86 解，必然全错。

往返4｜动作：指定 ARM64
kitty_ghidra action=analyze target=libnative.so
判读：Language 设为 AARCH64:LE:64:v8A
回包：函数边界正常，出现 BL 调用
判读：这一步对了。

收敛｜末态验证
kitty_ghidra action=functions out=logs\\ghidra-so-<ts> filter=Java_
回包：能解出 JNI 入口
末态：ARM64 视图可用，x86 产物作废。
复盘：先核架构再反汇编；错选语言不会报错，只给垃圾。"""),

("我想读注册表值，跑去逆代码，其实有更快的路。",
"""往返1｜动作：直接在二进制里找键名
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=16
回包：拿到 3 个键名
判读：这一步是对的，但下一步走偏了。

往返2｜动作：试图静态解出值内容
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<n>-<ts> name=<写入函数>
回包：值来自加密配置，静态解不动
判读：失败。值不是硬编码。

往返3｜动作：改成运行期观测
kitty_x64dbg action=seed addr=advapi32.RegSetValueExW seedCmd=log
回包：命中，参数里带值名与数据
判读：这一步对了 —— 值是运行期算出来的，必须动态取。

往返4｜动作：读参数
kitty_dbg action=regs
kitty_ce op="R|0xRDX|bytes:64"
回包：值名与数据都可读

收敛｜末态验证
kitty_ce op="MEMDUMP_HEX|0xRDX|64" → 与日志一致
末态：拿到键路径 + 值名 + 数据。
复盘：值是算出来的就别硬解；写类 API 的断点是最短路径。"""),

("BTACH 里放了扫描作业，回包全错位。",
"""往返1｜动作：批处理里混扫描
kitty_ce ops=["S_NEW|dword|1500|0xSTART|0xSTOP","R|0xADDR|dword"]
回包：第一条回 pending，第二条回的内部状态
判读：第一次失败。异步作业不能进 BATCH。

往返2｜动作：改成 scan 后批量读
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP" wait=true top=20
kitty_ce ops=["R|0xCAND1|dword","R|0xCAND2|dword"]
回包：顺序正确
判读：这一步对了。

往返3｜动作：把写也塞进 BATCH，忘了 confirm
kitty_ce ops=["W|0xADDR|dword|100"]
回包：被拒（缺确认）
判读：第三次失败。BATCH 里的写同样要确认。

往返4｜动作：写批 + 读批分开
kitty_ce ops=[<N 条 W，逐条带确认>]
kitty_ce ops=[<N 条 R>]
回包：写全 OK，读全回值
判读：正确。

收敛｜末态验证
读批的 N 条值与写入值比对；kitty_ce op=SYNC_ARCHIVE → SYNC_STAT 四项 0
末态：写入可证明，状态归零。
复盘：BATCH 只放同步 OP；写读分批；读批就是验证批。"""),

("我按 64 位算了一晚上偏移，样本其实是 32 位。",
"""往返1｜动作：按 x64 惯例读指针
kitty_ce op="R|0x7FF6DAE12340|qword"
回包：0x00000000000005DC
判读：看着像指针，实际是 dword 值被当 qword 读。

往返2｜动作：按这个值反查
kitty_ce op="P_BACK|0x5DC|0x7FF6DADB1000|0x7FF6DADCD1000"
回包：n 巨大
判读：第二次失败。小值到处都有。

往返3｜动作：核位数
kitty_ce op=MODENUM
回包：TARGET.exe|0x00400000|0|0
判读：坐实 —— is64=0，base=0x00400000。前面用的 0x7FF6 地址全是错的。

往返4｜动作：重取窗口再扫
kitty_ce op="R|0x0040003C|dword" → e_lfanew
kitty_ce op="S_NEW|dword|1500|0x00400000|0x00400000+0x1C00000" wait=true top=20
回包：n=9
判读：这一步对了。

收敛｜末态验证
kitty_ce op="R|0x00412A40|dword" → 1500
kitty_km action=read addr=0x00412A40 vt=dword → 1500
末态：32 位地址空间内双视图一致。
复盘：任何 OP 之前先看 is64；位数错不报错，只给错值。"""),

("用 kitty_dump 转储后 IDA 打不开，忘了 unmap。",
"""往返1｜动作：直接 dump 原始内存
kitty_dump module=TARGET.exe path=logs\\raw.bin
kitty_ida action=analyze target=logs\\raw.bin
回包：IDA 报格式错误 / 导入 0 项
判读：第一次失败。内存镜像是页对齐的，不是磁盘格式。

往返2｜动作：手工改节表
判读：改了 3 个节的 PointerToRawData，仍解析失败
判读：第二次失败。手工改容易漏 IAT 与校验和。

往返3｜动作：用 unmap + fix_iat
kitty_dump module=TARGET.exe unmap=true fix_iat=true path=logs\\fixed.bin reference=SAMPLE.exe
回包：一致率 93.1%
kitty_ida action=analyze target=logs\\fixed.bin
回包：导入可解析
判读：这一步对了。

收敛｜末态验证
kitty_sym action=imports path=logs\\fixed.bin → 38 项可解析
kitty_ida action=imports out=logs\\ida-fixed-<ts> limit=20
末态：镜像可分析，一致率已记录。
复盘：unmap 与 fix_iat 同时开，并给 reference 算一致率。"""),

("我以为样本有反调试，其实是缺运行库。",
"""往返1｜动作：看到启动即退出，判反调试
kitty_sym action=imports path=SAMPLE.exe filter=Debug
回包：只有 IsDebuggerPresent（CRT 常见）
判读：证据不足。

往返2｜动作：找反调试典型指令
kitty_patch action=find path=SAMPLE.exe pattern="0F 31" limit=8
回包：命中 rdtsc（CRT 也有）
判读：第二次证据不足。

往返3｜动作：改抓退出点
kitty_x64dbg action=seed addr=kernel32.ExitProcess seedCmd=log
回包：退出前最后调用是 LoadLibraryW，返回 0
判读：坐实 —— 缺依赖，不是反调试。

往返4｜动作：补齐运行库
kitty_ce op=MODENUM
回包：模块表里出现新加载的 vcruntime
判读：这一步对了。

收敛｜末态验证
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1000000" wait=true top=10 → n>0
末态：能跑到业务逻辑。
复盘：跑不起来先抓退出码与最后调用，别先归因反调试。"""),

("我把 dump 当磁盘文件算 RVA，偏移全错。",
"""往返1｜动作：按磁盘节表算 RVA
kitty_patch action=info path=logs\\mem.bin
回包：节表可读
判读：能读，但节表是内存布局（对齐 0x1000）。

往返2｜动作：用 FileAlignment 换算
判读：算出的文件偏移与内容不对应
回包：读到乱码
判读：第一次失败。内存镜像没有文件对齐概念。

往返3｜动作：改用 SectionAlignment 直接算
kitty_ce op="MEMDUMP_HEX|0x0+0xTEXT_VA|64"
回包：读到合法序言
判读：这一步对了 —— 内存镜像里 RVA 就是相对基址的偏移。

收敛｜末态验证
kitty_ce op="R|0x0+0xEP_RVA|bytes:8" → 与磁盘 EP 字节一致
末态：地址换算规则确定（内存镜像直接用 RVA）。
复盘：内存镜像与磁盘文件的换算规则不同，先确认手里是哪一种。"""),

("我改完值没回读，报了个假结论。",
"""往返1｜动作：写后直接判成功
kitty_ce op="W|0xADDR|dword|100" confirm=true
回包：OK
判读：第一次失败。OK 只表示指令被受理。

往返2｜动作：以为任务完成，去写报告
判读：报告里写「已改成功」
回包：—（人为错误）
判读：这个结论没有证据支撑。

往返3｜动作：补回读
kitty_ce op="R|0xADDR|dword"
回包：1500（原值）
判读：坐实 —— 写入被吞。

往返4｜动作：换写路径
kitty_prot action=query addr=0xADDR
kitty_wpb addr=0xADDR val=100 vt=dword restore=true accept_protection_bypass=true
kitty_ce op="R|0xADDR|dword" → 100
kitty_km action=read addr=0xADDR vt=dword → 100
判读：这一步对了。

收敛｜末态验证
两视图一致 + 3 秒后仍为 100
末态：写入真实生效；旧报告作废重写。
复盘：任何写操作，没有回读就等于没做。"""),

("找指针链时我用对了窗口，但跳错了一级。",
"""往返1｜动作：从目标地址直接反查
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x400000"
回包：3 条候选
判读：窗口对了。

往返2｜动作：取第一条当上一级
kitty_ce op="R|0xCAND1|qword"
回包：0x1D2A0001234（不是目标）
判读：第一次失败。候选顺序不等于相关性。

往返3｜动作：逐条回验
kitty_ce op="R|0xCAND2|qword" → 0x1D2A0012340（不是）
kitty_ce op="R|0xCAND3|qword" → 0xTARGET（命中）
判读：这一步对了。

往返4｜动作：继续上跳，改用 pchain 免手算
kitty_pchain target=0xCAND3 depth=2 mod=TARGET.exe
回包：→ 模块静态区

收敛｜末态验证
kitty_ce op="P_WALK|0xBASE|0xOFF" → 逐级回读等于目标
末态：链成立，每级都经 R 回验。
复盘：候选必须逐条 R 回验，不能按顺序取第一条。"""),

("我以为 BATCH 能提升扫描速度，其实是异步作业拖慢的。",
"""往返1｜动作：把 20 条 S_NEW 塞进 BATCH 想并行
kitty_ce ops=[<20 条 S_NEW>]
回包：错位 + 状态占用
判读：第一次失败。扫描是异步单例。

往返2｜动作：改成一条条发
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1000000" wait=true top=20
回包：正常
判读：这一步对了。

往返3｜动作：想加速，改小窗口多次扫
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x400000" wait=true top=20
回包：n 少量，更快
判读：窗口小 = 扫得快。

往返4｜动作：用 LUA 批量读替代多次 R
kitty_ce op="LUA|local t={} for i=0,99 do t[#t+1]=string.format('%X',readInteger(0xBASE+i*4)) end return table.concat(t,',')"
回包：一次拿 100 个值
判读：这一步对了。

收敛｜末态验证
kitty_ce op=SYNC_STAT → 四项 0
末态：扫描 + 批量读都在正确层面完成。
复盘：加速靠「缩小窗口」和「LUA 批量读」，不靠 BATCH 塞异步作业。"""),

("我用 strings 找配置，拿到半截乱码。",
"""往返1｜动作：strings 扫二进制
回包：大量可读串，配置项被截断
判读：第一次失败。strings 按可打印字符切，二进制值会被切断。

往返2｜动作：以为文件损坏
kitty_patch action=info path=SAMPLE.exe
回包：节表正常
判读：方向错了。

往返3｜动作：按结构读
kitty_patch action=find path=SAMPLE.exe str=Server utf16=true limit=8
回包：命中偏移
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xRVA|256"
回包：完整配置块（含二进制字段）
判读：这一步对了。

收敛｜末态验证
按字段表解析该块，每个字段值自洽（端口在 1-65535、地址可解析）
末态：配置结构恢复。
复盘：配置是结构化数据，用 dump 按结构读，不要用 strings。"""),

("我把签名目录和调试目录搞混，验证了半天空数据。",
"""往返1｜动作：按索引 6 找签名
kitty_patch action=info path=SAMPLE.exe
kitty_patch action=find path=SAMPLE.exe pattern="30 82" from=<索引6偏移> limit=2
回包：0 命中
判读：第一次失败。索引 6 是调试目录。

往返2｜动作：以为签名被剥
kitty_die action=detect target=SAMPLE.exe
回包：报有 Security 目录
判读：矛盾 —— 说明我查错了索引。

往返3｜动作：改查索引 4
kitty_patch action=find path=SAMPLE.exe pattern="30 82" from=<索引4偏移> limit=2
回包：命中
判读：这一步对了。

往返4｜动作：验证证书链
判读：WIN_CERTIFICATE 的 dwLength ≤ 目录 Size
回包：合法

收敛｜末态验证
kitty_die action=detect target=SAMPLE.exe → 报签名有效
末态：签名结论与目录索引一致。
复盘：4=Security，6=Debug；索引别记反。"""),

("我 attach 到错误进程，写了一天数据全废。",
"""往返1｜动作：按进程名 OPEN
kitty_ce op=OPEN|TARGET.exe
回包：成功
判读：看着对，但同名有两份。

往返2｜动作：写值并回读
kitty_ce op="W|0xADDR|dword|100" confirm=true
kitty_ce op="R|0xADDR|dword" → 100
判读：回读成功，但界面没变。

往返3｜动作：查当前锚点
kitty_ce op=CUR
回包：pid 与预期不符
判读：坐实 —— 写到了另一个实例。

往返4｜动作：按 pid 钉死
kitty_ce op=LP
kitty_ce op=OPEN|<正确pid>
kitty_ce op=CUR
回包：pid 正确
判读：这一步对了。

收敛｜末态验证
kitty_ce op="R|0xADDR|dword" → 期望旧值（写前核）
写入 → 回读 100 → 界面同步变化
末态：写入生效且实例正确。
复盘：同名进程必须按 pid；写前先回读旧值做归属校验。"""),

("我以为要找的是加密算法，其实是编码。",
"""往返1｜动作：按加密处理，找密钥
kitty_patch action=find path=SAMPLE.exe pattern="<SBox 特征>" limit=4
回包：无命中
判读：第一次失败。

往返2｜动作：找循环异或
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<n>-<ts> filter=xor
回包：有 xor 但只在普通逻辑里
判读：第二次失败。

往返3｜动作：先看串的形态
kitty_ce op="R|0xSTR|bytes:32"
回包：字符集是 A-Za-z0-9+/=
判读：坐实 —— Base64，不是加密。

往返4｜动作：解码
kitty_proto action=decode target=<base64 hex>
回包：解出明文 JSON
判读：这一步对了。

收敛｜末态验证
解出的 JSON 字段能对应到界面元素
末态：确认编码而非加密；不需要密钥。
复盘：先看字符集，再谈算法。"""),

("我把 DLL 当 exe 分析，找不到 WinMain。",
"""往返1｜动作：找 WinMain
kitty_ghidra action=analyze target=MODULE.dll
kitty_ghidra action=functions out=logs\\ghidra-mod-<ts> filter=WinMain
回包：无
判读：第一次失败。DLL 没有 WinMain。

往返2｜动作：以为被剥符号
kitty_sym action=exports path=MODULE.dll
回包：有导出
判读：方向错了。

往返3｜动作：改找 DllMain
kitty_ghidra action=functions out=logs\\ghidra-mod-<ts> filter=DllMain
回包：命中
判读：这一步对了。

往返4｜动作：沿导出追业务
kitty_sym action=exports path=MODULE.dll filter=.
kitty_ghidra action=decompile out=logs\\ghidra-mod-<ts> name=<导出名>
回包：业务函数体可读

收敛｜末态验证
kitty_die action=detect target=MODULE.dll → 报 DLL 特征
末态：分析入口改为「导出 + DllMain」，不再找 WinMain。
复盘：先看文件类型（exe/dll）再定入口，别套模板。"""),

("我用 S_CHANGED 收窄，结果候选一直不降。",
"""往返1｜动作：窗口给整模块
kitty_ce op="S_SNAP|bytes:16|0xBASE|0xBASE+SIZE"
kitty_ce op=S_CHANGED
回包：命中数千
判读：第一次失败。整模块里周期性字段太多。

往返2｜动作：以为值类型错，换 bytes
kitty_ce op="S_SNAP|bytes:8|0xBASE|0xBASE+SIZE"
回包：仍数千
判读：第二次失败。问题在窗口不在类型。

往返3｜动作：窗口缩到堆区
kitty_prot action=query addr=0xTARGET
kitty_ce op="S_SNAP|bytes:16|0xALLOC_BASE|0xALLOC_BASE+0x40000"
kitty_ce op=S_CHANGED
回包：n=40
判读：这一步对了。

往返4｜动作：交替两轮
kitty_ce op=S_UNCHANGED
kitty_ce op=S_CHANGED
回包：n=6

收敛｜末态验证
kitty_ce op="S_GET|0|6" → 逐条 R 回读
末态：候选 ≤10 且改值跟随。
复盘：CHANGED 的判别力取决于窗口大小，先缩窗再收窄。"""),

("读一个结构体我按错的对齐读了，字段全乱。",
"""往返1｜动作：按 4 字节对齐读
kitty_ce op="R|0xOBJ|qword"
kitty_ce op="R|0xOBJ+4|dword"
回包：值明显不合理
判读：第一次失败。

往返2｜动作：以为地址错
kitty_prot action=query addr=0xOBJ
回包：Type=MEM_PRIVATE 合法
判读：地址没错，是对齐错。

往返3｜动作：dump 头部看布局
kitty_ce op="MEMDUMP_HEX|0xOBJ|64"
回包：首 8 字节是指向模块的指针
判读：坐实 —— 首字段是 8 字节指针（vtable），整体 8 字节对齐。

往返4｜动作：按 8 字节重读
kitty_ce op="R|0xOBJ|qword"
kitty_ce op="R|0xOBJ+8|dword"
回包：vtable + 合理字段值
判读：这一步对了。

收敛｜末态验证
vtable 指向模块只读区；后续字段自洽
末态：结构对齐确认（8 字节）。
复盘：先 dump 看首个字段宽度，再定对齐。"""),

("我把内存里的 PE 当磁盘 PE 修 IAT，结果全错。",
"""往返1｜动作：按磁盘结构改内存 IAT
kitty_ce op="W|0xIDATA_VA|qword|<修正值>" confirm=true
回包：写入成功但程序崩
判读：第一次失败。内存里的 IAT 是加载器填过的，改它等于破坏已解析地址。

往返2｜动作：以为地址算错
kitty_ce op="R|0xIDATA_VA|qword"
回包：指向 KERNEL32
判读：地址没错，是思路错 —— 内存 IAT 本来就该指向真实地址。

往返3｜动作：改回并改用 dump + unmap
kitty_ce op="W|0xIDATA_VA|qword|<原值>" confirm=true
kitty_dump module=TARGET.exe unmap=true fix_iat=true path=logs\\fixed.bin reference=SAMPLE.exe
回包：一致率 91%
判读：这一步对了。修 IAT 是离线动作，不是运行期动作。

收敛｜末态验证
kitty_sym action=imports path=logs\\fixed.bin → 可解析
末态：离线修好，内存未被动。
复盘：内存 IAT 别改；要修就在 dump 上修。"""),

("我以为样本会联网，抓了半天包什么都没有。",
"""往返1｜动作：直接抓包
kitty_net action=capture port=8080
判据：等 30 秒无流量
判读：第一次失败。

往返2｜动作：以为代理没生效
kitty_net action=status
回包：mitmdump 正常
判读：方向错了。

往返3｜动作：静态核网络能力
kitty_sym action=imports path=SAMPLE.exe
回包：无 ws2_32 / winhttp / wininet
判读：坐实 —— 它根本不联网。

往返4｜动作：改看它到底干什么
kitty_sym action=imports path=SAMPLE.exe
回包：文件 + 注册表 + 进程枚举
判读：这是本地工具。

收敛｜末态验证
kitty_patch action=find path=SAMPLE.exe str=http limit=4 → 0 命中
末态：确认无网络行为，抓包路径作废。
复盘：抓包前先用导入面确认有没有网络能力。"""),

("我在 32 位进程里用 qword 反查，命中爆表。",
"""往返1｜动作：按 8 字节反查
kitty_ce op="P_BACK|0xTARGET|0xSTART|0xSTOP"
回包：200 打满
判读：第一次失败。

往返2｜动作：缩窗口
kitty_ce op="P_BACK|0xTARGET|0xSTART|0xSTART+0x100000"
回包：仍打满
判读：第二次失败。缩窗不解决根本问题。

往返3｜动作：核位数
kitty_ce op=MODENUM
回包：is64=0
判读：坐实 —— 32 位下地址 4 字节，8 字节反查会把相邻字段一起算。

往返4｜动作：按 4 字节思维缩窗（密度翻倍）
kitty_ce op="P_BACK|0xTARGET|0xSTART|0xSTART+0x40000"
回包：OK|7 条
判读：这一步对了。

收敛｜末态验证
kitty_ce op="P_BACK_RES|7" → 逐条 R 回验
末态：链成立。
复盘：反查密度随位数变，32 位窗口要比 64 位更窄。"""),

("我以为要 hook，其实 S_SNAP 就够了。",
"""往返1｜动作：准备注入 DLL 做 hook
kitty_inject dll=<路径> confirm=true
回包：注入成功但目标行为未变
判读：第一次失败。hook 点没选对。

往返2｜动作：换 API 断点
kitty_x64dbg action=seed addr=kernel32.ReadFile seedCmd=log
回包：命中过密，日志淹了
判读：第二次失败。

往返3｜动作：改用内存差分
kitty_prot action=query addr=0xTARGET
kitty_ce op="S_SNAP|bytes:16|0xALLOC_BASE|0xALLOC_BASE+0x40000"
kitty_ce op=S_CHANGED
回包：n=6
判读：这一步对了 —— 不 hook 也能定位。

往返4｜动作：按变化点读值
kitty_ce op="R|0xCHANGED|qword"
回包：目标值

收敛｜末态验证
连续两次触发功能，同一地址跟随变化
末态：数据拿到，零 hook、零注入。
复盘：先试快照差分，hook 是最后手段。"""),

("我把 unsigned 当 signed 写，值绕回负数。",
"""往返1｜动作：写 -1
kitty_ce op="W|0xADDR|dword|-1" confirm=true
回包：被拒（不接受负数）
判读：第一次失败。

往返2｜动作：写 0xFFFFFFFF
kitty_ce op="W|0xADDR|dword|0xFFFFFFFF" confirm=true
kitty_ce op="R|0xADDR|dword"
回包：4294967295
判读：写入成功，界面显示 -1 或极大值 —— 取决于字段符号性。

往返3｜动作：确认字段符号性
kitty_ce op="R|0xADDR-4|dword"
回包：相邻字段形态正常
判读：无符号解释一致。

收敛｜末态验证
值 = 0xFFFFFFFF，界面行为符合预期
归属与权限核对：
```
kitty_prot action=query addr=0xADDR
```
判读：Protect 可写才谈值语义；不可写时先改保护。

末态：按无符号补码写入 + query 显示可写。
复盘：负数一律转补码；界面表现取决于字段符号性。"""),

("我以为 S_GET 返回的是地址，结果它是索引。",
"""往返1｜动作：把地址传给 S_GET
kitty_ce op="S_GET|0x7FF6DAE12340|5"
回包：空 / 报错
判读：第一次失败。第一个参数是索引起点。

往返2｜动作：以为扫描没结果
kitty_ce op=JOB_STAT
回包：n=31
判读：有结果，是我用错参数。

往返3｜动作：按索引取
kitty_ce op="S_GET|0|10"
回包：10 条地址
判读：这一步对了。

往返4｜动作：分页取全
kitty_ce op="S_GET|10|10"
kitty_ce op="S_GET|20|10"
回包：共 31 条

收敛｜末态验证
31 条逐一 R 回读，筛出跟随改值的那一条
末态：取样完成。
复盘：S_GET 是分页取样，不是地址查询。"""),

("我下断点用的地址是上一次会话的，永不命中。",
"""往返1｜动作：复用上次记录的绝对地址
kitty_dbg action=bp addr=0x7FF75FCD1000 access=execute
回包：设置成功，永不命中
判读：第一次失败。ASLR 每次启动都变。

往返2｜动作：以为断点类型错
kitty_dbg action=bp addr=0x7FF75FCD1000 access=write
回包：仍不命中
判读：第二次失败。问题在地址不在类型。

往返3｜动作：取当前 base 重算
kitty_ce op=MODENUM
回包：base=0x7FF6DADB1000
判读：与上次差了一个随机量，坐实。

往返4｜动作：按偏移重下
kitty_dbg action=bp addr=0x7FF6DADB1000+0x1200000 → 0x7FF6DBFB1000
回包：命中
判读：这一步对了。

收敛｜末态验证
kitty_dbg action=regs → 寄存器合理
kitty_dbg action=bp_del → detach → SYNC_STAT 四项 0
末态：断点可用且已清理。
复盘：跨会话只存偏移，不存绝对地址。"""),
]

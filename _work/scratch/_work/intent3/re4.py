# -*- coding: utf-8 -*-
"""re-sft 批次 4：移动/引擎（G2-G15）+ 只读动态观察（H1-H10）+ 符号/差分（I1-I6）。"""

RECORDS = [
    dict(id="re-091", topic="mobile",
         prompt="APK 反编译后怎么快速找到真正的入口 Activity？",
         response="""kitty_jadx action=decompile target=app.apk out=logs/jadx-app
kitty_rea_method path=app.apk class_name=com.example.App method_name=onCreate
判据一：manifest 里带 MAIN/LAUNCHER intent-filter 的 activity 是入口。
判据二：自定义 Application 子类先于 activity 初始化，存在则先看它。
收敛：入口 activity 的 onCreate 里 setContentView 的布局 id 与资源表对上，才是真实首屏。"""),
    dict(id="re-092", topic="mobile",
         prompt="APK 里的 so 怎么确认架构和 JNI 绑定？",
         response="""kitty_rea_android args path=app.apk
kitty_rea_binary inspect_binary_layout path=lib/arm64-v8a/libnative.so
判据一：e_machine=0xB7（AArch64），导出表有 Java_ 前缀符号或 JNI_OnLoad。
判据二：JNI_OnLoad 调用 RegisterNatives，注册表 method name 与 Java 层 native 声明一致。
收敛：没有 Java_ 导出但有 RegisterNatives 时，按注册表里的函数指针定位实现，比按名字找可靠。"""),
    dict(id="re-093", topic="mobile",
         prompt="自家 App 的签名校验怎么定位？",
         response="""kitty_jadx action=search target=app.apk query=getPackageInfo
kitty_apkscan action=scan target=app.apk
判据一：代码里出现 GET_SIGNATURES 或 GET_SIGNING_CERTIFICATES，并与常量签名哈希比较。
判据二：比较结果进入 native 层（JNI 调用），说明有二次校验。
收敛：只在 Java 层的校验改签名即失效；native 校验要跟到 JNI 函数，先确认是否只影响调试构建。"""),
    dict(id="re-094", topic="engine",
         prompt="Unity IL2CPP 的包怎么拿到类结构？",
         response="""kitty_engines action=route path=game_dir
kitty_il2cppdumper action=dump so=libil2cpp.so meta=global-metadata.dat out=logs/il2cpp
判据一：dump 产物里 Assembly-CSharp 的类与方法表完整（类数 > 100）。
判据二：global-metadata.dat 版本与运行时 il2cpp 版本匹配，否则字段偏移错位。
收敛：用 dump 出的 method pointer 在 libil2cpp.so 里定位实现；偏移对不上先核对 metadata 版本。"""),
    dict(id="re-095", topic="engine",
         prompt="Unity Mono 包怎么反编译？",
         response="""kitty_dnspy action=deobf target=Assembly-CSharp.dll out=logs/dnspy-cs
kitty_rea_function procedure=<类型名>::<方法名>
判据一：dnSpy 产物能列出命名空间与类型，方法体可读。
判据二：关键字段有 getter/setter，且被 Update 调用。
收敛：Mono 包逻辑基本明文，先看 Assembly-CSharp 再看热更 dll；混淆过的先 deobf 再读。"""),
    dict(id="re-096", topic="engine",
         prompt="UE 的 pak 怎么解包和看清单？",
         response="""kitty_engines action=route path=game_dir
kitty_fmodel action=list pakDir=game_dir/Content/Paks
判据一：pak 版本与引擎版本匹配（v11 对应 UE5），mount point 可读。
判据二：清单里 .uasset/.uexp 成对出现，总数与 pak 索引一致。
收敛：能列清单再导出；导出后按 mount point 还原目录，缺 uexp 的 uasset 无法独立解析。"""),
    dict(id="re-097", topic="engine",
         prompt="UE 的配置和默认值一般怎么提？",
         response="""kitty_fmodel action=export pak=game_dir/Content/Paks/pakchunk0-WindowsNoEditor.pak out=logs/ue-exp
kitty_ghidra action=strings out=logs/gh-ue limit=600
判据一：Config/Default*.ini 与 .uasset 里的 Default__ 对象属性可读。
判据二：字符串表里的配置键名与 ini 中的键一致。
收敛：ini 是文本优先读；uasset 里的默认值按属性序列化布局解，先拿同版本引擎模板对照。"""),
    dict(id="re-098", topic="engine",
         prompt="Godot 的 pck 怎么提取？",
         response="""kitty_engines action=route path=game_dir
kitty_gdre action=extract target=game.pck out=logs/godot-exp
判据一：pck 头魔数 GDPC，版本字段与引擎版本对应（3.x/4.x）。
判据二：导出后 project.godot 与 .tscn/.gd 可读。
收敛：GDScript 被编译成字节码时用 kitty_gdre action=decompile 还原；4.x 的 .gdc 版本必须匹配。"""),
    dict(id="re-099", topic="engine",
         prompt="Electron 应用怎么还原结构？",
         response="""kitty_rea_javascript input_path=app_dir format=auto
kitty_rea_recover_js path=app.asar output_directory=logs/js-rec extraction_mode=structural
判据一：主进程 main.js 与 preload 脚本的 IPC channel 清单可读。
判据二：渲染进程 bundle 里的路由表与 API base URL 可读。
收敛：先看 IPC 边界再看业务逻辑；node_modules 里的原生 addon 单独按 PE/ELF 处理。"""),
    dict(id="re-100", topic="engine",
         prompt="前端 bundle 带 sourcemap，怎么恢复源码？",
         response="""kitty_rea_recover_js path=dist/app.js output_directory=logs/js-map extraction_mode=structural rewrite_level=standard
kitty_rea_javascript input_path=dist
判据一：sourcemap 的 sources 数组能映射回 .ts/.tsx 路径。
判据二：恢复后的模块 import 关系与 bundle 的 chunk 图一致。
收敛：sourcesContent 缺失时只能还原结构不能还原注释；映射错位说明构建时改了 sourceRoot。"""),
    dict(id="re-101", topic="engine",
         prompt="Lua 脚本被编译成字节码，怎么反编译？",
         response="""kitty_lua action=decompile target=script.luac out=logs/lua-dec
kitty_ghidra action=strings out=logs/gh-lua limit=300
判据一：Luac 头魔数 1B 4C 75 61（\\x1bLua）与版本字节（0x51/0x52/0x53/0x54）。
判据二：反编译产物里函数原型数与原文件常量表条目数一致。
收敛：版本不匹配的反编译器会产出乱码，先按版本字节选工具，再比对常量表校验。"""),
    dict(id="re-102", topic="engine",
         prompt="资源混淆（比如 a.png 实际是布局）怎么建映射？",
         response="""kitty_apktool action=decode target=app.apk out=logs/apk-dec
kitty_rea_android args path=app.apk
判据一：resources.arsc 里的资源名与文件实际内容类型不符（.png 实为二进制 XML）。
判据二：文件头魔数（PK、0x03 0x00 0x08 0x00）能判真实类型。
收敛：按魔数批量重命名后重建资源表；映射表落盘，后续分析直接用映射后的名字。"""),
    dict(id="re-103", topic="mobile",
         prompt="加固 APK 怎么先识别壳类型（只识别）？",
         response="""kitty_apkscan action=scan target=app.apk
kitty_apktool action=decode target=app.apk out=logs/apk-dec
判据一：Application 被替换为壳的 StubApplication，dex 里业务类 < 10 个。
判据二：so 里有壳特征串（libjiagu / libshell / libDexHelper）。
收敛：识别到壳就停，不在壳上硬逆；后续按壳类型决定动态观察还是等解包产物。"""),
    dict(id="re-104", topic="mobile",
         prompt="多渠道包的差异怎么定位？",
         response="""kitty_apktool action=decode target=ch_a.apk out=logs/apk-a
kitty_apktool action=decode target=ch_b.apk out=logs/apk-b
判据一：manifest 的 meta-data（渠道号）不同，其余组件清单一致。
判据二：签名证书相同则同一构建流水线，不同则重签。
收敛：先比 manifest 与资源，再比 dex 哈希；只差渠道字段说明是同一包重签，不是逻辑差异。"""),
    dict(id="re-105", topic="dynamic-readonly",
         prompt="断点命中后怎么快速取寄存器现场？",
         response="""kitty_x64dbg action=seed addr=<module>+0x1234 seedCmd="r" logfile=logs/x64-r.log
kitty_x64dbg action=readlog logfile=logs/x64-r.log
判据一：RIP 等于断点地址（或 +1，int3 残留），RSP 落在栈区。
判据二：RCX/RDX 指向的地址可读（kitty_ce op="R|<rcx>|qword" 不报错）。
收敛：先取参数寄存器，再取栈上第 5 个参数；寄存器值像指针就顺着读一层。"""),
    dict(id="re-106", topic="dynamic-readonly",
         prompt="怎么做只读内存快照对比找变化？",
         response="""kitty_ce op="MEMDUMP_HEX|<addr>|256"
kitty_ce op="MEMDUMP_HEX|<addr>|256"
判据一：两次采样差异字节数 / 总字节数 < 2% 说明该区稳定，可作基线。
判据二：变化集中在 4/8 字节对齐位置，说明是计数器或指针更新，不是代码自改。
收敛：稳定区多次采样取众数作基线；两次采样之间不要下断，避免调试器改写页；变化区标动态字段，不参与特征匹配。"""),
    dict(id="re-107", topic="dynamic-readonly",
         prompt="模块基址每次都不一样，偏移怎么算？",
         response="""kitty_ce op="MODENUM"
kitty_pchain target=0x7FF6DADB1000 mod=app.exe depth=1
判据一：RVA = 绝对地址 - 模块基址，同一版本内 RVA 固定。
判据二：MODENUM 行的 base 与 size 有效（size 为 0 时用镜像头兜底）。
收敛：RVA 写进分析记录，绝对地址只在当次会话有效；跨会话先重取基址，再套 RVA。"""),
    dict(id="re-108", topic="dynamic-readonly",
         prompt="怎么采样找热点函数？",
         response="""kitty_x64dbg action=cmd cmd="pause" confirm=true
kitty_x64dbg action=cmd cmd="r"
判据一：连续 20 次采样中，同一 RIP 区间命中 ≥3 次 → 热点。
判据二：热点地址落在循环体内（向后跳转的目标）。
收敛：热点函数再用 kitty_ida action=decompile 看循环边界；采样少于 20 次不下结论。"""),
    dict(id="re-109", topic="dynamic-readonly",
         prompt="自家 App 的文件读写怎么跟踪？",
         response="""kitty_x64dbg action=seed addr=kernelbase.CreateFileW seedCmd="r" logfile=logs/x64-file.log
kitty_x64dbg action=rununtil artifact=logs/x64-file.log maxRun=20
判据一：命中时 RCX 指向的宽字符串是文件路径。
判据二：路径落在 AppData 或临时目录，且随后有 WriteFile 命中。
收敛：把路径与写入大小配对成文件操作时间线；只跟踪自家进程。"""),
    dict(id="re-110", topic="dynamic-readonly",
         prompt="注册表访问怎么观察？",
         response="""kitty_x64dbg action=seed addr=advapi32.RegOpenKeyExW seedCmd="r" logfile=logs/x64-reg.log
kitty_x64dbg action=readlog logfile=logs/x64-reg.log
判据一：RDX 指向的宽字符串是子键路径，RCX 是 HKEY 值。
判据二：同一路径先 Open 后 SetValue 的顺序出现 → 写配置。
收敛：按路径去重得访问集合；读多写少的键是配置，频繁写的键是状态。"""),
    dict(id="re-111", topic="dynamic-readonly",
         prompt="网络请求是从哪发起的，怎么拿到调用栈？",
         response="""kitty_x64dbg action=seed addr=ws2_32.send seedCmd="kv" logfile=logs/x64-net.log
kitty_x64dbg action=rununtil artifact=logs/x64-net.log maxRun=10
判据一：命中时 kv 栈里第一个业务模块帧即发起层。
判据二：RCX 是 socket，RDX 指向缓冲区，长度在 R8。
收敛：按栈帧逐层回落到业务函数；只对自家进程做，第三方进程不碰。"""),
    dict(id="re-112", topic="dynamic-readonly",
         prompt="怎么清点进程的线程与句柄？",
         response="""kitty_ce op="CUR"
kitty_prot action=query addr=<handle_table_addr> pid=<PID>
判据一：线程数在启动后 5 秒内稳定，突增说明有线程池或注入。
判据二：句柄表里文件句柄数与实际打开路径数一致。
收敛：句柄类型分布突变（如大量 Section）是注入强信号；线程数与句柄数的基线按空跑一次取，别用经验值；只做清点与留档，不做任何处置。"""),
    dict(id="re-113", topic="dynamic-readonly",
         prompt="异常分发链怎么观察？",
         response="""kitty_x64dbg action=seed addr=ntdll.KiUserExceptionDispatcher seedCmd="kv" logfile=logs/x64-seh.log
kitty_x64dbg action=readlog logfile=logs/x64-seh.log
判据一：分发链上第一个 handler 地址落在栈区（SEH 帧）还是 .pdata（表驱动）。
判据二：handler 返回 CONTINUE_SEARCH 会继续向上，返回 CONTINUE_EXECUTION 则恢复。
收敛：按返回值判断谁处理了异常；链上出现重复 handler 说明有嵌套注册。"""),
    dict(id="re-114", topic="dynamic-readonly",
         prompt="怎么把一次运行做成时间线？",
         response="""kitty_trail action=append step=start text="proc start" target=app.exe
kitty_x64dbg action=seed addr=kernelbase.CreateFileW seedCmd="r" logfile=logs/x64-tl.log
判据一：每条事件带单调时间戳（用 QueryPerformanceCounter 采样对齐）。
判据二：事件顺序与文件/网络/注册表操作的因果一致（先读配置再连网）。
收敛：时间线只留可复现事件，噪声采样单独存；跨会话对比用相对时间。"""),
    dict(id="re-115", topic="symbols",
         prompt="导出符号怎么恢复得全一点？",
         response="""kitty_sym action=exports source=file path=lib.dll limit=500
kitty_sym action=exports source=mem module=lib.dll limit=500
判据一：内存导出表比磁盘多（运行期注册），差集即延迟注册的符号。
判据二：导出地址落在代码节，名字符合 C++ 修饰规则（?func@@YAXXZ）。
收敛：修饰名 demangle 还原签名；无名导出按序号锚定，跨版本用差分校准。"""),
    dict(id="re-116", topic="symbols",
         prompt="导入符号怎么按能力分类？",
         response="""kitty_sym action=imports source=file path=s.exe limit=300
kitty_ida action=imports out=logs/ida-s
判据一：按 DLL 分组后，网络（ws2_32/wininet）、加密（bcrypt/crypt32）、进程（kernel32）三类占比可算。
判据二：出现仅少数样本使用的敏感 API（如 NtUnmapViewOfSection）时单独标记。
收敛：分类表落盘，作为行为画像一维；单看导入不能定性，要与字符串和调用图交叉。"""),
    dict(id="re-117", topic="symbols",
         prompt="怎么找某个字符串在哪里被用？",
         response="""kitty_ida action=strings out=logs/ida-app filter=<关键字> limit=20
kitty_ida action=xrefs out=logs/ida-app filter=<串地址>
kitty_ida action=decompile out=logs/ida-app name=<引用函数>
判据一：字符串地址被 mov 到寄存器后作为参数传入调用。
判据二：引用点所在函数与字符串语义一致（错误串在错误处理分支）。
收敛：一个串多处引用时按调用图分组，先看启动路径上的那处。"""),
    dict(id="re-118", topic="symbols",
         prompt="两个版本的函数怎么对齐做差分？",
         response="""kitty_ida action=analyze target=v1.dll out=logs/ida-v1
kitty_ida action=analyze target=v2.dll out=logs/ida-v2
kitty_rea_compare left=<v1_fn> right=<v2_fn>
判据一：相似度 > 0.9 的函数直接复用旧命名。
判据二：相似度 0.6-0.9 且基本块数变化 → 逻辑改动，需人工看新增分支。
收敛：先按导出名对齐，再按字符串引用对齐，最后按调用图对齐；三轮都失败才手工。"""),
    dict(id="re-119", topic="symbols",
         prompt="怎么追一条从入口到目标的调用路径？",
         response="""kitty_rea_callpath start=<入口符号> goal=<目标符号> direction=forward
kitty_ida action=xrefs out=logs/ida-app filter=<中间函数>
判据一：路径上每一跳都有直接 call 或 tail jump 支撑。
判据二：路径长度 < 12 跳，超过则可能是间接调用断链。
收敛：间接调用（寄存器/虚表）要单独标注，不能当确定路径；用动态断点验证一次。"""),
    dict(id="re-120", topic="symbols",
         prompt="某个配置串在哪些模块被引用，怎么一次追完？",
         response="""kitty_rea_trace query=<配置串>
kitty_ida action=strings out=logs/ida-app filter=<配置串> limit=8
判据一：trace 结果里出现跨模块引用（主程序 + 插件 dll）。
判据二：每个引用点上下文都是读取（mov 后比较），没有写入。
收敛：按模块汇总引用点，写入点单独列；只读引用说明该串是外部配置键，改配置即可验证。"""),
]

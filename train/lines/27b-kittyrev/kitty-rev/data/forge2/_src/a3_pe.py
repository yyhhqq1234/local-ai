# -*- coding: utf-8 -*-
"""forge2 A3 · PE 未覆盖分支（30 条）。与 forge r1 的 120 条 PE 行错开角度：只写它没碰的次级结构。"""
GROUP = "A"
CAT = "kb-re"

ROWS = [
    ("pe-tls-multi",
     "TLS 目录里 AddressOfCallBacks 有两个回调，DLL 进程附着时都会跑吗？",
     "都会跑，按数组顺序，以 0 结尾。判据：`readelf` 不认 PE，用 `python -c \"import pefile;d=pefile.PE(f);"
     "print(hex(d.OPTIONAL_HEADER.DATA_DIRECTORY[9].VirtualAddress))\"` 取 TLS 目录 RVA，"
     "再按 0x28 字节步长读回调数组；数组项 ≥2 且第二项非 0 即两回调。DLL 场景多一次 THREAD_ATTACH（reason=2）。"),
    ("pe-tls-index",
     "TLS 目录的 AddressOfIndex 指向哪，取值有什么意义？",
     "它指向一个 DWORD 槽，加载器把本次分配的 TLS 槽位号写进去（通常 0 起递增）。判据："
     "该 DWORD 初始值为 0，进程加载多个带 TLS 的模块后变成非 0 小整数（< 1088）；"
     "若静态值已是 0xFFFFFFFF，说明构建时预留未初始化，运行时才被改写。"),
    ("pe-delay-attrs",
     "延迟导入描述符里 grAttrs 这一位到底管什么？",
     "管描述符字段是 RVA 还是 VA：grAttrs 最低位=1 表示字段为 RVA（新版链接器默认），=0 表示 VA（老式）。"
     "判据：`python -c \"import pefile;d=pefile.PE(f);print(d.DIRECTORY_ENTRY_DELAY_IMPORT)\"` 若解析出的名字是乱码，"
     "就是 grAttrs 判反了；手工按 0x20 字节步长读 ImgDelayDescr 时先看偏移 0 的 Attributes。"),
    ("pe-delay-unload",
     "延迟导入里有个 Unload 标志，什么时候会主动卸库？",
     "看 Delay Import 的 dlattr 中 dlattrNoUnload 位（0x1 的反位语义按链接器文档）：未设 NoUnload 时，"
     "进程/线程退出会调用 FreeLibrary。判据：静态看描述符偏移 0 的低字节，0x1 表示字段为 RVA、0x2 表示 NoUnload；"
     "运行时验证在 `kernel32!FreeLibrary` 下断，看调用栈是否来自 delayimp 的 thunk。"),
    ("pe-bound-ts",
     "Bound Import 里的时间戳和 DLL 的时间戳对不上，说明什么？",
     "说明绑定信息已过期，加载器会回退到按名字解析。判据：`python -c \"import pefile;d=pefile.PE(f);"
     "print(d.DIRECTORY_ENTRY_BOUND_IMPORT)\"` 输出的 TimeDateStamp 与目标 DLL 的 FileHeader.TimeDateStamp 不等 → 失效；"
     "此时 IAT 里的地址只是链接时的快照，运行时会被重写。"),
    ("pe-debug-cleared",
     "Debug 目录被清零了，还能不能找到原始 PDB 路径？",
     "能，先看节名与残留：`strings -a sample.exe | findstr /i \".pdb\"` 常在 .rdata 里留下构建路径；"
     "若为空，再扫 overlay 里的 CodeView 记录（签名 RSDS + 16 字节 GUID + 4 字节 age）。判据："
     "`xxd sample.exe | findstr RSDS` 命中即说明调试目录是被摘链而非物理删除。"),
    ("pe-mixedmode",
     ".NET 混编（C++/CLI）的 PE 有什么结构特征？",
     "两套头并存：CLR 目录非 0（COM descriptor 指向 COR20 header），同时 .text 里有原生 x64 代码。判据："
     "`python -c \"import pefile;d=pefile.PE(f);print(d.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress)\"` 非 0，"
     "且 `dumpbin /headers` 的 CLR Header 里 Flags 含 ILONLY=0；`kitty_ida` 打开会同时给出 IL 与原生函数。"),
    ("pe-rtor",
     ".NET ReadyToRun 和普通 IL 怎么区分？",
     "看 COR20 header 的 ManagedNativeHeader 目录（偏移 0x40）非 0 即 R2R。判据："
     "该目录指向 READYTORUN_HEADER，前 4 字节签名 0x00525452（'RTR'）；普通 IL 该字段为 0。"
     "辅以 `kitty_dnspy` 打开：R2R 的程序集方法体显示为 native stub 而非 IL。"),
    ("pe-res-nested",
     ".rsrc 里嵌了一个完整 PE，怎么确认而不是误判成数据？",
     "按资源条目取原始字节后验头：`python -c \"import pefile;d=pefile.PE(f);"
     "print([(e.id,e.directory) for e in d.DIRECTORY_ENTRY_RESOURCE.entries])\"` 找到 RT_RCDATA，导出该块后看前两字节 MZ、"
     "偏移 0x3C 的 e_lfanew 指向 PE\\0\\0。判据：e_lfanew < 0x400 且该处四字节为 0x00004550 才算内嵌 PE。"),
    ("pe-res-depth",
     "资源目录层级很浅但条目很多，正常吗？",
     "正常，深度固定三层（类型/名称/语言）。判据：`pefile` 遍历时每层 directory 的 NumberOfEntries 之和 ≈ 条目数；"
     "若第二层直接出现 lang id（0x409/0x804）而缺名称层，说明构建工具做了扁平化，资源编辑器会显示异常但加载不受影响。"),
    ("pe-loadcfg-cfg",
     "Load Config 里的 CFG 表怎么判断有效性？",
     "三个字段互相约束：GuardFlags 含 0x100（CF_INSTRUMENTED）、GuardCFFunctionTable 非 0、GuardCFFunctionCount > 0。"
     "判据：表项为 4 字节 RVA（含 FID 表时为 5 字节对齐），项数 × 4 ≈ 表大小；三者不齐时系统忽略 CFG。"),
    ("pe-loadcfg-xfg",
     "XFG（间接调用目标校验）在文件里怎么体现？",
     "GuardFlags 的 0x40000 位与 GuardAddressTakenIatEntryTable 非 0。判据："
     "`dumpbin /loadconfig sample.exe` 输出里 XFG 相关表存在且计数 > 0；只有 CFG 没有 XFG 时，"
     "间接调用只校验函数起点，不校验 IAT 取址。"),
    ("pe-pdata-missing",
     "64 位 PE 没有 .pdata，异常展开靠什么？",
     "没有 unwind 信息就只能靠帧指针链或启发式。判据：`readelf` 不适用，`python -c \"import pefile;"
     "d=pefile.PE(f);print(d.OPTIONAL_HEADER.DATA_DIRECTORY[3].Size)\"` 为 0（异常目录空）且节表无 .pdata；"
     "此时崩溃栈只能到模块+偏移，`kitty_dump` 拿到镜像后要自己按 prologue 模式扫。"),
    ("pe-seh-x86",
     "32 位 PE 的 SEH 链怎么静态看出来？",
     "看 FS:[0] 的安装点：搜 `64 A1 00 00 00 00`（mov eax,fs:[0]）与随后的 `push eax`。判据："
     "`objdump -d -M intel sample.exe | grep -c 'fs:0x0'` ≥ 1；再跟 `push <handler>` 的立即数即异常处理函数地址，"
     "64 位没有这条链（改用 .pdata）。"),
    ("pe-fwd-chain",
     "导出转发链能有多长，怎么判断终点？",
     "转发字符串形如 `KERNEL32.Sleep`，指向另一个模块。判据：`python -c \"import pefile;"
     "d=pefile.PE(f);print([(e.name,e.forwarder) for e in d.DIRECTORY_ENTRY_EXPORT.symbols if e.forwarder])\"`，"
     "终点是 forwarder 为空、ordinal 落在本模块内的那条；链长 > 3 时加载器会报 127。"),
    ("pe-apiset",
     "导入表里 api-ms-win-* 这类契约名，实际由谁提供？",
     "由 API Set 解析到真实 DLL：`api-ms-win-core-file-l1-1-0.dll` → kernelbase/kernel32。判据："
     "`python -c \"import pefile;d=pefile.PE(f);print([e.dll for e in d.DIRECTORY_ENTRY_IMPORT])\"` 出现 api-ms-win 前缀，"
     "而磁盘上无同名文件；用 `dumpbin /dependents` 也是这些名字，属于正常现代构建。"),
    ("pe-sect-align",
     "SectionAlignment 和 FileAlignment 不一致会导致什么？",
     "加载器按 SectionAlignment 映射，文件按 FileAlignment 对齐；两者不等时 PointerToRawData 必须按 FileAlignment 取整。"
     "判据：`python -c \"import pefile;d=pefile.PE(f);print(d.OPTIONAL_HEADER.SectionAlignment,d.OPTIONAL_HEADER.FileAlignment)\"`，"
     "常见 (0x1000, 0x200)；若 FileAlignment < 0x200 且某节 PointerToRawData % 0x200 != 0，加载会失败。"),
    ("pe-rawsize-zero",
     "某节 SizeOfRawData 为 0 但 VirtualSize 很大，是什么？",
     "未初始化数据段（等价 .bss）：文件里不占空间，加载时按 VirtualSize 清零。判据："
     "节 Characteristics 含 IMAGE_SCN_CNT_UNINITIALIZED_DATA（0x80），PointerToRawData 常为 0；"
     "`dumpbin /section:.bss` 可见 VirtualSize > 0 而 RawSize = 0。"),
    ("pe-import-ordinal",
     "只有序号没有名字的导入，怎么还原成 API？",
     "按 DLL 的导出序号表反查：`python -c \"import pefile;d=pefile.PE('kernel32.dll');"
     "print([(s.ordinal,s.name) for s in d.DIRECTORY_ENTRY_EXPORT.symbols][:5])\"`，用 import 的 ordinal 匹配。"
     "判据：同一 ordinal 在不同 Windows 版本可能指向不同函数（尤其 ntdll），跨版本还原必须用目标机的 DLL。"),
    ("pe-rich",
     "Rich header 能读出什么？",
     "编译器与链接器的构建号序列：`python -c \"import pefile;d=pefile.PE(f);print(d.RICH_HEADER.values if d.RICH_HEADER else None)\"`。"
     "判据：每一对 (prodid, build) 对应一个工具版本；Rich 头被抹时该字段为 None 而 DOS stub 仍存在 —— 这才是"
     "「被处理过」的信号，别把正常的无 Rich（mingw 产物）当异常。"),
    ("pe-checksum",
     "校验和字段为 0，是不是样本被改过？",
     "不一定：非驱动、非系统 DLL 的链接器可以不算校验和。判据：`python -c \"import pefile;d=pefile.PE(f);"
     "print(hex(d.OPTIONAL_HEADER.CheckSum), d.verify_checksum())\"`；verify 为 False 且 CheckSum=0 属正常构建，"
     "若 CheckSum 非 0 但 verify 为 False，才是改过字节没重算。"),
    ("pe-auth-overlay",
     "签名在 overlay 里，怎么确认覆盖范围？",
     "看 Security 目录（数据目录第 4 项）的 VirtualAddress/Size：它是**文件偏移**不是 RVA。判据："
     "`python -c \"import pefile;d=pefile.PE(f);s=d.OPTIONAL_HEADER.DATA_DIRECTORY[4];print(hex(s.VirtualAddress),s.Size)\"`，"
     "该偏移处应为 0x00000000 长度前缀的 WIN_CERTIFICATE；Size 与文件尾距离相等即签名覆盖到末尾。"),
    ("pe-manifest-uac",
     "manifest 里 requestedExecutionLevel 有哪几档，怎么读？",
     "三档：asInvoker / highestAvailable / requireAdministrator。判据：资源 RT_MANIFEST(24) 的 XML 里 "
     "`<requestedExecutionLevel level=\"...\">`；`kitty_die` 或 `strings -el sample.exe | findstr /i requestedExecutionLevel` "
     "能直接捞到 UTF-16 串，长度通常 60-120 字节。"),
    ("pe-icon-group",
     "RT_ICON 有 47 个而 RT_GROUP_ICON 只有 1 个，怎么对应？",
     "GROUP_ICON 是一张索引表：每项 14 字节（宽高/色数/位深/大小/资源 ID）。判据："
     "`python -c \"import pefile;d=pefile.PE(f);print([(e.id,len(e.directory.entries)) for e in "
     "d.DIRECTORY_ENTRY_RESOURCE.entries if e.id==14])\"`，条目数 × 14 + 6 应等于该资源大小；"
     "ID 与 RT_ICON 的 id 一一对应。"),
    ("pe-dialog-tmpl",
     "RT_DIALOG 是二进制模板，怎么解析出控件？",
     "按 DLGTEMPLATE 结构走：style(4) exstyle(4) cdit(2) 后跟变长菜单/类/标题串（UTF-16，双 0 结束），"
     "再是 DLGITEMTEMPLATE 数组（每项 18 字节 + 变长串，按 DWORD 对齐）。判据："
     "cdit 与后续条目数必须相等；`kitty_ida` 的 resource 视图能直接渲染，手写解析器时对齐错了会读出乱码标题。"),
    ("pe-stringtable",
     "RT_STRING 的块编号怎么换算成字符串 ID？",
     "块号 n 覆盖 ID 区间 [n*16, n*16+15]，块内 16 个 UTF-16 串以长度前缀（WORD）串接，空串长度为 0。判据："
     "块内偏移累加时遇 len=0 直接跳到下一个；`python pefile` 里 entry.name.string 即块号，"
     "按 (块号-1)*16 + 序位 得 ID。"),
    ("pe-version-block",
     "VS_VERSION_INFO 里有两个语言块，取哪个？",
     "取与资源 LANG 一致的那个；两者都存在时优先 0x409（en-US）。判据：`python -c \"import pefile;"
     "d=pefile.PE(f);print(d.VS_VERSIONINFO if hasattr(d,'VS_VERSIONINFO') else None)\"`，"
     "结构为 VS_FIXEDFILEINFO(52 字节) + StringFileInfo + VarFileInfo；文件版本在 FixedFileInfo 的 dwFileVersionMS/LS。"),
    ("pe-section-discard",
     "节属性里有 MEM_DISCARDABLE，说明什么？",
     "该节加载后可被系统丢弃（如 .reloc 之外的一次性初始化数据）。判据：Characteristics 含 "
     "IMAGE_SCN_MEM_DISCARDABLE(0x02000000)；带此标志的节在内存里读到的可能是 0，"
     "静态分析要回文件读，不能只看 `kitty_dump` 的映像。"),
    ("pe-iat-outside",
     "IAT 里出现一个指向堆的地址，怎么判断是不是运行时填的？",
     "先比文件与内存：文件里该项为 0 或指向 hint/name，内存里变成模块内地址 → 运行时填。判据："
     "`kitty_dualview` 同址取 R 与 KM_R，两值不同且都非 0 说明有写入者；再用 "
     "`P_BACK|0x<iat项地址>|0x<模块基址>|0x<模块尾>` 反查谁持有该指针。"),
    ("pe-sxsp",
     "怎么确认样本用了 SEH 还是 VEH？",
     "VEH 走 `AddVectoredExceptionHandler` 导入，SEH 走 FS:[0] 或 .pdata。判据："
     "`python -c \"import pefile;d=pefile.PE(f);print([i.name for i in d.DIRECTORY_ENTRY_IMPORT "
     "if i.dll.lower().startswith(b'kernel32')])\"` 中出现 AddVectoredExceptionHandler；"
     "配合 0x1 参数（FirstHandler）即可判定优先于 SEH。"),
    ("pe-tls-vs-dllmain",
     "TLS 回调和 DllMain 谁先执行？",
     "进程附着时 TLS 回调先于 DllMain（加载器先跑 TLS，再调入口）。判据："
     "断 `ntdll!LdrpCallTlsInitializers` 与 `ntdll!LdrpRunInitializeRoutines` 的先后；"
     "静态侧看 TLS 目录 AddressOfCallBacks 非 0 即可预判「入口点之前还有一段代码」。"),
]

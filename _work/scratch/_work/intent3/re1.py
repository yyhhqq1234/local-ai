# -*- coding: utf-8 -*-
"""re-sft 批次 1：静态分诊与加壳/编译器指纹（A1-A20）+ PE/ELF 结构（B1-B10）。"""

RECORDS = [
    dict(id="re-001", topic="static-triage",
         prompt="一个 exe 双击闪退，怀疑加壳，但节表看着正常，怎么定性？",
         response="""kitty_patch action=info path=notepad2.exe
kitty_die   action=scan target=notepad2.exe
判据一：info 里任一节 VirtualSize/SizeOfRawData > 3，且该节 Characteristics 含 0xE0000020（RWX），定加密壳。
判据二：die 回 packer 非空、compiler 为空，说明编译器指纹被壳盖掉。
两条同时成立再 kitty_ghidra action=analyze target=notepad2.exe out=logs/gh-np2，函数数 < 300 且入口函数没有 push rbp; mov rbp,rsp 序言，即入口在壳里。
收敛：OEP 落地后重跑 analyze，函数数应跳到原程序量级（通常 > 800）。"""),
    dict(id="re-002", topic="static-triage",
         prompt="样本报 UPX，常规脱壳工具却说 not packed by UPX，怎么判断是被二次处理过？",
         response="""kitty_patch action=find path=a.exe str=UPX! limit=16
kitty_patch action=find path=a.exe str=UPX0 limit=8
kitty_patch action=info path=a.exe
判据一：UPX! 命中 ≥1、UPX0 节名存在，但 info 显示该节 SizeOfRawData=0 —— 节名留着、数据被搬走，属于改头后的二次压缩。
判据二：overlay 长度 = 文件长度 - (最后节 PointerToRawData + SizeOfRawData)，该值 > 0 且这段熵接近 8，说明主体在附加区。
收敛：按 overlay 起点切出后对其单独跑 kitty_patch action=info，节表自洽才是可独立分析的 PE。"""),
    dict(id="re-003", topic="static-triage",
         prompt="一个 dll 反汇编出来几乎全是跳板，是不是 .NET 的？",
         response="""kitty_patch action=info path=agent.dll
kitty_sym   action=imports path=agent.dll limit=120
判据一：DataDirectory[14]（CLR）的 VirtualAddress/Size 非 0，且 Size ≥ 0x48。
判据二：imports 里出现 _CorDllMain 或 _CorExeMain，同时没有正常 CRT 初始化符号。
两条都中即托管程序集，native 入口不用跟。转 kitty_dnspy action=deobf target=agent.dll out=logs/dnspy-agent。
收敛：产物里能列出命名空间与类型数，且 kitty_ida action=entries out=logs/ida-agent 的入口 RVA 与 CLR 头 EntryPointToken 对得上。"""),
    dict(id="re-004", topic="static-triage",
         prompt="这个服务端 exe 导入表只有十几个函数，是不是 Go 静态链接的？",
         response="""kitty_patch action=find path=svc.exe pattern="FF FF FF FF 00 00 47 6F" limit=4
kitty_sym   action=imports path=svc.exe limit=200
判据一：命中偏移 +0x0E 起是可读的 go1.x 版本串（buildinfo 结构）。
判据二：导入总数 < 30 且集中在 kernel32/ws2_32，没有 msvcr* 系列。
两条同中即 Go 静态链接。kitty_ghidra action=functions out=logs/gh-svc 里会出现 runtime.*、main.* 命名。
收敛：从 main.main 的 xref 向上找 lang_start，其第二参数就是业务入口地址。"""),
    dict(id="re-005", topic="static-triage",
         prompt="判断一个工具是不是 Rust 写的，除了看图标还能怎么确认？",
         response="""kitty_patch action=find path=tool.exe str=rustc limit=8
kitty_patch action=find path=tool.exe str=library/std/src/panicking.rs limit=4
判据一：两条字符串都存在（编译器版本串 + panic 路径），基本可定 Rust。
判据二：kitty_sym action=imports path=tool.exe 里没有 __CxxFrameHandler3，排除 MSVC C++ 主导。
收敛：kitty_ghidra action=functions 找 core::panicking::panic_fmt，从它的 xref 反推调用者，通常落在 lang_start 包住的 main wrapper 上。"""),
    dict(id="re-006", topic="static-triage",
         prompt="打包成单文件的 Python 程序，怎么从二进制里确认并找到归档？",
         response="""kitty_patch action=find path=app.exe pattern="22 4D 45 49 0C 0B 0A 0B 0E" limit=4
kitty_die   action=scan target=app.exe
判据一：CArchive 魔数命中且偏移 < 0x200000（一般落在 PE 覆盖层起始处）。
判据二：die 回 compiler=unknown，因为入口是 bootloader 而不是编译器产物。
收敛：按魔数偏移读 CArchive 头（magic, lengthofPackage, toc, tocLen, pyver），TOC 里出现 PYZ-00.pyz 与若干 .pyc 即结构对齐；对不上就换打包器假设。"""),
    dict(id="re-007", topic="static-triage",
         prompt="怎么在不装额外工具的情况下判断某个节是不是加密数据？",
         response="""kitty_patch action=info path=packed.exe
kitty_ce    op="MEMDUMP_HEX|0x7FF6DADB1000|4096"
判据一：按 256 字节统计字节分布估熵；单节熵 > 7.2 且该节可写可执行 → 加密/压缩载荷；6.5-7.2 且只读 → 正常代码或高压缩资源。
判据二：同一节两次 MEMDUMP_HEX 采样内容不同（运行时自解码），配合 kitty_prot action=query addr=<节VA> 看保护位是否 RWX。
收敛：熵高的节用 kitty_ghidra action=strings 看有没有可读常量，全无则按数据节处理，不再跟反汇编。"""),
    dict(id="re-008", topic="static-triage",
         prompt="导入表只有四个函数，正常吗？",
         response="""kitty_sym action=imports path=s.exe limit=200
kitty_ida action=imports out=logs/ida-s
判据一：导入总数 < 15 且集中在 LoadLibraryA/GetProcAddress/VirtualAlloc/VirtualProtect → 运行时解析。
判据二：ida 产物里 IAT 大小与 kitty_patch action=info 的 DataDirectory[1].Size 差 > 0x40 → 导入表被动过。
两条都中时，kitty_ghidra action=search out=logs/gh-s filter=GetProcAddress 找解析调用点，单函数内 > 50 次即批量循环。
收敛：解析循环引用到的字符串表就是真实 API 清单，导出后按名字重建导入。"""),
    dict(id="re-009", topic="static-triage",
         prompt="程序在 main 之前就退出了，怀疑 TLS 回调里有检查，怎么验证？",
         response="""kitty_patch action=info path=t.exe
kitty_ida   action=entries out=logs/ida-t
判据一：DataDirectory[9]（TLS）RVA 非 0，entries 里 AddressOfCallBacks 指向的地址在最后一个节内。
判据二：该回调函数调用了 IsDebuggerPresent 或 NtQueryInformationProcess。
两条都中即启动期检查布在 TLS 阶段，main 根本没机会跑。收敛：回调地址与 OEP 比较，回调在 OEP 之前且所在节可写，进一步支持壳的判断。"""),
    dict(id="re-010", topic="static-triage",
         prompt="资源节比正常大很多，里面是不是藏了另一个 PE？",
         response="""kitty_patch action=find path=rsrc.exe pattern="4D 5A 90 00 03 00 00 00" limit=32
kitty_patch action=info path=rsrc.exe
判据一：MZ 头命中 ≥2，且第二个命中偏移落在 .rsrc 节范围（PointerToRawData 到 +SizeOfRawData）内。
判据二：该偏移 +0x3C 的 e_lfanew 指向的 PE 签名可读（PE\\0\\0）。
收敛：按偏移切出子文件，对子文件跑 kitty_patch action=info，节数 3-12、对齐合法即独立载荷。"""),
    dict(id="re-011", topic="static-triage",
         prompt="两个样本代码一样但哈希不同，怎么确认只是头部被改？",
         response="""kitty_patch action=hash path=v1.exe
kitty_patch action=info path=v1.exe
判据一：TimeDateStamp=0 或与文件 mtime 相差超过 1 年 → 链接后被重写。
判据二：DataDirectory[4]（Security）Size=0 而样本本该带签名 → 签名被剥。
收敛：对两版逐节算哈希（info 拿节偏移，按节切出后 hash），若 .text 一致、只有头与 .rdata 不同，说明是改头而不是重编译。"""),
    dict(id="re-012", topic="static-triage",
         prompt="怎么判断程序是批量动态解析 API 而不是正常导入？",
         response="""kitty_ida action=analyze target=d.exe out=logs/ida-d
kitty_ida action=functions out=logs/ida-d filter=GetProcAddress
kitty_ida action=xrefs out=logs/ida-d filter=<候选地址>
判据一：单函数内 xref 数 > 30，且每次调用前有 mov rdx, <字符串VA> 的模式。
判据二：该函数被 TLS 回调或 DllMain 引用（入口前执行）。
收敛：把解析函数用到的字符串表 dump 出来就是完整 API 清单；与 imports 求差集，差集即隐藏能力。"""),
    dict(id="re-013", topic="static-triage",
         prompt="怎么快速判断一个 exe 还留着调试符号？",
         response="""kitty_patch action=find path=m.exe str=.pdb limit=4
kitty_patch action=find path=m.exe str=RSDS limit=4
判据一：RSDS 后跟 16 字节 GUID + 4 字节 age + 以 .pdb 结尾的路径串，结构完整。
判据二：kitty_ida action=functions out=logs/ida-m 里出现非 sub_ 前缀的函数名。
收敛：符号可用就直接按名字定位，省掉字符串与调用图推断；符号与二进制不匹配（GUID 对不上）时只能信 RVA。"""),
    dict(id="re-014", topic="static-triage",
         prompt="不运行程序，怎么判断它是用哪个版本的 MSVC 编的？",
         response="""kitty_sym action=imports path=o.exe limit=200
kitty_patch action=find path=o.exe str=Rich limit=2
判据一：Rich 头里每个 (prodid<<16)|build 的 build 号能映射到 VS 版本（如 30729 → VS2019 16.x）。
判据二：导入的 CRT 版本与映射结果一致（vcruntime140 与 140_1 对应不同小版本）。
收敛：kitty_ghidra action=analyze 看 __security_init_cookie 的调用形态，与编译选项 /GS 对齐后版本判断才可信。"""),
    dict(id="re-015", topic="static-triage",
         prompt="壳的入口单步到 pushad 结束，怎么从栈上找原始返回地址？",
         response="""kitty_x64dbg action=seed addr=<entry> seedCmd="dd rsp, L20" logfile=logs/x64-oep.log
kitty_x64dbg action=readlog logfile=logs/x64-oep.log
判据一：连续 4 个栈值都落在映像代码节范围内 → 这段是壳保存的返回链。
判据二：其中第一个不在壳节内的地址，其前 3 字节为 55 48 8B（push rbp; mov rbp,rsp）→ OEP 候选。
收敛：对候选地址 kitty_ce op="R|<候选>|bytes:8" 取前 8 字节确认序言，再下断确认能命中业务代码。"""),
    dict(id="re-016", topic="static-triage",
         prompt="有个节同时可写可执行，正常吗？",
         response="""kitty_patch action=info path=x.exe
kitty_prot   action=query addr=<节VA> pid=<PID>
判据一：info 里该节 Characteristics=0xE0000020（RWE）。
判据二：运行时 query 回 Protection=RWX 且 Type=MEM_IMAGE。
两条都中说明有自修改代码或解壳循环。收敛：对该节两次 kitty_ce op="R|<节VA+0x100>|bytes:16" 采样，内容变化即确认自解码，按壳处理而非误报。"""),
    dict(id="re-017", topic="static-triage",
         prompt="静态看导入表是空的，但程序明明调用了网络 API，怎么回事？",
         response="""kitty_patch action=info path=n.exe
kitty_sym   action=imports source=mem module=n.exe limit=200
判据一：DataDirectory[1] 指向的区域全 0 或落在节外（按 RVA 换算文件偏移后取 128 字节看）。
判据二：source=mem 能列出真实导入（运行时重建）。
收敛：对比静态与内存两份导入，差集就是被隐藏的 API；再 kitty_ghidra action=search filter=LdrLoadDll 找重建函数。"""),
    dict(id="re-018", topic="static-triage",
         prompt="怎么快速确认样本带反调试检查？",
         response="""kitty_ghidra action=strings out=logs/gh-x limit=400
kitty_ida    action=strings out=logs/ida-x limit=400
判据一：IsDebuggerPresent / NtQueryInformationProcess / CheckRemoteDebuggerPresent 三个串命中 ≥2。
判据二：引用点集中在入口后 200 条指令内（启动期检查），而不是分散在业务路径。
收敛：kitty_ida action=xrefs filter=<串地址> 定位引用函数；这是识别，处置按项目策略决定（跳过/改分支/换环境）。"""),
    dict(id="re-019", topic="static-triage",
         prompt="怎么确认这个样本的签名是真的还是被重打包过？",
         response="""kitty_patch action=info path=p.exe
kitty_ce    op="MEMDUMP_HEX|<security_off_map>|256"
判据一：Security 目录 dwLength 与 DataDirectory[4].Size 相差 ≤8，wRevision=0x0200 → 有 PKCS#7。
判据二：TimeDateStamp 与证书 notBefore/notAfter 区间不重叠 → 签名后文件被改过。
收敛：把证书段切出做链校验；签名者与预期发布者不符时，即使哈希能过也按重打包处理。"""),
    dict(id="re-020", topic="static-triage",
         prompt="整体熵很高但代码节看起来正常，怎么判断高熵来自哪里？",
         response="""kitty_patch action=info path=b.exe
kitty_ce    op="MEMDUMP_HEX|<overlay_addr>|4096"
判据一：整体熵 > 7.5 而 .text 熵 < 6.8 → 高熵不是代码。
判据二：overlay 起点 = 最后节 PointerToRawData + SizeOfRawData，该偏移之后长度 > 0 且熵 > 7.9。
收敛：按 overlay 切出单独分析，若切出体是压缩流（zlib 头 78 9C / gzip 1F 8B）则优先解压再看内容。"""),
    dict(id="re-021", topic="pe-elf",
         prompt="PE 头里 SizeOfImage 和节表对不上，会有什么后果？",
         response="""kitty_patch action=info path=a.exe
kitty_rea_binary inspect_binary_layout path=a.exe
判据一：SizeOfImage 应等于最后节 VA + 按 SectionAlignment 向上取整的 VirtualSize，差 > 0x1000 说明头被改。
判据二：SizeOfHeaders 必须是 FileAlignment 整数倍，否则部分加载器直接拒绝。
收敛：两工具输出一致才继续；不一致时以节表为准重算 SizeOfImage，再用 kitty_dump action=unmap 验证重建镜像能否对齐。"""),
    dict(id="re-022", topic="pe-elf",
         prompt="样本加载基址每次都一样，是没开 ASLR 吗？",
         response="""kitty_patch action=info path=x.exe
kitty_ce    op="MODENUM"
判据一：DataDirectory[5]（BaseReloc）Size=0 且 Characteristics 含 0x0001（RELOCS_STRIPPED）→ 不能重定位。
判据二：MODENUM 回的模块基址等于 OptionalHeader.ImageBase。
两条同中即固定基址，所有偏移可以写死。收敛：若强行开启系统 ASLR 后进程启动即崩（0xC0000005 在入口），进一步确认无重定位表。"""),
    dict(id="re-023", topic="pe-elf",
         prompt="dump 出来的内存镜像，IAT 怎么修才干净？",
         response="""kitty_dump action=dump module=x.exe path=logs/x-mem.bin
kitty_dump action=unmap reference=x.exe fix_iat=true path=logs/x-fixed.exe
判据一：重建产物里 IAT 每项都落在某个模块的映像范围内（kitty_rea_binary 看节区间）。
判据二：与磁盘版 IAT 的差异项数 < 5。
收敛：差异项集中在少数 DLL 上，说明是运行期替换的导入（loader 型样本常见），按替换后的模块名写回才可再加载。"""),
    dict(id="re-024", topic="pe-elf",
         prompt="节的对齐参数不合法还能加载，说明什么？",
         response="""kitty_patch action=info path=w.exe
kitty_rea_binary inspect_binary_layout path=w.exe
判据一：PointerToRawData % FileAlignment ≠ 0 而程序仍能跑 → 手工构造，链接器不会这样输出。
判据二：VirtualSize=0 但 SizeOfRawData>0，映射时按原始大小，容易与下一节重叠。
收敛：inspect_binary_layout 报段重叠时，按先出现的节优先，重叠区内容只信一次；若重叠区是关键代码，直接转崩溃分诊。"""),
    dict(id="re-025", topic="pe-elf",
         prompt="ELF 的 program header 和 section header 对不上，以哪个为准？",
         response="""kitty_rea_binary inspect_binary_layout path=sample.elf
kitty_ghidra action=analyze target=sample.elf out=logs/gh-elf
判据一：存在 PT_LOAD 段没有任何节覆盖，或某节偏移落在所有 PT_LOAD 之外。
判据二：反汇编在段边界处出现非法指令密度突增（每 256 字节 > 20 条无效）。
收敛：以 program header 为准重建视图；节表只作符号与名字参考，冲突时丢弃节视图。"""),
    dict(id="re-026", topic="pe-elf",
         prompt=".so 在目标机上加载失败，怎么确认是依赖缺失？",
         response="""kitty_rea_binary inspect_binary_layout path=libfoo.so
kitty_sym action=imports path=libfoo.so limit=200
判据一：.dynamic 的 NEEDED 条目 ≥3，但 DT_RPATH/DT_RUNPATH 缺失。
判据二：imports 里有未定义符号，且没有任何 NEEDED 库能提供（按库名逐个核对导出）。
收敛：缺哪个补哪个；若 NEEDED 里出现绝对路径的库，按该路径找同名不同版本，版本不符是最常见的加载失败原因。"""),
    dict(id="re-027", topic="pe-elf",
         prompt="怎么判断一个 Linux 二进制是静态链接的？",
         response="""kitty_rea_binary inspect_binary_layout path=tool
kitty_ghidra action=functions out=logs/gh-tool limit=40
判据一：没有 PT_INTERP 段，没有 .dynamic 节。
判据二：符号里出现 __libc_start_main，且其参数直接给出 main 地址。
收敛：静态链接时启动链完整可读，main 之前只有 libc 初始化；若同时有 INTERP 与 NEEDED 为空，属手工改过的异常样本，按加固处理。"""),
    dict(id="re-028", topic="pe-elf",
         prompt="怎么确认一个 ELF 是 PIE？",
         response="""kitty_rea_binary inspect_binary_layout path=a.out
kitty_ce op="MODENUM"
判据一：e_type=ET_DYN 且有 PT_INTERP。
判据二：.rela.dyn 里 R_X86_64_RELATIVE 占比 > 80%。
收敛：运行时模块基址不等于 0x400000 即验证。PIE 下所有静态偏移都要加模块基址，先定这个再谈别的。"""),
    dict(id="re-029", topic="pe-elf",
         prompt=".so 被 strip 过，还能恢复多少符号？",
         response="""kitty_sym action=exports source=file path=lib.so limit=200
kitty_rea_binary inspect_binary_layout path=lib.so
判据一：.symtab 缺失但 .dynsym 有 ≥10 个导出 → 只剥了调试符号。
判据二：kitty_ghidra action=functions 里导出名直接出现（非 sub_）。
收敛：全 sub_ 时只能靠字符串、JNI 注册表或调用图推名字；导出可用时优先用导出名锚定。"""),
    dict(id="re-030", topic="pe-elf",
         prompt="替换系统库时同名符号有多个版本，怎么选？",
         response="""kitty_rea_binary inspect_binary_layout path=lib-x.so
kitty_sym action=exports path=lib-x.so limit=200
判据一：存在 .gnu.version_d（VERDEF）且导出带 @GLIBC_2.x 后缀。
判据二：同名符号出现 foo@V1 与 foo@@V2 两条，@@ 是默认绑定版本。
收敛：替换库必须保留默认版本定义，调用方按 @@ 绑定；只提供 @V1 会导致启动时报 version GLIBC_2.x not found。"""),
]

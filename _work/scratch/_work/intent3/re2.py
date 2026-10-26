# -*- coding: utf-8 -*-
"""re-sft 批次 2：PE/ELF 补充（B11-B15）+ 固件/镜像（C1-C15）+ 崩溃转储（D1-D10）。
说明：转储加载用 cdb（真实调试器 CLI，contracts 无转储解析工具）；其余一律 kitty_*。
"""

RECORDS = [
    dict(id="re-031", topic="pe-elf",
         prompt="内存镜像和磁盘版差 30%，正常吗？",
         response="""kitty_dump action=dump module=svc.exe path=logs/svc-mem.bin
kitty_dump action=unmap reference=svc.exe fix_iat=false path=logs/svc-unmap.bin
判据一：unmap 后与磁盘文件逐节比较，.text 差异应 < 1%（只有重定位修正），差异 > 5% 说明内存里被改写（补丁/解壳）。
判据二：.data 差异大属正常（运行时初始化），.rdata 差异 > 2% 才可疑。
收敛：差异集中区按节偏移回推文件偏移，用 kitty_patch action=find 在原文件对应区定位改前字节。"""),
    dict(id="re-032", topic="pe-elf",
         prompt="怎么确认异常处理目录里的回调是编译器默认的还是自己注册的？",
         response="""kitty_patch action=info path=e.exe
kitty_ida action=entries out=logs/ida-e
判据一：DataDirectory[3]（Exception）Size / 12 等于异常表条目数，每个 ScopeTable 落在 .rdata。
判据二：存在指向代码节中间的 handler（不在 .pdata 覆盖范围），说明运行期注册过向量化处理。
收敛：kitty_ida action=xrefs filter=AddVectoredExceptionHandler 找注册点，参数里的回调地址即真实处理函数。"""),
    dict(id="re-033", topic="pe-elf",
         prompt="怎么从资源里拿版本信息做样本聚类？",
         response="""kitty_ghidra action=strings out=logs/gh-r limit=300
kitty_patch action=find path=r.exe str=VS_VERSION_INFO utf16=true limit=2
判据一：UTF-16 命中 VS_VERSION_INFO 后跟固定头部（BD 04 EF FE）。
判据二：FileVersion/ProductVersion 与 PE 头 TimeDateStamp 的组合可做聚类键。
收敛：CompanyName/OriginalFilename 与签名主体交叉核对，三者一致才把版本信息当可信字段。"""),
    dict(id="re-034", topic="pe-elf",
         prompt="文件尾还有一段数据，怎么判断是不是必要载荷？",
         response="""kitty_patch action=info path=z.exe
kitty_patch action=find path=z.exe pattern="50 4B 03 04" limit=8
判据一：overlay 长度 > 0，起点 = 最后节 PointerToRawData+SizeOfRawData，之后内容不属于任何节。
判据二：overlay 里命中 ZIP 本地头（50 4B 03 04）或自定义魔数，且程序里有对应偏移的读取代码。
收敛：kitty_ida action=strings 找 overlay 相关路径/魔数常量；有读取代码才算必要载荷，否则按附加数据丢弃。"""),
    dict(id="re-035", topic="pe-elf",
         prompt="只有序号没有名字的导出，怎么用？",
         response="""kitty_sym action=exports path=old.dll limit=200
kitty_rea_binary inspect_binary_layout path=old.dll
判据一：导出表里 Name 指针为 0、只有 Ordinal 的条目占比 > 30%。
判据二：.edata 的 AddressOfNames 数组存在但对应项为空串。
收敛：按序号 kitty_sym action=resolve name=#<ordinal> 解析，命中即可在 kitty_ida 里按地址下断；序号跨版本不稳定，换版本必须用二进制差分校准。"""),
    dict(id="re-036", topic="firmware",
         prompt="拿到一个 8MB 的固件 bin，怎么先摸清结构？",
         response="""kitty_patch action=find path=fw.bin pattern="68 73 71 73" limit=8
kitty_patch action=find path=fw.bin pattern="27 05 19 56" limit=8
kitty_patch action=find path=fw.bin pattern="D0 0D FE ED" limit=4
判据一：68 73 71 73（sqsh 小端）→ squashfs 起点；27 05 19 56 → uImage 头；D0 0D FE ED → 设备树。
判据二：各命中偏移按 4KB 对齐且间隔 ≥ 0x10000，说明是分区化布局。
收敛：按命中点切段，对每段跑 kitty_patch action=info 或 kitty_rea_binary，能识别的段先归档。"""),
    dict(id="re-037", topic="firmware",
         prompt="固件里确认有 squashfs，怎么定位并取出来？",
         response="""kitty_patch action=find path=fw.bin pattern="68 73 71 73" limit=4
kitty_ce op="MEMDUMP_HEX|<hit_off>|64"
判据一：魔数后 2 字节是 inode 数、4 字节 mkfs_time，版本字段为 04 00（4.0）。
判据二：块大小字段为 4096/8192/16384 之一，compress id 在 1-6 之间。
收敛：从命中偏移切到下一个分区魔数（或文件尾）得到镜像，用 unsquashfs -s 验证超级块，能列出 inode 数即完整。"""),
    dict(id="re-038", topic="firmware",
         prompt="固件解出来是裸 NAND 镜像，怎么判断文件系统类型？",
         response="""kitty_patch action=find path=nand.bin pattern="85 19 03 20" limit=8
kitty_patch action=find path=nand.bin pattern="55 42 49 23" limit=8
判据一：85 19 03 20（JFFS2 小端魔数）在多个擦除块首部重复出现 → JFFS2。
判据二：55 42 49 23（UBI#）命中且后跟 EC 头，说明是 UBI 卷。
收敛：JFFS2 按擦除块大小（通常 0x20000）切；UBI 先按 EC 头里的 vid_hdr_offset 找卷表，再逐卷导出。"""),
    dict(id="re-039", topic="firmware",
         prompt="路由器固件的 TRX 头怎么解析？",
         response="""kitty_patch action=find path=fw.trx str=HDR0 limit=2
kitty_ce op="MEMDUMP_HEX|<trx_off>|32"
判据一：HDR0 后 4 字节是长度（小端），再 4 字节 CRC32，再 2+2 字节版本/标志。
判据二：偏移表 3 个 uint32（loader/kernel/rootfs）都小于总长度且单调递增。
收敛：按偏移表切出 kernel 与 rootfs；kernel 跑 kitty_rea_binary 应为 ELF 或 zImage，rootfs 按魔数再扫一遍。"""),
    dict(id="re-040", topic="firmware",
         prompt="固件 rootfs 解出来后，怎么快速找 Web 管理入口？",
         response="""kitty_patch action=find path=rootfs.bin str=/www limit=16
kitty_patch action=find path=rootfs.bin str=lighttpd limit=8
判据一：/www 或 /web 路径串命中 ≥2 处（配置文件 + 启动脚本）。
判据二：init 脚本里出现 httpd/lighttpd/goahead 启动命令，端口参数可见（-p 80 / 8080）。
收敛：按脚本里的 DocumentRoot 定位静态目录，再找 CGI 目录；CGI 二进制用 kitty_rea_binary 判架构后交叉分析。"""),
    dict(id="re-041", topic="firmware",
         prompt="自有设备的固件里，init 脚本常带默认口令，怎么系统性地找？",
         response="""kitty_patch action=find path=rootfs.bin str=/etc/shadow limit=8
kitty_patch action=find path=rootfs.bin str=password= limit=32
判据一：shadow 路径出现在打包列表里，且哈希字段不是 * 或 !。
判据二：脚本里 username= 与 password= 成对赋值，且该行未被 # 注释。
收敛：把命中脚本段切出按行过滤，排除模板变量后记入设备台账；用途是默认口令整改，不是分发。"""),
    dict(id="re-042", topic="firmware",
         prompt="固件镜像带分区表，怎么验证分区边界？",
         response="""kitty_ce op="MEMDUMP_HEX|<0>|512"
kitty_patch action=find path=fw.bin pattern="55 AA" limit=4
判据一：MBR 签名 55 AA 位于 0x1FE，四个分区项起始 LBA 与长度都落在镜像范围内。
判据二：各分区首扇区魔数（Linux 的 83、FAT 的 EB 3C 90）与分区类型码一致。
收敛：按 LBA*512 切段逐段扫描；边界重叠或越界说明分区表被改过，以实际魔数为准。"""),
    dict(id="re-043", topic="firmware",
         prompt="自建升级包的字段怎么还原？",
         response="""kitty_ce op="MEMDUMP_HEX|<pkg_off>|256"
kitty_patch action=find path=upg.bin str=VER limit=8
判据一：头部有固定魔数 + 版本串 + 长度字段，且长度字段与文件实际长度一致。
判据二：负载段前 4 字节是 CRC32，按标准多项式重算能对上。
收敛：按长度字段切负载，CRC 通过即字段布局正确；不通过换字节序再试一次，两次都错则说明头长可变，需要按版本串偏移反推。"""),
    dict(id="re-044", topic="firmware",
         prompt="固件里切出的二进制怎么快速判架构？",
         response="""kitty_rea_binary inspect_binary_layout path=bin/httpd
kitty_ghidra action=analyze target=bin/httpd out=logs/gh-httpd
判据一：e_machine 为 0x28（ARM）、0xB7（AArch64）或 0x08（MIPS），EI_CLASS 区分 32/64。
判据二：PT_INTERP 指向 /lib/ld-uClibc.so.0 或 /lib/ld-musl-*.so.1，说明是嵌入式 libc。
收敛：AArch64 用 Ghidra 默认处理器可直读；MIPS 大端必须在 analyze 前指定语言，否则反汇编全错。"""),
    dict(id="re-045", topic="firmware",
         prompt="固件里的 busybox 怎么确认版本和启用的 applet？",
         response="""kitty_ghidra action=strings out=logs/gh-bb limit=400
kitty_sym action=exports path=busybox limit=200
判据一：版本串 BusyBox v1.x.y 命中，且 applet 名表（ash、cat、ls、mount 等）以空格分隔成串。
判据二：导出表里 applet_main 或 applet_names 符号存在。
收敛：applet 名表按顺序与 applet_main 指针数组一一对应，取索引即得某 applet 的实现地址。"""),
    dict(id="re-046", topic="firmware",
         prompt="固件里的默认配置一般存在哪，怎么取？",
         response="""kitty_patch action=find path=rootfs.bin str=nvram limit=16
kitty_patch action=find path=rootfs.bin str=default.cfg limit=8
判据一：/etc/nvram/defaults 或 /etc/config 路径存在，同目录有 .default 后缀文件。
判据二：配置是 key=value 行式，键名与 Web 表单字段能对上。
收敛：默认值表与运行期读取点（kitty_ida action=xrefs filter=nvram_get）对齐，未在读取点出现的键是死配置，可忽略。"""),
    dict(id="re-047", topic="firmware",
         prompt="怎么把启动链证据串起来？",
         response="""kitty_patch action=find path=fw.bin pattern="27 05 19 56" limit=4
kitty_rea_binary inspect_binary_layout path=kernel.img
kitty_ghidra action=strings out=logs/gh-init limit=200
判据一：uImage 头里的 load/entry 地址与内核 ELF 的 p_paddr 一致。
判据二：initramfs 里 /init 的 shebang 指向的 busybox 路径真实存在。
收敛：bootloader 配置（bootargs）里的 root= 与 rootfs 分区类型一致，链条闭合才算还原完整启动路径。"""),
    dict(id="re-048", topic="firmware",
         prompt="自有设备固件带签名校验，怎么定位校验点？",
         response="""kitty_ghidra action=strings out=logs/gh-fw limit=400
kitty_ida action=functions out=logs/ida-fw filter=verify
判据一：字符串里出现公钥 PEM 头与 signature 相关错误码。
判据二：校验函数在升级流程里被调用，失败路径返回固定错误码（如 0x1A）。
收敛：公钥段与镜像里的签名段对齐，校验范围通常是头部之外的全部负载；范围确定后再谈兼容性修补。"""),
    dict(id="re-049", topic="firmware",
         prompt="固件里常见的密钥/证书存放位置有哪些？",
         response="""kitty_patch action=find path=rootfs.bin str=PRIVATE KEY limit=8
kitty_patch action=find path=rootfs.bin str=.pem limit=16
判据一：PEM 头（-----BEGIN）命中且后随 base64 块，长度与 2048/4096 位密钥匹配。
判据二：同目录存在 .crt/.pem 成对文件，说明是设备身份而非测试残留。
收敛：私钥命中即高危项，核对是否所有设备共用同一把；共用则整批设备身份可伪造，需立即轮换。"""),
    dict(id="re-050", topic="firmware",
         prompt="怎么从固件生成一份最小 SBOM？",
         response="""kitty_patch action=find path=rootfs.bin str=openssl limit=16
kitty_ghidra action=strings out=logs/gh-lib limit=600
判据一：库文件名带版本（libssl.so.1.1、libcurl.so.4.5.0）且至少 5 个组件命中。
判据二：版本串能落到已知 CVE 区间（如 OpenSSL 1.1.1 < 1.1.1w）。
收敛：组件名+版本+路径三元组汇总成清单，按 CVE 区间过滤出需升级项；无版本号的库用 build-id 反查发行版包。"""),
    dict(id="re-051", topic="crash-dump",
         prompt="拿到一个 minidump，怎么先读异常码？",
         response="""cdb -z crash-app.dmp -c ".exr -1; lm; q"
kitty_ce op="MODENUM"
判据一：.exr -1 的 ExceptionCode 为 0xC0000005（AV）、0xC00000FD（栈溢出）或 0xE06D7363（C++ 异常）。
判据二：ExceptionAddress 落在 lm 列表某个模块的 [base, base+size) 内。
收敛：异常码加模块归属先定性，再决定看栈还是看堆；0xC0000005 且地址 < 0x10000 是空指针解引用。"""),
    dict(id="re-052", topic="crash-dump",
         prompt="崩溃转储没有符号，栈怎么回溯？",
         response="""cdb -z crash-b.dmp -c ".ecxr; kb; q"
kitty_sym action=resolve source=mem module=app.exe name=<候选>
判据一：kb 输出的返回地址中，落在代码节的占比 > 60%。
判据二：每个候选返回地址前一条指令是 call（E8/FF15）。
收敛：按 call 反推被调函数起点，逐个用模块+偏移解析；对不上的跳过，不硬凑链路。"""),
    dict(id="re-053", topic="crash-dump",
         prompt="访问违例的地址怎么分类？",
         response="""cdb -z crash-c.dmp -c ".ecxr; !analyze -v; q"
kitty_ce op="MEMDUMP_HEX|<fault_addr>|64"
判据一：fault address < 0x10000 → 空指针或结构体偏移解引用。
判据二：地址在栈区且接近 RSP → 栈溢出；地址在堆区且内容像 ASCII → 释放后使用。
收敛：MEMDUMP_HEX 看该地址可读性；不可读且 PageFault 为读，按空指针链处理，先修判空再谈越界。"""),
    dict(id="re-054", topic="crash-dump",
         prompt="堆破坏在转储里有什么特征？",
         response="""cdb -z crash-d.dmp -c "!heap -s; q"
kitty_ce op="MEMDUMP_HEX|<heap_region>|256"
判据一：堆块头 size/flags 出现非 0 flag 位且相邻块 size 不连续。
判据二：空闲链表指针指向非堆区地址。
收敛：定位第一个异常块，向前回溯分配记录；有页堆日志用 !heap -p 对齐，没有则按写越界方向推定。两条同中才按堆破坏处理，单中可能是未初始化内存。"""),
    dict(id="re-055", topic="crash-dump",
         prompt="怎么确认转储里的模块版本和现场一致？",
         response="""cdb -z crash-e.dmp -c "lmv; q"
kitty_patch action=info path=app.exe
判据一：lmv 里主模块时间戳与磁盘文件 TimeDateStamp 一致。
判据二：系统 DLL 只有名字没有路径，说明是精简转储。
收敛：版本不一致时以转储内时间戳为准重建现场，别拿现网 DLL 的偏移套栈；磁盘文件可能已被更新或替换，此时只信转储里的模块布局。"""),
    dict(id="re-056", topic="crash-dump",
         prompt="只有一段栈内存，怎么反推调用链？",
         response="""kitty_ce op="MEMDUMP_HEX|<rsp>|2048"
kitty_sym action=resolve source=mem module=app.exe name=<候选>
判据一：按 8 字节步进，值落在 [模块基址, 基址+SizeOfImage) 的即候选帧。
判据二：候选值减 5 处能解出 call 指令，且目标在代码节。
收敛：从 RSP 向高地址逐帧校验，遇到第一个不合法帧即停；帧序列与 kitty_ida action=xrefs 的调用图比对，闭合即链成立。"""),
    dict(id="re-057", topic="crash-dump",
         prompt="异常地址在模块里，怎么换算成函数？",
         response="""cdb -z crash-f.dmp -c ".ecxr; ln; q"
kitty_ida action=functions out=logs/ida-app limit=400
判据一：RVA = ExceptionAddress - 模块基址，落在某函数 [start, end) 区间。
判据二：该函数内偏移处是访存指令（mov/cmp），操作数寄存器来自未初始化参数。
收敛：命中函数后 kitty_ida action=decompile name=<函数> 看参数使用；偏移落在函数中段且前有循环，优先怀疑数组越界。"""),
    dict(id="re-058", topic="crash-dump",
         prompt="完整转储和 minidump 差在哪，什么时候必须用完整的？",
         response="""cdb -z crash-full.dmp -c ".dumpchk; q"
cdb -z crash-mini.dmp -c ".dumpchk; q"
kitty_patch action=info path=app.exe
判据一：完整转储能覆盖堆与全部线程栈页，minidump 只有寄存器与栈顶若干页。
判据二：崩溃与堆数据相关（AV 地址在堆区）时 minidump 无法验证内容，必须完整转储。
收敛：先按 minidump 定性异常码与模块，再按需补采；转储策略别设成每次全量，会拖慢现场。"""),
    dict(id="re-059", topic="crash-dump",
         prompt="转储里能捞到什么现场信息？",
         response="""kitty_ce op="MEMDUMP_HEX|<heap>|4096"
kitty_ghidra action=strings out=logs/gh-app limit=600
判据一：命令行、URL、文件路径、错误消息四类字符串命中 ≥3 类。
判据二：字符串所在页可读，且邻近有连续 8 字节对齐的指针表。
收敛：按字符串反查静态引用（kitty_ida action=xrefs），对不上的是运行期拼接，按时间线归档而非硬编码匹配。"""),
    dict(id="re-060", topic="crash-dump",
         prompt="异常处理里又崩了，怎么分诊？",
         response="""cdb -z crash-g.dmp -c ".exr -2; .exr -1; q"
kitty_ida action=functions out=logs/ida-app filter=handler
判据一：两次 ExceptionCode 不同（如先 0xC0000005 后 0xC0000409），第二次栈更浅。
判据二：第二次异常地址落在第一次的 handler 函数内。
收敛：以第一次异常为主分析，第二次只说明 handler 自身不安全；修复顺序是先补 handler 入参校验，再修原始 bug。"""),
]

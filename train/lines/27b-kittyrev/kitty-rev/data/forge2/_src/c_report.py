# -*- coding: utf-8 -*-
"""forge2 C · 逆向结论体（30 条，150-300 字）：现象→判据→结论→下一步。治"短答偏斜"。"""
GROUP = "C"
CAT = "action-reverse"

ROWS = [
    ("rp-pe-overlay",
     "把这段分析落成结论：exe 末段之后还有 0x2A000 字节，首部是 MZ。",
     "现象：文件尾存在 0x2A000 字节附加区，首 2 字节为 `4D 5A`。判据：末 PT/节 RawEnd=0x6C000，文件长 0x96000，"
     "差值恰为 0x2A000；附加区 `e_lfanew` 指向 0x80，该处读得 `50 45 00 00`。结论：镜像尾部内嵌一个完整 PE，"
     "非随机填充。下一步：`dd if=s.exe bs=1 skip=0x6C000 of=inner.bin` 后按独立样本走节表与导入分析，"
     "并核对两个镜像的 TimeDateStamp 是否同源。"),
    ("rp-elf-wx",
     "把 .text 段 RWE 这件事写成结论。",
     "现象：`readelf -lW lib.so` 中第一个 PT_LOAD 的 Flg 为 `RWE`，且 p_filesz=0x220 远小于 p_memsz=0x8000。"
     "判据：正常构建只有 `R E` 代码段；文件实际承载 0x220 字节、内存却映射 0x8000，说明运行时才填入主体。"
     "结论：该 so 自带解密/自映射逻辑，静态只能看到装载器。下一步：在 `mprotect`/`mmap` 导入处下断，"
     "取填充后的内存镜像，再对解密后的区间重新做一次节级分析。"),
    ("rp-fw-squashfs",
     "固件提取结论怎么写？镜像里 squashfs 在 0x1A0000，提取后 /etc/init.d/rcS 起 3 个服务。",
     "现象：镜像 0x1A0000 处命中 `68 73 71 73`，`unsquashfs -s` 报块大小 0x20000、xz 压缩，提取出 1 个 rootfs。"
     "判据：rcS 内 3 条以 `&` 结尾的启动行分别指向 httpd、telnetd、wscd，对应二进制均在 /usr/sbin 下且为 MIPS32。"
     "结论：对外面为 web + telnet 两条。下一步：先看 telnetd 是否带 `-l /bin/sh`，"
     "再对 httpd 的 cgi-bin 做输入面清点，最后核对 wscd 的 socket 端口。"),
    ("rp-apk-shell",
     "给这个 APK 下个加固结论。",
     "现象：classes.dex 仅 6,144 字节，assets 下存在 18 MB 的 `o0oo0.dat`，`lib/arm64-v8a` 含 `libjiagu.so`。"
     "判据：dex 头 magic 正常但 file_size 字段为 0，说明是占位；`strings -a libjiagu.so | grep -c DexHelper` ≥ 3。"
     "结论：整体壳（Application 已被替换），静态不可得真实代码。下一步：脱壳取内存中的 dex（在 "
     "`DexFile.loadDex` 或 `openDexFile` 处取 dump），再对还原后的 dex 做组件与权限对照。"),
    ("rp-dualview-diverge",
     "三视图分叉了，结论怎么写才不越界？",
     "现象：同一地址 `0x7FF7A1203400` 的 `R` 返回 0x00000000，`KM_R` 返回 0x00000064，`KM_PA`+`KM_PR` 与后者一致。"
     "判据：两视图差异稳定复现 3 轮（`kitty_dualview samples=3`），且物理读与内核路由一致 → 差异出在用户态取数路径。"
     "结论：该页存在用户态读取被改写/重定向的迹象，不等同于内存内容变化。下一步：换只读路径复核（`R` 用 bytes:16），"
     "并对该页做 `kitty_prot query` 看保护位，再决定是否用 `kitty_wpb` 之外的取证手段。"),
    ("rp-pointer-chain",
     "把指针链结论写清楚：基址+0x1A2B3C0 → +0x38 → +0x10 → HP。",
     "现象：`P_BACK|0x...HP|0x7FF700000000|0x7FF750000000` 命中 3 条候选，逐条 `P_WALK` 后仅 1 条稳定。"
     "判据：`P_WALK|0x7FF71A2B3C0|0x38` 与 `|0x10` 连续两跳返回值恒定，第三跳读到 int32 且与界面显示同量级。"
     "结论：链为 MODULE+0x1A2B3C0 → [+0x38] → [+0x10] → int32，偏移量按十进制记录。下一步：换场景复验一次，"
     "并在两次进程重启后确认基址漂移只影响第一跳。"),
    ("rp-patch-verify",
     "这个补丁的结论段怎么写？",
     "现象：目标函数首字节由 `48 89 5C 24 08` 改为 `31 C0 C3 90 90`（提前返回 0）。判据："
     "`kitty_patch action=patch` 带 expect 原字节写入成功，事后 `hash` 前后对比只有该 5 字节变化，PE 校验和已重算。"
     "结论：改动最小且可回滚（.bak 保留）。下一步：跑一次原路径回归，确认返回值 0 时上游分支走的是成功侧，"
     "并把 expect 字节写进变更记录。"),
    ("rp-dump-rebuild",
     "转储重建的结论怎么写？",
     "现象：按节表转储 0x1C0000 字节，重建后与磁盘原文件逐字节一致率 99.87%。判据："
     "差异集中在 .rdata 的 0x2xx 字节（IAT 槽位，运行时被改写），其余节全等；`kitty_dump unmap=true` 已回填 IAT。"
     "结论：运行时镜像与磁盘镜像仅 IAT 不同，符合正常加载。下一步：把差异区间单独导出做对照，"
     "确认没有额外写入者，再拿重建件做静态比对。"),
    ("rp-frida-trace",
     "把 hook 结论写成一段。",
     "现象：对 `libsign.so!sign` 下 hook 后，入参 3 个（str、int、byte[]），返回 32 字节 hex。判据："
     "同输入连调 3 次返回一致，第 2 参为时间戳（秒级、与系统时间差 < 2 s），第 3 参长度固定 16。"
     "结论：签名 = f(固定串, 秒级时间, 16 字节随机/设备因子)，无服务端 nonce。下一步：把第 3 参来源追到调用点，"
     "确认是否来自设备指纹，再决定本地复现的输入面。"),
    ("rp-firmware-uart",
     "串口结论怎么写：115200 能出 U-Boot，中断后进命令行。",
     "现象：TX 在 115200 8N1 下可打印，可打印字符占比约 82%；上电 0.8 s 出现 `Hit any key to stop autoboot`。"
     "判据：按键后 `printenv` 可读，bootdelay=2、bootargs 含 `root=/dev/mtdblock3`。结论：调试口开放且可中断启动。"
     "下一步：`printenv` 全量落盘归档，核对 mtdparts 与镜像内分区是否一致，再决定是否只做只读取证。"),
    ("rp-apk-sign",
     "签名结论怎么写？",
     "现象：`apksigner verify --verbose` 显示 v1=true、v2=true、v3=true，证书主体 CN=Android Debug。"
     "判据：v2 块 magic `APK Sig Block 42` 存在于中央目录前 0x1A0 字节，且 `--print-certs` 的 SHA-256 与 "
     "META-INF 里 CERT.RSA 一致。结论：三方案齐备但为调试证书，属可重签包。下一步：核对 targetSdk 与 "
     "v3 轮转 lineage，确认无 OEM 私有签名容器后再做重打包。"),
    ("rp-elf-strip",
     "strip 过的 so 结论段。",
     "现象：e_shoff=0、.symtab 缺失，仅 .dynsym 保留 7 个导出。判据：`readelf -hW` 的 e_shnum=0 但 e_phnum=9，"
     "程序头完好；`strings -tx` 命中 214 条可读串，其中 12 条为 URL。结论：符号被移除但结构完整，"
     "逻辑可经字符串 xref 定位。下一步：以 URL 与错误提示为锚点反查引用，先重建 3-5 个关键函数，"
     "再决定是否做全量函数识别。"),
    ("rp-crash-dump",
     "崩溃结论怎么写才有下一步？",
     "现象：minidump 中异常码 0xC0000005、访问地址 0x00000018，栈顶返回地址落在 `mod+0x4A2C1`。判据："
     "该地址前 3 条指令为 `mov rax,[rcx+0x18]`，rcx=0 → 空指针加偏移，非野指针。结论：调用方未判空即解引用。"
     "下一步：回溯 `mod+0x4A2C1` 的调用者，核对传入对象在何处分文未初始化，并确认该路径是否只在特定配置下走。"),
    ("rp-network-proto",
     "协议结论怎么写？抓包看到 12 字节头 + 变长体。",
     "现象：帧头固定 12 字节，前 4 字节为 magic `0x4B545231`，其后 2 字节长度（小端）、2 字节 cmd、4 字节 seq。"
     "判据：长度字段 + 12 恒等于帧总长（30 帧全对），seq 单调递增无空洞。结论：长度前缀式自定义协议，无分片。"
     "下一步：按 cmd 聚类取样本，先还原 3 个高频 cmd 的体结构，再看是否有加密（体熵 > 7.5 即疑似）。"),
    ("rp-anti-debug",
     "这个反调试结论怎么写？",
     "现象：导入表含 ptrace，首次调用参数为 0；`/proc/self/status` 字符串存在。判据：ptrace(0,...) 返回 -1 时"
     "走到 exit(1) 分支（反汇编可见 `cmp eax,-1` + `jne`），且该分支前读 TracerPid。结论：单点自检，"
     "无多点交叉校验。下一步：先确认是否存在第二处校验（搜同一字符串的 xref 数），再决定脱壳顺序。"),
    ("rp-root-detection",
     "把 root 检测结论写成报告段。",
     "现象：应用启动时检查 `/system/bin/su`、`/sbin/su` 与 `ro.debuggable`，并对 `which su` 结果判空。"
     "判据：三处检查的返回值合并成一个 bool，任一命中即弹窗退出；`strings -a libnative.so | grep -c '/su'` = 3。"
     "结论：文件存在性检测，无 SafetyNet 级校验。下一步：确认是否有 native 侧二次校验（JNI 调用链），"
     "再评估自有测试机上的取证路径。"),
    ("rp-web-cgi",
     "固件 web 结论怎么写？",
     "现象：`/www/cgi-bin/setup.cgi` 读取 QUERY_STRING 后直接拼进 `system()`。判据："
     "`objdump -d` 中 system 调用点前 0x18 字节内出现该缓冲区地址，且格式化串为 `%s`（非常量）。"
     "结论：命令拼接点确认，输入面为 GET 参数。下一步：梳理参数白名单（若有），"
     "并在自有设备上以最小输入验证拼接是否真的落地，再给出加固建议（改用 execv 传参）。"),
    ("rp-pe-tls",
     "TLS 回调结论段。",
     "现象：TLS 目录 RVA 0x2A3000，AddressOfCallBacks 指向 .rdata 内数组，含 2 个非 0 项。判据："
     "两项均落在 .text（0x401000-0x4A2000）内，且第一项在入口点之前被执行（断 LdrpCallTlsInitializers 可见）。"
     "结论：入口前有 2 段初始化，静态分析的「第一执行点」应取回调 1 而非 EntryPoint。下一步：优先反编译这两个回调。"),
    ("rp-unpack",
     "脱壳结论怎么写？",
     "现象：OEP 处 `.text` 熵由 7.94 降到 6.02，节大小由 0x220 恢复为 0x1A000。判据：dump 后 "
     "`readelf`/`dumpbin` 能解析导入表（IAT 条目 187 条、全部指向系统模块），且重建后与原文件差异仅 IAT。"
     "结论：标准压缩壳，OEP 定位正确。下一步：对还原件做导入面清点，优先看网络与文件 API 的调用簇。"),
    ("rp-ios-binary",
     "Mach-O 结论怎么写？",
     "现象：`otool -l` 显示 LC_ENCRYPTION_INFO_64 cryptid=1，__TEXT 段 cryptoff=0x4000。判据："
     "cryptid=1 表示仍加密，cryptoff/cryptsize 指定加密区间；`nm -g` 只能看到导出符号。"
     "结论：App Store 加密二进制，静态不可读主体。下一步：在自有测试机上取解密后镜像（dumpdecrypted 类方案），"
     "再按 LC_SEGMENT 重建后分析。"),
    ("rp-android-native",
     "native 库结论段。",
     "现象：`lib/arm64-v8a/libcore.so` 导出仅 `JNI_OnLoad`，无 Java_* 符号。判据：JNI_OnLoad 内调用 "
     "RegisterNatives，方法表 3 项，签名串位于 .rodata（`(Ljava/lang/String;)Ljava/lang/String;`）。"
     "结论：动态注册，3 个 native 方法。下一步：按方法表第三列取函数地址，逐个反编译，"
     "先看哪个碰到加解密常量（AES S-box / 0x9E3779B9）。"),
    ("rp-frida-detect",
     "反 Frida 结论怎么写？",
     "现象：进程内扫描 `/proc/self/maps` 中 `frida`、`gum-js-loop` 字符串，并对 27042 端口做 connect 探测。"
     "判据：两处检查任一命中即设全局标志，随后主线程走降级分支（功能受限而非退出）。结论：检测存在但不致命。"
     "下一步：确认降级分支影响哪些功能，判断取证是否仍可继续；再决定是否需要在自有环境内换注入方式。"),
    ("rp-vmp",
     "VMProtect 结论怎么写？",
     "现象：入口段有 `pushad` 后跳入高熵区（熵 7.98），`.vmp0/.vmp1` 节存在。判据："
     "节名命中 + 入口处无标准 CRT 序言 + 导入表仅 12 项（LoadLibrary/GetProcAddress 为主）。"
     "结论：VM 保护，主体 handler 在 vmp 节内。下一步：先定位 VM 入口（`pushad` 后第一个 `jmp` 目标），"
     "统计 handler 分派表规模，再评估是否值得做语义还原。"),
    ("rp-kernel-drv",
     "驱动结论怎么写？",
     "现象：驱动导入 `IoCreateDevice`、`ObRegisterCallbacks`、`PsSetCreateProcessNotifyRoutineEx`。判据："
     "`strings -el drv.sys | grep -c '\\\\Device\\\\'` ≥ 1，回调注册点位于 DriverEntry + 0x2A0 附近。"
     "结论：进程/句柄回调型驱动，非文件过滤。下一步：核对回调里对目标进程名的比对逻辑，"
     "确认是否存在白名单，再评估对取证工具的影响面。"),
    ("rp-pcap",
     "pcap 结论段。",
     "现象：单流 1,842 帧，TLS 握手后应用层为 protobuf（首字节 0x0A）。判据："
     "`tshark -r x.pcap -Y 'tcp.stream==3' -T fields -e data.data` 取载荷，首字节 0x0A 且字段 1 为变长串，"
     "长度前缀与剩余字节吻合。结论：明文 protobuf over TLS（自有环境内已解密）。下一步："
     "按字段号聚类，先还原 3 个高频消息，再看是否有签名字段（32 字节定长）。"),
    ("rp-js-bundle",
     "前端 bundle 结论怎么写？",
     "现象：单文件 2.1 MB，webpack 运行时 + 业务 chunk 混排，签名函数位于 `_0x4f2a` 混淆数组后。"
     "判据：`node --check` 通过；`grep -c '_0x[0-9a-f]\\{4,\\}'` = 3,214，字符串表在文件头 0x1200 偏移处。"
     "结论：字符串数组混淆，无控制流平坦化。下一步：先解字符串表（shift + 索引），再定位签名入口的调用链。"),
    ("rp-repro-check",
     "怎么把「结论可复现」写进报告？",
     "现象：同一镜像两次分析结论不一致（一次判 W+X、一次判正常）。判据：两次分别用 `readelf -lW` 与 "
     "`dumpbin /headers`，前者读程序头、后者读节表，在节头被改过的样本上必然不同。结论：口径不同导致分歧，"
     "以程序头为准。下一步：报告里固定写「用哪条命令、读哪个表、样本 sha256 前 16 位」，"
     "并附命令原始输出片段，避免只写结论。"),
    ("rp-scope-note",
     "报告里怎么交代样本来源与范围？",
     "现象：样本为自建靶场产物，sha256 前 16 位 `3f9a...c21e`，分析在隔离机完成。判据："
     "报告含三条可核字段：sha16、采集时间、分析机镜像版本；且每条结论后标所用命令。"
     "结论：来源与口径可追溯。下一步：把命令输出落盘到 `logs/` 并在附录引用路径，"
     "让第三人能不依赖作者复跑同一结论。"),
    ("rp-diff-two",
     "两个版本的差异结论怎么写？",
     "现象：v1.2 与 v1.3 的 .text 有 1,204 字节差异，集中在 0x4A200-0x4A6B0。判据："
     "该区间在 v1.3 新增一次 `call` 到新函数（地址 0x4C100），新函数内引用字符串 `license.dat`。"
     "结论：新增许可文件校验分支。下一步：反编译新函数确认失败路径（返回值与提示串），"
     "再核对调用点是否在启动链上。"),
    ("rp-evidence-chain",
     "取证报告的证据链怎么组织？",
     "现象：三个证据点——进程内镜像、磁盘文件、网络流量——时间戳跨 40 s。判据："
     "镜像采集时间 T0、文件 mtime T1、首个外连 T2 满足 T0 < T1 < T2，且三者 sha256 互相独立可校验。"
     "结论：行为顺序可判定。下一步：把每份证据的采集命令与哈希写进附表，"
     "并注明时钟源（本机 NTP 偏移 < 50 ms），避免时间线被质疑。"),
]

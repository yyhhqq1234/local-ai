# -*- coding: utf-8 -*-
"""forge2 A2 · 固件/嵌入式（30 条）：binwalk 分叉识别、提取后落点、UART/JTAG 判定。"""
GROUP = "A"
CAT = "kb-re"

ROWS = [
    ("fw-binwalk-basic",
     "拿到一个 16 MB 的固件镜像，第一步该做什么？",
     "先扫签名不急着提取：`binwalk -B -A fw.bin` 出签名表（-B 签名扫描、-A 熵图），"
     "再看 `binwalk -E fw.bin` 的熵曲线。判据：连续高熵段（>7.5）通常是压缩/加密体，"
     "熵骤降处（<4.0）是未压缩的头部或脚本区，落差位置就是文件系统起点候选。"),
    ("fw-squashfs",
     "binwalk 报 squashfs 但提取出来是空的，怎么查？",
     "先确认超级块：squashfs 魔数 `hsqs`（小端 0x73717368）在偏移 0 字节处，块大小在偏移 0x0C（4 字节）。"
     "判据：`dd if=fw.bin bs=1 skip=<off> count=96 | xxd` 前 4 字节为 68 73 71 73；"
     "用 `unsquashfs -s <片>` 能读出块大小与压缩算法，读不出就是被截断。"),
    ("fw-jffs2",
     "JFFS2 和 squashfs 怎么区分，提取方式有何不同？",
     "魔数不同：JFFS2 节点以 0x1985 开头（小端 `85 19`），squashfs 是 `hsqs`。判据："
     "`binwalk fw.bin` 行里 `JFFS2 filesystem` 段通常连续多段（擦除块 0x20000 对齐）；"
     "提取用 `jefferson -d out fw.bin`（或 `binwalk -e` 后合并 mtd），squashfs 用 `unsquashfs -d out`。"),
    ("fw-ubi",
     "UBI 镜像怎么挂载/提取？",
     "认 UBI 头：偏移 0 是 `UBI#`（55 42 49 23），其后 EC 头 64 字节，VID 头 64 字节；页大小常见 0x800。判据："
     "`ubireader_extract_images fw.ubi` 出 .ubivol，再 `ubireader_extract_files` 出目录；"
     "若报 no UBI found，用 `binwalk -o <off>` 把前导 bootloader 跳过后再试。"),
    ("fw-raw-lzma",
     "裸 LZMA 流怎么识别与解压？",
     "看前 5 字节属性：`5D 00 00 80 00` 是 lc=3,lp=0,pb=2 + 字典 8 MB 的常见组合。判据："
     "`dd if=fw.bin bs=1 skip=<off> | xz --format=lzma -dc > out.bin` 能解即为裸 LZMA；"
     "binwalk 里显示 `LZMA compressed data` 但提取失败，多是字典大小被改，需手工按 5 字节属性重建。"),
    ("fw-gzip-chain",
     "固件里一串 gzip，怎么按顺序还原？",
     "先定位每个流起点：gzip 头 `1F 8B 08` + 4 字节 mtime + 1 字节 XFL + 1 字节 OS。判据："
     "`binwalk fw.bin | grep gzip` 给出偏移列表，逐个 `dd skip=<off>` 到 `zcat > part$i`；"
     "若 zcat 报 trailing garbage，说明后面紧跟下一个流，属正常分包。"),
    ("fw-initd",
     "文件系统提出来第一件事看哪里？",
     "看启动链落点：`/etc/init.d/rcS`、`/etc/inittab`、`/etc/rc.local` 三处，"
     "再 `grep -rn 'insmod\\|start-stop-daemon\\|&$' etc/init.d/` 找后台服务。判据："
     "rcS 里 `&` 结尾的行就是常驻进程，其可执行文件路径通常在 `/usr/sbin` 或 `/bin`，"
     "用 `file bin/* | grep -i 'ELF 32-bit'` 校准架构。"),
    ("fw-web-root",
     "Web 服务目录怎么定位、怎么判断用的什么服务？",
     "找 `lighttpd.conf` / `httpd.conf` / `boa.conf`：`grep -rn 'document_root\\|DocumentRoot' etc/`。判据："
     "配置里 `document_root` 的值即 web 根（常见 `/www`、`/web`、`/usr/share/web`）；"
     "再看 `/etc/init.d/` 里对应启动脚本，服务名决定 CGI 路径规则（boa 用 /cgi-bin，lighttpd 看 cgi.assign）。"),
    ("fw-cgi-bin",
     "CGI 目录里一堆 .cgi，怎么快速挑出有输入处理的？",
     "按字符串筛：`grep -rl 'QUERY_STRING\\|CONTENT_LENGTH\\|HTTP_COOKIE' www/cgi-bin/`。判据："
     "命中这三个环境变量的才解析请求；再用 `strings -a x.cgi | grep -c '%s'` 看格式化串数量，"
     "数量 > 3 的多半拼过 SQL 或命令，优先看 `system(`/`popen(` 的 xref。"),
    ("fw-hardcoded",
     "怎么系统性地找固件里的硬编码凭据？",
     "三层扫：`grep -rIn 'password\\|passwd\\|secret\\|token' etc/ usr/` 出文本；"
     "`strings -a -n 8 bin/* | grep -iE 'admin:|root:'` 出二进制内嵌；再 `grep -rn '\\$1\\$\\|\\$5\\$\\|\\$6\\$' etc/` 找 shadow 哈希。"
     "判据：`/etc/shadow` 里 `$1$` 是 MD5、`$6$` 是 SHA-512，字段长度分别约 34 与 90 字节。"),
    ("fw-uart-pin",
     "板子上四个排针，怎么判断哪个是 UART？",
     "先量电平：VCC 3.3 V、GND 0 V 静态可定；TX 上电瞬间有快速跳变（0-3.3 V 抖动），RX 静态高电平。判据："
     "用万用表测四个点，两高一低一抖的组合即 UART；再用逻辑分析仪按 115200 8N1 采样，"
     "能解出可读 ASCII（常见 `U-Boot`、`Booting` 前缀）即确认波特率。"),
    ("fw-uart-baud",
     "不知道波特率，怎么试出来？",
     "从三个最常见值开始：115200、57600、38400。判据：按 8N1 采样后统计字节分布，"
     "正确波特率下可打印字符占比 > 70%，错误时大量 0xFF/0x00 或乱码；"
     "若 115200 出半可读（部分字符对），按 2 倍关系试 57600 或 230400。"),
    ("fw-jtag-idcode",
     "怎么确认板子有 JTAG 且能读出 IDCODE？",
     "先看封装旁 20 针或 10 针排针（TCK/TMS/TDI/TDO/GND/VREF）；用 OpenOCD 试探："
     "`openocd -f interface/ftdi/ft232h.cfg -c 'adapter speed 1000; jtag newtap auto0 tap -irlen 4' -c 'scan_chain'`。判据："
     "scan_chain 输出非 0 的 idcode（如 0x4BA00477 是 Cortex-A9）即通；全 0 或全 1 说明 TDO 未接或电平不匹配。"),
    ("fw-spi-flash",
     "固件是从 SPI Flash 读的，怎么判断容量与布局？",
     "读 JEDEC ID：`flashrom -p ch341a_spi` 会打印 `Found ... flash chip`，ID 前三字节即厂商+容量。判据："
     "常见 0xEF4018 = W25Q128（16 MB），0xC22018 = 32 MB；读出整片后按 0x10000 边界找 U-Boot 头"
     "（`27 05 19 56` 是 uImage 魔数）。"),
    ("fw-uboot-env",
     "U-Boot 环境变量区怎么找、怎么读？",
     "找 `bootcmd=` 的 ASCII 块，其后通常跟 CRC32。判据：`grep -abo 'bootcmd=' fw.bin` 给偏移，"
     "向前对齐到 0x10000 内的擦除块起点；环境区大小常见 0x20000，末尾 4 字节是 CRC32，"
     "用 `python -c \"import zlib;print(hex(zlib.crc32(open('env.bin','rb').read()[:-4]))) \"` 校验。"),
    ("fw-kernel-load",
     "bootargs 里哪些字段决定了内核从哪加载？",
     "看 `bootargs` 的 mtdparts 与 root=：`mtdparts=spi0.0:256k(u-boot),64k(env),4m(kernel),-(rootfs)` 给分区表，"
     "`root=/dev/mtdblock3` 指根分区。判据：分区偏移可由 mtdparts 累加算出（256k+64k+4m=0x450000），"
     "在该偏移处应能看到内核魔数或文件系统魔数。"),
    ("fw-mtd-layout",
     "没有源码，怎么反推 flash 分区表？",
     "按魔数聚类：扫描全片找 0x00004550(PE 不适用)、`hsqs`(squashfs)、`UBI#`、`85 19`(JFFS2)、`1F 8B`(gzip)、"
     "`D0 0D FE ED`(FDT)。判据：把命中偏移排序，相邻命中之间的空档 ≈ 擦除块整数倍（0x10000/0x20000）时，"
     "空档边界即分区边界。"),
    ("fw-dtb",
     "设备树 dtb 怎么提取与反编译？",
     "认魔数 0xD00DFEED（大端字节序 `D0 0D FE ED`），其后 4 字节是总大小。判据："
     "`dd if=fw.bin bs=1 skip=<off> count=<size> of=x.dtb` 后 `dtc -I dtb -O dts x.dtb > x.dts`；"
     "dts 里 `model`/`compatible` 直接给板型，`chosen` 节点的 bootargs 含启动参数。"),
    ("fw-cramfs",
     "binwalk 报 cramfs，怎么解？",
     "魔数 `45 3D CD 28`（小端）在偏移 0，头部 64 字节含 size/flags/name。判据："
     "`binwalk -e` 后用 `cramfsck -x out file.cramfs` 或 `cramfs2tar`；"
     "只读且常被去掉块大小字段，解不出时按 0x400 块大小手工遍历 inode。"),
    ("fw-romfs",
     "romfs 镜像怎么识别和挂载？",
     "魔数 `2D 72 6F 6D`（\"-rom\"）在偏移 0，其后 1 字节是完整大小（4 字节）+ 卷名。判据："
     "`mount -t romfs -o loop fw.romfs /mnt` 可直接挂；容器里无 romfs 支持时用 `genromfs -f x.img -d dir` 反向对照结构。"),
    ("fw-ext4-inside",
     "固件里带一个 ext4，怎么确认而不是误判？",
     "超级块在偏移 0x400：魔数 0xEF53 位于 +0x38（小端 `53 EF`）。判据：`dd if=fw.bin bs=1 skip=<off+0x400> count=2 | xxd` "
     "得 `53 ef` 即 ext 族；再用 `dumpe2fs -h` 读卷标与块大小（常见 0x1000），"
     "块数 × 块大小 应 ≈ 分区大小。"),
    ("fw-ecc",
     "带 ECC 的 NAND dump 直接用会读出乱码，怎么处理？",
     "先确认页大小与 OOB 大小：常见 2048+64 或 4096+224。判据："
     "`nanddump --noecc -f raw.bin /dev/mtd0` 去 OOB 后 `binwalk` 能出结构；"
     "若手上只有带 OOB 的 dump，按 (page+oob) 步长切、丢弃每页末尾 oob 字节即可还原。"),
    ("fw-squashfs-pad",
     "squashfs 提取报 bad magic，但 binwalk 明明命中，为什么？",
     "偏移偏了：squashfs 超级块要求 4 字节对齐，binwalk 的偏移是签名位置，可能落在压缩体的中间。判据："
     "把偏移按 0x1000 向下取整再试 `unsquashfs -o <off>`；仍失败时用 `hexdump -C -s <off-16> -n 64` 看是否"
     "有 0x10-0x200 的前导头（部分厂商在前面塞了自有头）。"),
    ("fw-firmware-mod",
     "厂商固件升级包（.bin）里通常是什么结构？",
     "常见是「自有头 + 压缩载荷 + 校验」三段：头 0x100-0x400 字节含 magic、版本、长度、CRC。判据："
     "`binwalk -B -A pkg.bin` 若在 0x200 后才出现 squashfs/UBI，说明头是自有的；"
     "头部 0x20 起的 4 字节常等于总长，用 `xxd -l 64` 与文件大小比对可验证。"),
    ("fw-rootfs-creds",
     "提取后的 rootfs 里怎么找登录绕过点（不改固件）？",
     "看认证实现：`grep -rn 'strcmp\\|memcmp' usr/sbin/` 交叉引用 login/passwd 处理；"
     "`strings -a bin/login | grep -i 'root\\|admin'` 看内嵌默认名。判据："
     "若 `/etc/shadow` 里 root 字段为 `*` 或空，登录逻辑必然另有分支（如 `telnetd -l /bin/sh`）。"),
    ("fw-web-cgi-audit",
     "CGI 里疑似命令拼接，怎么静态确认？",
     "跟数据流：`grep -n 'getenv(\"QUERY_STRING\")' -r www/` 找入口，再看该变量是否流到 `system(`/`popen(`。判据："
     "`objdump -d --disassemble=main x.cgi` 里 system 的调用点前 0x20 字节内应出现该缓冲区地址；"
     "同时 `strings -a x.cgi | grep -c '%s'` ≥ 2 说明拼接不是常量。"),
    ("fw-uart-shell",
     "串口进去只有 U-Boot，怎么判断能不能进 shell？",
     "看 U-Boot 环境：`printenv` 里 `bootdelay` 与 `preboot`；判据："
     "bootdelay > 0 且串口在启动阶段有 `Hit any key to stop autoboot` 提示，即可中断进 U-Boot 命令行；"
     "`printenv bootargs` 含 `init=/bin/sh` 时内核直接给 shell。"),
    ("fw-jtag-halt",
     "JTAG 连上了但 halt 不住，常见原因？",
     "先看是否能读 IDCODE（能读说明 TCK/TMS 通），再查是否被锁："
     "`openocd ... -c 'reset halt'` 报 `target not halted` 时，多为 CPU 处于低功耗或安全启动锁了 DAP。判据："
     "`scan_chain` 有 idcode 但 `halt` 超时 → 安全位/时钟门控；两者全无 → 接线或电平。"),
    ("fw-i2c-eeprom",
     "板上有 8 脚芯片疑似 EEPROM，怎么读？",
     "先认丝印与地址：24 系列 I2C EEPROM 常见地址 0x50-0x57（A0-A2 决定）。判据："
     "`i2cdetect -y 1` 扫到 0x50 即存在；`i2cget -y 1 0x50 0x00` 读首字节，"
     "前 2 字节常是长度或魔数，整片大小按型号（24C02=256 B、24C256=32 KB）。"),
    ("fw-diff-two",
     "两个版本固件想找改了什么，怎么做差分？",
     "先对齐再比：`binwalk` 两边的段偏移若一致，直接 `cmp -l old.bin new.bin | head -50` 看首个差异偏移；"
     "若偏移漂移，先按 squashfs/UBI 起点做切片对齐再比。判据：差异集中在某 0x1000 页且该页熵升高 → "
     "该页被替换；分散在数百字节 → 配置或脚本改动。"),
    ("fw-entropy-map",
     "熵图怎么读才能判断加密还是压缩？",
     "按块算并看形态：压缩体熵 7.9-8.0 但块间有轻微波动，加密体恒定 8.0 且无结构。判据："
     "`binwalk -E fw.bin` 输出的 CSV 里，若某段 64 个块的熵方差 < 0.001 且均值 7.99 → 判加密；"
     "方差 > 0.01 且有局部跌落到 6.x → 判压缩（字典/块头造成）。"),
    ("fw-secure-boot",
     "怎么从镜像判断有没有开安全启动？",
     "看启动链是否有签名块：U-Boot 之后若紧跟一段固定长度（常见 0x100-0x300）的高熵数据且其前 4 字节为版本号，"
     "多为 FIT 签名或厂商证书。判据：`binwalk` 在该处无已知签名命中、但熵 7.9 且长度是 0x100 整数倍；"
     "配合 dts 里 `secure-boot` 属性或 eFuse 读值确认。"),
]

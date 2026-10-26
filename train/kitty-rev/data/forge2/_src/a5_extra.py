# -*- coding: utf-8 -*-
"""forge2 A5 · 补足行（24 条）：全部带"命令 + 地址/阈值"双判据，补 A/B 组的密度缺口。"""
GROUP = "A"
CAT = "kb-re"

ROWS = [
    ("x-elf-aarch64-plt",
     "AArch64 的 PLT 桩和 x86_64 有什么不同，怎么从字节上区分？",
     "x86_64 桩 16 字节、以 `ff 25 <rel32>`（jmp [rip+off]）结尾；AArch64 桩 16 字节、以 "
     "`adrp x16, page` + `ldr x17, [x16, #off]` + `br x17` 三条组成。判据：`objdump -d -j .plt lib.so` 首条指令为 "
     "`adrp` 即 AArch64；`.plt` 节大小除以 16 等于桩数，两者对不上说明有桩被合并。"),
    ("x-elf-got-relro",
     "怎么看 .got 是否在 RELRO 区间内？",
     "取两个地址比大小：`readelf -SW lib.so` 的 .got 起始地址 A，`readelf -lW` 的 GNU_RELRO 结束地址 B。"
     "判据：A >= GNU_RELRO 起始且 A < B 才算覆盖；再 `readelf -dW` 看 BIND_NOW，两者都有才是 full RELRO。"),
    ("x-elf-init-order",
     "怎么在文件里确认两个构造函数的执行顺序？",
     "看 .init_array 数组顺序：`readelf -x .init_array a.out` 每 8 字节一项，第 0 项先执行。"
     "判据：项数 = 节大小 / 8；用 `objdump -d --start-address=0x<item0>` 与 `0x<item1>` 分别确认函数体，"
     "顺序与源码里 `constructor(101)`/`(102)` 的编号必须一致。"),
    ("x-elf-overlay-magic",
     "附加区里到底是什么，怎么一次判完？",
     "读首 16 字节比魔数：`xxd -s 0x6C000 -l 16 s.exe`。判据：`50 4B 03 04` 是 zip、`37 7A BC AF` 是 7z、"
     "`4D 5A` 是 PE、`1F 8B` 是 gzip；四种都不匹配时按熵判断（`binwalk -E` 该段 > 7.5 视为加密载荷）。"),
    ("x-elf-string-xref",
     "给定一个字符串偏移，怎么找到引用它的指令？",
     "先算 VA：`readelf -SW lib.so` 找包含该偏移的节，VA = 节地址 + (偏移 - 节文件偏移)。判据："
     "`objdump -d lib.so | grep -i '0x<VA>'` 应命中 `lea`/`adrp+add` 指令；AArch64 下地址被拆成两半，"
     "要同时搜 adrp 的页地址与 add 的低 12 位。"),
    ("x-elf-symbol-count",
     "怎么用符号数量快速判断是否 strip 过？",
     "`readelf -sW lib.so | wc -l` 与 `readelf --dyn-syms -W lib.so | wc -l` 比。判据："
     "未 strip 时前者数百到数千、后者几十；两者数量接近（都 < 50）说明 .symtab 已被移除，只剩动态符号。"),
    ("x-elf-segment-gap",
     "两个 PT_LOAD 之间有空洞，会影响静态分析吗？",
     "会。空洞在内存里是未映射页。判据：`readelf -lW` 相邻 PT_LOAD 的 (p_vaddr+p_memsz) 与下一个 p_vaddr 不等时，"
     "该区间不可读；静态按文件偏移算地址会错，必须按段分别算 `VA = p_vaddr + (off - p_offset)`。"),
    ("x-elf-endian-read",
     "手工读 ELF 头时怎么避免端序错误？",
     "先读第 5 字节 EI_DATA（1=小端、2=大端），再按该端序解析后续字段。判据：`xxd -l 20 lib.so` 中偏移 5 的字节"
     "决定 e_type 的读法；小端下 ET_DYN=0x03 读成 `03 00`，大端读成 `00 03`，读错会得到 0x0300 这种不存在的类型。"),
    ("x-fw-ubi-volume",
     "UBI 里有多个 volume，怎么只提其中一个？",
     "先列卷：`ubireader_extract_images fw.ubi` 输出 `ubifs.img.vol-<id>`；再按 id 取。判据："
     "`ubinize.cfg` 或卷头 name 字段含 `rootfs`/`data`；单卷大小 = 总 PEB 数 × 0x20000，"
     "所有卷之和应等于镜像减 UBI 头（0x800 起）。"),
    ("x-fw-squashfs-block",
     "squashfs 的块大小怎么影响提取？",
     "块大小在超级块偏移 0x0C（4 字节，0x20000 常见）。判据：`unsquashfs -s` 输出 `Block size 131072`；"
     "文件被截断时按 `块大小 × 块数` 估算所需长度，差多少就缺多少，缺一块也会解压失败。"),
    ("x-fw-jffs2-erase",
     "JFFS2 提取不全怎么判断是擦除块对齐问题？",
     "按 0x20000 对齐检查节点：`binwalk fw.bin | grep JFFS2` 的偏移应落在 0x20000 整数倍。判据："
     "偏移 % 0x20000 != 0 时，说明前面有 bootloader 或分区头，用 `dd skip=<对齐值>` 切出后再提。"),
    ("x-fw-gzip-total",
     "一串 gzip 解出来大小对不上，怎么核？",
     "gzip 尾 8 字节是 CRC32 + ISIZE（原始长度，小端）。判据：`dd if=part0.gz skip=<size-4> | xxd` 读 ISIZE，"
     "与实际解压输出字节数比对；不等说明流被截断或中间有拼接，按单流逐个解再求和。"),
    ("x-fw-uboot-crc",
     "U-Boot 环境区怎么验证没被改过？",
     "环境区结构是若干 `key=value\\0`，末尾 4 字节 CRC32（小端）。判据："
     "`python -c \"import zlib;d=open('env.bin','rb').read();print(hex(zlib.crc32(d[:-4])&0xffffffff),d[-4:].hex())\"`，"
     "两个值一致才算完整；不一致时环境会被 U-Boot 重置为默认。"),
    ("x-fw-mtd-offsets",
     "mtdparts 里的偏移怎么换算成文件里的绝对位置？",
     "按顺序累加：`256k(u-boot),64k(env),4m(kernel),-(rootfs)` → u-boot 0x0、env 0x40000、kernel 0x50000、"
     "rootfs 0x450000。判据：在 rootfs 偏移处应命中文件系统魔数（`hsqs` 或 `UBI#`）；"
     "若偏移处是 0xFF 填充，说明前面某分区实际更大。"),
    ("x-fw-dtb-size",
     "dtb 的总大小字段和实际长度不一致怎么办？",
     "总大小在偏移 4（大端 4 字节）。判据：`xxd -s <off> -l 8 fw.bin` 读 0xD00DFEED 后的 4 字节，"
     "与 `dtc -I dtb -O dts` 成功解析所需长度比对；偏小时按 padding 到 4 字节对齐补齐再解析。"),
    ("x-fw-ext4-block",
     "ext4 超级块里怎么读块大小与 inode 数？",
     "超级块在分区偏移 0x400，块大小在 +0x18（log block size），inode 数在 +0x0。判据："
     "块大小 = 1024 << log；`dumpe2fs -h part.img` 输出的 Block count × 块大小 应等于分区大小（误差 < 1%）。"),
    ("x-fw-i2c-dump",
     "从 I2C EEPROM 读出来的内容怎么判断是配置还是固件？",
     "先看头部 ASCII：`xxd -l 64 eeprom.bin`。判据：出现 `MAC=`、`SN=`、`BOARD=` 这类键值即配置；"
     "出现 `hsqs`/`UBI#`/`1F 8B` 即固件段；两者都无且熵 > 7.5 视为加密配置。"),
    ("x-apk-manifest-sdk",
     "怎么确认 APK 的 targetSdk，进而判断哪些行为受限制？",
     "`aapt dump badging app.apk | grep -E 'sdkVersion|targetSdkVersion'`。判据："
     "targetSdk >= 30 时明文 HTTP 默认被禁（需 usesCleartextTraffic=true 显式开启）；"
     ">= 31 时 exported 必须显式声明，缺失即构建失败。"),
    ("x-apk-dex-method",
     "想确认某个方法是否被内联/删除，怎么查？",
     "反编译后按方法名搜：`jadx -d out app.apk` 后 `grep -rn 'methodName' out/sources`。判据："
     "在 smali 里 `grep -c '.method' classes.dex.dump` 统计方法数，与 dex 头 method_ids_size（偏移 0x58）比对，"
     "两者不等说明有方法被裁剪。"),
    ("x-apk-so-symbol",
     "怎么确认 so 里某个导出函数真的被 Java 调到？",
     "两向对齐：so 侧 `readelf --dyn-syms lib.so | grep <name>`，Java 侧 `grep -rn 'native ' out/sources` 找声明。"
     "判据：静态注册要求符号名形如 `Java_<pkg>_<Class>_<method>`（包名点换下划线），"
     "不匹配则必然走 RegisterNatives 动态注册。"),
    ("x-ace-dualview-baseline",
     "做反作弊对照前，基线该采哪些点？",
     "三点：模块只读页（.text+0x1000）、堆对象、栈地址。判据：每个点 `kitty_dualview samples=3` 全绿才算干净基线；"
     "三点里任一点红，先修环境（驱动版本/HVCI），否则后续所有对比都带噪声。"),
    ("x-ace-writeback-cost",
     "写回环会不会影响被测进程的性能？",
     "会短暂影响：写入 + 回读各一次，通常 < 1 ms。判据：在 `ALLOC` 页做 3 轮，记录总耗时；"
     "若单轮 > 50 ms，说明页被换出或驱动路径异常，应先 `KM_PA` 检查是否在物理内存。"),
    ("x-ace-evidence-json",
     "反作弊证据的最小字段集是什么？",
     "六个字段：时间戳、pid、地址、类型、三视图值、结论标签。判据：`logs/anti-ace-*.jsonl` 每行必须含这六项，"
     "缺 `结论标签` 的行不能进统计；同一地址的多行按时间排序后才可判断是否稳定分叉。"),
    ("x-ace-scope-limit",
     "一次 acescan 能覆盖多大范围？",
     "默认只采样模块基址一个点，不代表全模块。判据：`kitty_acescan samples=3` 的结论仅对该地址成立；"
     "要覆盖多页需显式给 `addr`，且每点独立采样——把单点结论写成「无拦截面」属过度推断。"),
]

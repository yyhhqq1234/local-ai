# -*- coding: utf-8 -*-
"""forge2 A1 · ELF/SO 静态识别（40 条）。自有样本的静态判据，不涉及绕过。"""
GROUP = "A"
CAT = "kb-re"

ROWS = [
    ("elf-phdr-vs-shdr",
     "一个 .so 的节头全被抹了，还能不能看出段布局？",
     "能，走程序头不走节头：`readelf -lW lib.so` 列出 PT_LOAD 的 p_offset/p_vaddr/p_filesz/p_memsz，"
     "段布局就回来了。判据：e_shoff=0 且 e_shnum=0 时 `readelf -SW` 输出为空，但 `readelf -h` 的 "
     "e_phoff 仍非 0、e_phnum 仍等于 8~12 —— 这两个字段非 0 就说明程序头表完好。"),
    ("elf-pie",
     "怎么一眼分清 PIE 和静态链接？",
     "看 e_type 与 PT_INTERP：`readelf -hW a.out` 里 ET_DYN 且 `readelf -lW` 有 PT_INTERP → PIE 动态；"
     "ET_EXEC 且无 PT_INTERP、无 PT_DYNAMIC → 静态。补充判据：静态链接的 .symtab 里 local 符号常在 2000 以上，"
     "而 strip 过的 PIE 只剩不到 30 个 .dynsym 导出。"),
    ("elf-initarray",
     "main 之前执行的代码藏在哪，怎么定位？",
     "在 .init_array：`readelf -x .init_array a.out` 一串 8 字节小端指针，就是构造函数地址；"
     "`objdump -d --start-address=0x<ptr> --stop-address=0x<ptr+0x80> a.out` 直接看它做什么。"
     "判据：.init_array 条目数 = (节大小)/8，x86_64 每条 8 字节、AArch64 也是 8 字节，别按 4 字节数。"),
    ("elf-finiarray",
     "退出时才跑的逻辑在哪个节？",
     "在 .fini_array，与 .init_array 对称：`readelf -x .fini_array` 取指针，"
     "`objdump -d` 该地址可见 __attribute__((destructor)) 注册的函数。判据：.fini_array 通常只有 1-3 条，"
     "而 .init_array 常见 5-40 条 —— 数量反了就说明读到的是 .dynamic 里 DT_INIT_ARRAY 的旧值。"),
    ("elf-arch",
     "同一个工程编出 x86_64 和 AArch64 两个 .so，逆向时要盯的差异有哪些？",
     "先看 `readelf -hW` 的 e_machine：0x3E 是 x86_64、0xB7 是 AArch64、0x28 是 ARM32。"
     "调用约定差异最影响读代码：AArch64 参数在 x0-x7、返回 x0、LR 在 x30 且 `bl` 范围 ±128 MB；"
     "x86_64 参数在 rdi/rsi/rdx/rcx/r8/r9。栈帧上 AArch64 常见 `stp x29,x30,[sp,#-0x20]!` 一次压 32 字节，"
     "x86_64 是 `push rbp` 8 字节。"),
    ("elf-pltgot",
     "PLT 和 GOT 的关系怎么在文件里验证？",
     "`readelf -rW lib.so` 看 .rela.plt 的条目数与 `objdump -d -j .plt` 的桩数量必须相等，"
     "每个桩固定 16 字节（x86_64）。判据：DT_BIND_NOW 存在或 GNU_RELRO 段覆盖 .got.plt → 启动即绑定，"
     "否则首次调用才写 GOT；`readelf -dW` 里 BIND_NOW 与 FLAGS_1 NOW 任一出现即算全绑定。"),
    ("elf-strip-find",
     "strip 过的二进制，怎么从入口摸到真正的业务逻辑？",
     "从 _start 反推：`readelf -hW` 取 Entry，`objdump -d --start-address=0x<entry>` 看到 "
     "`lea rdi,[rip+...]` 把 main 地址传给 __libc_start_main（第二个参数）。拿到 main 后再用 "
     "`strings -tx` 取字符串偏移，配合 xref 找引用点。判据：__libc_start_main 的调用点一定在 entry 后 0x40 字节内。"),
    ("elf-needed",
     "怎么快速列出这个 so 依赖哪些库、以及依赖链断在哪？",
     "`readelf -dW lib.so | grep NEEDED` 列直接依赖；`ldd ./lib.so` 会解析整条链并标 not found。"
     "判据：ldd 报 not found 时用 `LD_DEBUG=libs ./prog 2>&1 | grep -i 'search path'` 看实际搜索路径，"
     "路径列表里缺的那一条就是断点；`readelf -dW` 的 RUNPATH 与 RPATH 同时存在时 RUNPATH 优先。"),
    ("elf-rpath",
     "二进制里写死的库搜索路径在哪看、优先级如何？",
     "`readelf -dW bin` 看 RPATH/RUNPATH 字符串；优先级为 DT_RPATH（仅老式）→ LD_LIBRARY_PATH → DT_RUNPATH → "
     "ldconfig 缓存。判据：字符串里出现 `$ORIGIN` 表示相对自身路径，按 `readelf -dW` 输出的偏移在文件里"
     "`xxd -s <off> -l 128` 能读到原文，含 $ORIGIN 时该条长度通常 < 64 字节。"),
    ("elf-reloc",
     "重定位表里怎么区分代码引用和数据引用？",
     "按类型：`readelf -rW` 里 R_X86_64_JUMP_SLOT / R_AARCH64_JUMP_SLOT 是函数（走 PLT），"
     "R_*_GLOB_DAT 是数据指针，R_*_RELATIVE 是 PIE 基址加法。判据：JUMP_SLOT 条目数 == .plt 桩数；"
     "RELATIVE 条目数通常占 .rela.dyn 的 80% 以上，出现大量 GLOB_DAT 说明有外部全局变量引用。"),
    ("elf-tls",
     "线程局部变量在 ELF 里怎么落盘？",
     "看 PT_TLS 段：`readelf -lW lib.so | grep TLS` 给 p_filesz（初始化镜像）与 p_memsz（含 .tbss 的零区）。"
     "判据：p_memsz > p_filesz 时差额就是未初始化 TLS；访问方式看 `%fs:0x0`（x86_64）或 `mrs x0,tpidr_el0`（AArch64），"
     "偏移为负值表示落在 TLS 块之前。"),
    ("elf-priority",
     "多个构造函数同时存在时，执行顺序由什么决定？",
     "由节顺序与优先级属性：.preinit_array 整体先于 .init_array，.init_array 内部按 "
     "`__attribute__((constructor(101)))` 的数字升序（101-65535）。判据：`readelf -x .init_array` 的条目顺序"
     "就是执行顺序，条目数 N 与 .init_array 节大小必须满足 size == N*8；顺序与优先级数字不一致说明"
     "编译单元被拆到了不同目标文件。"),
    ("elf-symver",
     "同一个符号有多个版本时，运行时到底绑哪个？",
     "看 .gnu.version 与 .gnu.version_r：`readelf -V lib.so` 列出每个符号的版本索引，"
     "`objdump -T lib.so | grep GLIBC_` 显示默认版本。判据：同一名字出现 `@@` 与 `@` 两种写法时，"
     "`@@` 是默认版本（无版本请求时绑它），`@` 只能被显式 dlvsym 取到。"),
    ("elf-static",
     "拿到一个不认识的 ELF，先判它是不是静态链接，依据是什么？",
     "`readelf -lW` 没有 PT_INTERP、`readelf -dW` 没有 NEEDED，两条同时成立即静态。"
     "辅助判据：`.symtab` 里 STT_FUNC 的 local 符号数 > 1500、文件里有 `__libc_start_main` 但 .dynsym 为空 —— "
     "这两条出现基本可确定是静态 glibc。"),
    ("elf-soname",
     "so 导出符号少得可疑，是不是被隐藏了？",
     "看 `.dynsym` 与编译可见性：`readelf --dyn-syms -W lib.so | wc -l` 只有个位数，而 "
     "`nm -D --defined-only lib.so` 也少，说明用 `-fvisibility=hidden` 编的，只留了显式导出的。"
     "判据：如果 .dynsym 里 UND 符号很多而 DEFINED 极少，导出面就是刻意收窄的；此时找逻辑只能靠字符串 xref。"),
    ("elf-buildid",
     "线上崩了，怎么确认本地这份 .so 和崩溃栈是同一份？",
     "比 build-id：`readelf -n lib.so | grep 'Build ID'` 取 20 字节十六进制，与 crash 日志里 "
     "`/usr/lib/debug/.build-id/xx/yyyy.debug` 的路径拼法一致（前 2 位做目录、其余做文件名）。"
     "判据：build-id 相同则镜像逐比特相同；不同则连符号都对不上，别硬套。"),
    ("elf-antidebug",
     "怎么静态判断这个 so 有没有反调试？",
     "搜导入与调用点：`readelf --dyn-syms -W lib.so | grep -E 'ptrace|prctl|syscall'`，"
     "再 `objdump -d` 找 `PTRACE_TRACEME`（请求码 0）的调用。判据：ptrace 第一次参数为 0、"
     "返回值 -1 时走到 exit 分支，是最常见的自检；另有 `/proc/self/status` 字符串 + TracerPid 关键字组合。"),
    ("elf-wx",
     "段权限里同时可写可执行，意味着什么？",
     "`readelf -lW` 的 Flg 列出现 `RWE` 即为 W+X 段。判据：正常编译产物只有 R E 的代码段与 RW 的数据段，"
     "出现 RWE 通常是加壳/自解码器或 JIT；再配合 p_filesz 明显小于 p_memsz（如 0x200 vs 0x8000）"
     "可判定运行时才填内容。"),
    ("elf-entropy",
     "怎么用熵判断 .text 被加密或压缩？",
     "按节算熵：`readelf -SW` 取节偏移与大小，`dd if=lib.so bs=1 skip=<off> count=<size> | ent` 或 "
     "python 里 `collections.Counter(bytes)` 算香农熵。判据：正常代码段熵 5.8-6.3，"
     "> 7.2 基本可判加密/压缩；同时 .text 的 p_filesz 与实际可执行指令长度不符时更确定。"),
    ("elf-overlay",
     "文件末尾多出一大段不在任何段里的数据，怎么确认？",
     "算末段边界：`readelf -lW` 取所有 PT_LOAD 的 p_offset+p_filesz 最大值 M，文件大小 S，"
     "S - M 就是附加区。判据：差值 > 0x1000 时 `xxd -s <M> -l 64` 看头部特征（PK/7z/RAR/mz 等魔数），"
     "差值 < 0x200 一般是节名表或签名末尾，忽略。"),
    ("elf-thumb",
     "ARM32 的入口地址是奇数，正常吗？",
     "正常，最低位是 Thumb 标志：`readelf -hW` 的 Entry 若为 0x...1，实际指令地址要减 1 再按 Thumb 反汇编。"
     "判据：e_flags 里 EF_ARM_ABI_FLOAT 与 .ARM.attributes 的 Tag_CPU_arch 一起看；"
     "反汇编时 `objdump -d -M force-thumb` 与不加该参数的结果差异很大，用入口奇偶决定。"),
    ("elf-endian",
     "大小端怎么判，判错了会怎样？",
     "`readelf -hW` 的 Data 字段：2's complement, little endian / big endian；对应 EI_DATA 字节 1 或 2。"
     "判据：`xxd -l 16` 的第 6 字节就是 EI_DATA，值为 1 是小端、2 是大端；读错端序时 e_type 会变成 "
     "0x0200 之类的怪值，一眼可辨。"),
    ("elf-machine",
     "一批样本里混了不同架构，怎么批量归类？",
     "批量读头：`for f in *; do readelf -hW $f 2>/dev/null | grep Machine; done` 或 python 里读偏移 18 的 "
     "2 字节（e_machine）。判据：0x3E=x86_64、0xB7=AArch64、0x28=ARM、0x08=MIPS、0x32=IA64；"
     "同一批里出现两种以上就要按架构分桶再做后续分析。"),
    ("elf-jni",
     "so 是 JNI 库，入口在哪、怎么确认？",
     "先看导出：`readelf --dyn-syms -W libfoo.so | grep -E 'JNI_OnLoad|Java_'`。有 Java_* 说明是静态注册，"
     "函数名即类与方法；只有 JNI_OnLoad 说明走 RegisterNatives 动态注册。判据：JNI_OnLoad 的第一个动作通常是 "
     "`GetEnv` 取 JNIEnv（参数 rdi），随后 `FindClass` 的字符串在 .rodata 里能以 `strings -tx` 定位。"),
    ("elf-ctor-odd",
     ".init_array 里有个指针不落在 .text，正常吗？",
     "不正常但要看清落点：`readelf -SW` 比对指针所属节，落在 .data/.bss 说明构造函数在运行时才被填（自修改或壳），"
     "落在堆/匿名映射说明是 JIT。判据：指针值小于镜像基址或大于末段末尾 → 运行时才有效；"
     "此时静态反汇编该地址只会得到零字节。"),
    ("elf-relro",
     "RELRO 开没开、怎么从文件里看出来？",
     "`readelf -lW` 找 GNU_RELRO 段并看它覆盖到哪个地址；`readelf -dW` 看 BIND_NOW。"
     "判据：GNU_RELRO 的末地址 ≥ .got.plt 起始地址才算 full RELRO；只覆盖到 .got 是 partial。"
     "两者都没有时 .got.plt 在运行时可写，这是动态改跳转的前提条件之一。"),
    ("elf-decrypt",
     "字符串全是乱码，但程序能跑，怎么找解密逻辑？",
     "先定位解密循环：搜 `xor` 指令密集区（`objdump -d lib.so | grep -c xor` 明显高于均值的位置），"
     "再看是否被 .init_array 调用。判据：解密函数通常带立即数密钥（`xor eax,0x5A` 这类）或按索引异或，"
     "循环上界来自一个常量；把该常量与密文长度比对（如 0x1A3）能确认是整块解密还是逐串解密。"),
    ("elf-patch-count",
     "想知道某个函数被 inline 展开成几处，怎么数？",
     "按特征字节数：`objdump -d lib.so | grep -c '<关键指令序列>'`，或用 `r2 -q -c '/x 4889e5' lib.so` 找 "
     "`mov rbp,rsp` 这类序言。判据：同一函数被展开 N 次会出现 N 份相同序言 + N 个不同的调用点偏移；"
     "配合 `nm -C` 里该符号为 local 且地址数 > 1 更确定。"),
    ("elf-lddebug",
     "so 加载失败但报错很含糊，怎么定位到底缺什么？",
     "开加载器日志：`LD_DEBUG=libs,files ./prog 2>&1 | head -40`，看它在哪些目录找过、最后停在哪个 soname。"
     "判据：日志里 `trying file=` 的最后一条就是失败点；若 soname 带版本（libfoo.so.3）而磁盘只有 "
     "libfoo.so.2，就是 ABI 版本不匹配，不是路径问题。"),
    ("elf-glibcver",
     "换机器就报 GLIBC_2.34 not found，怎么确认是符号版本问题？",
     "`objdump -T bin | grep GLIBC_` 列出所需版本，对照目标机 `ldd --version` 的 glibc 版本。"
     "判据：所需最高版本 > 目标机版本即失败；`readelf -V` 的 .gnu.version_r 里每个 Verneed 条目"
     "带一个版本号与依赖库名，条目数就是需要的外部版本集合。"),
    ("elf-ctf-main",
     "静态链接的 PIE，怎么在没有任何符号的情况下找到 main？",
     "三步：`readelf -hW` 取 Entry；反汇编 entry 找到传给 __libc_start_main 的第二个参数（rdi 是 main）；"
     "再 `objdump -d --start-address=0x<main>`。判据：__libc_start_main 调用前一定有 "
     "`mov rdi, <imm>` 或 `lea rdi, [rip+...]`，该 imm 就是 main 的链接时地址；PIE 下要加运行时基址。"),
    ("elf-musl",
     "怎么判断是 musl 还是 glibc 编的？",
     "看解释器与字符串：`readelf -lW bin | grep interpreter`，出现 `/lib/ld-musl-` 即 musl；"
     "glibc 是 `/lib64/ld-linux-x86-64.so.2`。判据：musl 静态二进制里没有 `__libc_start_main` 的 "
     "GLIBC 版本标记，且 `strings bin | grep -c musl` ≥ 1；两者都静态时靠 .comment 与符号命名区分。"),
    ("elf-align",
     "p_align 小于 0x1000 的段是怎么加载的？",
     "按页对齐规则：加载器用 `mmap` 以页为单位映射，p_align < 0x1000 时按页粒度向上取整，"
     "段内偏移靠 p_vaddr & 0xFFF 保持。判据：`readelf -lW` 里出现 p_align=0x4 或 0x8 的 PT_LOAD，"
     "说明链接时用了 `-n`（不按页对齐），此时文件偏移与内存偏移的差值不再等于基址，计算地址要按段单独算。"),
    ("elf-bss",
     ".bss 特别大意味着什么？",
     "通常是一个大缓冲区或静态数组：`readelf -SW lib.so | grep bss` 看大小，"
     "在代码里搜引用该区间基址的指令（`objdump -d | grep <bss起始地址>`）。判据：.bss > 0x100000（1 MB）"
     "且该区间只被 memset/memcpy 引用，基本可判为数据缓冲区；若还被大量索引访问，可能是查找表。"),
    ("elf-comment",
     "怎么从文件本身判断编译器和版本？",
     "`readelf -p .comment lib.so` 直接给编译器串（GCC: (Ubuntu 11.4.0...) / clang version 17）。"
     "判据：节被 strip 掉时改看 `.note.gnu.property` 与指令风格（`endbr64` 出现说明开了 CET）；"
     "另外 GCC 与 clang 的 PLT 桩字节不同，`objdump -d -j .plt` 前 16 字节可区分。"),
    ("elf-cet",
     "怎么确认二进制开了 CET/CFI？",
     "`readelf -n lib.so` 找 GNU_PROPERTY_X86_FEATURE_1_AND，值含 IBT(1)/SHSTK(2)；"
     "代码里 `endbr64`（f3 0f 1e fa）出现在每个间接跳转目标前。判据：`objdump -d lib.so | grep -c endbr64` "
     "与间接调用点数量同量级即可确认；只有零星几条说明是编译器插入的非全量。"),
    ("elf-jnireg",
     "动态注册的 JNI，怎么把 Java 方法与 native 函数对上？",
     "跟 RegisterNatives：JNI_OnLoad 里调用 `env->RegisterNatives(clazz, methods, n)`，"
     "methods 是一片 JNINativeMethod{name,sig,fnPtr}（每项 3 个指针，x86_64 24 字节）。判据："
     "在 .data.rel.ro 里按 24 字节步长读，第二列指向 .rodata 的签名字符串，第三列就是 native 函数地址。"),
    ("elf-so-load",
     "库加载时报 undefined symbol，怎么快速定位是哪个符号、谁需要它？",
     "`nm -D --undefined-only lib.so | grep <名字>` 找需求方，`nm -D --defined-only` 在候选库里找提供方。"
     "判据：`LD_DEBUG=symbols ./prog 2>&1 | grep -A3 'symbol='` 会打印查找顺序与最终绑定；"
     "若提供方存在但版本不同（GLIBC_2.34 vs 2.17），日志会停在 version check 那一步。"),
    ("elf-objdump-choice",
     "读 ELF 到底该用 readelf 还是 objdump？",
     "分工：结构（头/段/节/动态/重定位/版本）用 `readelf -h -l -S -d -r -V`，指令与数据用 "
     "`objdump -d -s -t`。判据：objdump 依赖节头，节头被抹时只输出 `file format elf64-x86-64` 一行；"
     "readelf 只依赖程序头也能出段信息 —— 所以节头缺失的场景必须先用 readelf。"),
]

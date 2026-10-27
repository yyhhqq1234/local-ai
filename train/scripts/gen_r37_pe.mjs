#!/usr/bin/env node
/**
 * gen_r37_pe.mjs — R37 PE/ELF 专项（补领域重心：PE/ELF 从 9% 拉回）
 *
 * 事实源：kitty-toolbox/src/patch.ts 的 PEInfo / PESection 真实字段
 *   PEInfo: eLfanew machine machineName numberOfSections timeDateStamp characteristics
 *           magic is64 entryPointRva entryPointVa imageBase sectionAlignment fileAlignment
 *           sizeOfImage checksumStored checksumOffset checksumComputed sections[]
 *   PESection: name virtualSize virtualAddress sizeOfRawData pointerToRawData
 *              characteristics readable writable executable
 *   machine 表: 0x014c I386 / 0x8664 AMD64 / 0xaa64 ARM64 / 0x01c4 ARMNT / 0x0200 IA64
 *   另：ELF 侧走 REA（inspect_binary_layout 绑 pwntools-elf，Linux x64 only）
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r37-pe-elf.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (kind, user, assistant, meta) => out.push({
  id: 'kitty-r37-' + kind + '-' + String(out.length).padStart(4, '0'),
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: Object.assign({ __stage: 're', __kind: kind, __round: 'r37' }, meta || {}),
});

// ===== PE 头 =====
add('pe-header', '拿到一个 PE，info 里该先看哪几个字段',
  'kitty_patch action=info path=<样本>\n\n按顺序看五个：\n1) **machine** —— 0x014c I386 / 0x8664 AMD64 / 0xaa64 ARM64 / 0x01c4 ARMNT / 0x0200 IA64。架构错了后面全错\n2) **is64 / magic** —— 决定用 32 位还是 64 位调试器\n3) **entryPointRva / entryPointVa** —— 入口点，加壳样本这里常落在异常节\n4) **imageBase / sizeOfImage** —— 后续算地址和窗口的基准\n5) **numberOfSections + sections[]** —— 节表，加壳判据全在这里\n\n判据：machine 与目标环境不一致就不用往下分析了。', { topic: 'pe' });

add('pe-header', 'e_lfanew 是什么，为什么要看',
  '它是 DOS 头里指向 NT 头（PE 签名）的偏移。\n\n正常值：0x80 ~ 0x200 之间（常见 0xE8、0xF8、0x100）。\n\n异常判据：\n· 极大（如 0x100000）→ 头结构被改或文件有问题\n· 极小（< 0x40）→ 与 DOS 头重叠，畸形\n\n用途：dump 重建时头部区间要靠它确定，错了整个重建会错位。', { topic: 'pe' });

add('pe-header', 'characteristics 和 DLL 属性怎么看',
  'PEInfo 的 characteristics 是 COFF 头标志位：\n· 0x0002 EXECUTABLE_IMAGE —— 可执行\n· 0x2000 DLL —— 是 DLL\n· 0x0100 32BIT_MACHINE\n· 0x0020 LARGE_ADDRESS_AWARE\n\n判据：\n· 有 0x2000 但文件名是 .exe → 可能是伪装或壳改了\n· 没有 0x0002 → 纯资源 DLL 或畸形\n\n用途：判断"这是不是真的可执行"，比看扩展名可靠。', { topic: 'pe' });

add('pe-header', 'timeDateStamp 能说明什么',
  '编译时间戳（PEInfo 里已格式化成时间串）。\n\n三个用途：\n1) 判断样本新旧（跟同族样本比）\n2) **异常值识别**：0 或 0xFFFFFFFF 常见于被改过/壳生成\n3) 家族聚类：同批编译的样本时间戳接近\n\n判据：时间戳在未来 / 为 0 / 与文件其他特征矛盾 = 被处理过。\n\n注意：它不是可靠证据，可被伪造，只能当辅助信号。', { topic: 'pe' });

add('pe-header', 'sectionAlignment 和 fileAlignment 多少算正常',
  '正常值：\n· sectionAlignment 通常 0x1000（内存对齐）\n· fileAlignment 通常 0x200（文件对齐）\n· 两者满足 fileAlignment ≤ sectionAlignment\n\n异常判据：\n· sectionAlignment < 0x1000 → 非标准构建（某些壳/打包器）\n· fileAlignment 不是 2 的幂 → 畸形或手工改过\n· 两者相等且很小 → 典型的压缩壳特征\n\n用途：这是加壳识别的辅助证据，单看不够但组合起来很有效。', { topic: 'pe' });

// ===== 节表 =====
add('pe-section', '节表怎么看有没有壳',
  '三个判据，命中一个就可疑，命中两个基本确定：\n\n1) **可写且可执行**：某节 readable+writable+executable 全 true（即 RWX）\n2) **尺寸比异常**：virtualSize / sizeOfRawData > 3（内存里比文件里大很多 → 运行时解压）\n3) **节名异常**：非标准名（.text/.rdata/.data/.rsrc/.reloc 之外），如 UPX0/UPX1/.aspack/.themida\n\n判据：\n· 只命中 1 → 可能是 JIT 或自修改代码\n· 1 + 2 → 高度可疑加密壳\n· 三个全中 → 确定有壳', { topic: 'pe' });

add('pe-section', 'RWX 节一定是壳吗',
  '不一定，但要看它是什么节：\n\n· **.text 是 RWX** → 极可疑（正常代码段只读+执行）\n· **非标准名节是 RWX** → 高度可疑\n· **.data 可写**但不可执行 → 正常\n· 有个小 RWX 节且 virtualSize 很小 → 可能是 JIT stub\n\n判据：RWX + 该节 virtualSize 明显大于 sizeOfRawData = 运行时解压区。\n\n正确做法：kitty_patch action=info 看 full sections，别只看一个节。', { topic: 'pe' });

add('pe-section', 'virtualSize 和 sizeOfRawData 的比例说明什么',
  '比例 = virtualSize / sizeOfRawData：\n\n· ≈1 → 正常（文件里多大，内存里就多大）\n· **>3 → 运行时解压**（壳把压缩数据读进大缓冲区展开）\n· <1 → 文件里有对齐填充，正常\n· sizeOfRawData = 0 但 virtualSize > 0 → 该节在文件里无数据（BSS 类），正常\n\n判据：>3 是加密壳的强信号；配合 RWX 基本可定。', { topic: 'pe' });

add('pe-section', '入口点落在哪个节有讲究吗',
  '有。正常入口点应在**代码节**（通常是 .text）。\n\n异常判据：\n· 入口点在最后一个节（壳的解压 stub 常放这里）\n· 入口点所在节是 RWX\n· 入口点 RVA 落在节边界外（畸形）\n· 入口点指向 `.rsrc` / `.reloc`（被改过）\n\n判据：entryPointRva 换算成节索引，不在代码节就重点看那一节。', { topic: 'pe' });

add('pe-section', '节名能透露出用了什么壳吗',
  '常见指纹（节名直接暴露）：\n· UPX0 / UPX1 → UPX\n· .aspack / .adata → ASPack\n· .themida / .winlice → Themida/WinLicense\n· .vmp0 / .vmp1 → VMProtect\n· .enigma1 / .enigma2 → Enigma\n· .petite → Petite\n· .MPRESS1 / .MPRESS2 → MPRESS\n\n判据：节名 + kitty_die 指纹互相印证；节名可被改，别只靠它。', { topic: 'pe' });

add('pe-section', '为什么有的样本节表看着完全正常但确实是壳',
  '因为高级壳会**保留标准节名和尺寸**，把解压逻辑放进入口点前后的小段代码里。\n\n识别转向其他面：\n· 入口点代码特征（前几条指令是不是 pushad/解密循环）\n· 导入表极小（只有 LoadLibrary/GetProcAddress）→ 运行时解析 API\n· 节表正常但 sizeOfImage 异常大\n· kitty_die 的启发式指纹\n\n判据：节表正常 + 导入表极小 + 入口代码怪 = 别只看节表。', { topic: 'pe' });

// ===== 校验和与对齐 =====
add('pe-checksum', 'checksumStored 和 checksumComputed 不一致说明什么',
  'PEInfo 同时给了存储值与计算值：\n\n· 相等 → 文件未被改动（或改动后重算过）\n· **不相等** → 文件被改过，且没重算校验和\n\n用途：\n1) 判断补丁是否已落地（打完补丁后 checksum 会变）\n2) 判断样本是否被二次修改\n\n注意：Windows 对多数用户态 exe **不校验** checksum，所以不一致不影响运行 —— 别把它当"文件损坏"。\n\n判据：kitty_patch 的 fix_checksum 默认 true，打完会自动重算。', { topic: 'pe' });

add('pe-checksum', '补丁后要不要重算校验和',
  '默认要（fix_checksum=true）。\n\n重算的好处：\n· 文件看起来像正常构建产物\n· 某些加载路径（驱动、部分安装器）会校验\n\n不重算的场景：\n· 做字节级差分，需要与原文件完全对应\n· 明确知道目标不校验\n\n判据：不确定就开着；关掉只在明确需要时。', { topic: 'pe' });

// ===== 导入导出 =====
add('pe-import', '导入表能反推出什么',
  'kitty_sym action=imports path=<样本> 或 source=mem module=<模块>\n\n三个用法：\n1) **语言/框架**：MSVCR*.dll → C/C++；coreclr.dll → .NET；python*.dll → PyInstaller\n2) **加壳信号**：导入表极小（只有 LoadLibrary/GetProcAddress/VirtualAlloc）→ 运行时解析 API\n3) **能力推断**：有 WinINet/WS2_32 → 联网；有 CreateRemoteThread → 注入能力\n\n判据：导入表条目数 < 10 且全是加载器 API = 高度可疑。', { topic: 'pe' });

add('pe-import', '导出表怎么用来定位函数',
  'kitty_sym action=exports path=<样本>（文件）或 source=mem module=<模块>（内存）\n\n用途：\n· 拿导出名 → 直接知道功能（DLL 的 API 面）\n· 拿导出 RVA → 下断点/写补丁的目标\n· 内存 exports 可以确认模块是否真加载（注入验证）\n\n判据：注入后 source=mem 列不到你的 dll 导出 = 没加载成功。', { topic: 'pe' });

add('pe-import', 'resolve 什么时候用',
  'kitty_sym action=resolve module=<模块> name=<符号>\n\n把"模块+符号名"解析成实际 VA，用于：\n· 下断点（DBG_BP / x64dbg seed 需要 VA，不是名字）\n· 调用函数（拿地址后写进 LUA 或注入代码）\n\n判据：resolve 拿不到 = 名字写错或模块没加载。\n\n注意：地址是当前会话的，重启后 ASLR 会变，不要写死。', { topic: 'pe' });

add('pe-import', '重定位和 imageBase 的关系',
  '如果实际加载基址 ≠ imageBase，PE 会应用重定位（.reloc）修正绝对地址。\n\n影响：\n· 静态分析看到的地址是 imageBase 基准的 RVA\n· 运行时要加实际基址\n· dump 时如果重定位已应用，和磁盘文件比对会不一致（**属预期**）\n\n判据：dump 一致率低 + 有 .reloc 节 → 先怀疑重定位差异，不是 dump 坏了。', { topic: 'pe' });

// ===== ELF =====
add('elf', 'ELF 样本怎么分析',
  '工作台的 ELF 线走 **REA**，不是本地工具：\n\n1) kitty_rea action=status 确认服务在\n2) kitty_rea action=list query=binary 找相关工具\n3) kitty_rea action=describe tool=inspect_binary_layout\n4) kitty_rea action=call tool=inspect_binary_layout args={...}\n\n**关键坑**：inspect_binary_layout 固定绑 `pwntools-elf`（**Linux x64 only**），换 provider 无效。深度分析要走进阶工具组：open_binary → binary_overview → list_procedures / analyze_function。\n\n判据：报 provider_unavailable 就是选错入口，不是环境问题。', { topic: 'elf' });

add('elf', 'ELF 和 PE 的分析方法差异在哪',
  '结构层面：\n· PE：DOS 头 + NT 头 + 节表（section），按节组织\n· ELF：ELF 头 + 程序头（segment）+ 节头（section），双视图\n\n分析差异：\n· PE 关注节表特征（加壳判据）\n· ELF 关注 segment 映射（PT_LOAD）与动态链接（.dynamic/PLT/GOT）\n\n工具差异：工作台本地工具（patch/sym/dump）都是 **PE 专用**，ELF 必须走 REA。\n\n判据：拿 ELF 去跑 kitty_patch = 用错工具。', { topic: 'elf' });

add('elf', 'ELF 的 PLT/GOT 是什么',
  'PLT（Procedure Linkage Table）+ GOT（Global Offset Table）是延迟绑定的实现：\n· 首次调用外部函数 → 跳到 PLT → PLT 查 GOT → GOT 指向解析器 → 解析后回填 GOT\n· 之后调用直接走 GOT\n\n分析价值：\n· 静态看 PLT 表 = 知道调了哪些外部函数\n· 动态 hook 常改 GOT 项（比改代码段隐蔽）\n· 看 GOT 是否被改 = 检测 hook 的一个方向\n\n判据：想知道"调了谁"看 PLT；想知道"被改成谁"看 GOT。', { topic: 'elf' });

add('elf', '静态链接的 ELF 怎么下手',
  '没有动态符号表，工具面就变了：\n· 不能靠 imports 反推\n· 需要靠字符串、常量、系统调用序列识别\n· 剥符号后要恢复函数边界（REA 的 list_procedures 可以）\n\n判据：file size 很大 + 几乎没有 .dynamic → 静态链接。\n\n做法：先用 REA 的 binary_overview 拿布局，再 list_procedures 看函数密度，最后挑关键函数 analyze_function。', { topic: 'elf' });

// ===== 固件 / CTF 边界 =====
add('firmware', '工作台能做固件分析吗',
  '**本地工具面没有固件专用工具**。\n\n能做：\n· 拿到固件里提取出的 PE/ELF 二进制 → 走常规静态/动态分析\n· 提取出的文件系统里的脚本（Lua/JS/Python）→ 对应工具\n\n不能做（需外部工具）：\n· binwalk / unblob 解包\n· squashfs / UBI / JFFS2 挂载\n· 固件仿真（Firmadyne/QEMU 全系统）\n\n判据：任务是"从 .bin 里提文件系统"就走外部工具链，别指望 kitty_。', { topic: 'firmware' });

add('firmware', '固件里提出来一个 ELF，怎么接进来',
  '三步：\n1) 判断架构（ELF 头 e_machine）\n2) **架构不匹配就没法本机跑**：ARM/MIPS 的 ELF 在 x64 Windows 上只能静态分析\n3) 静态走 REA：kitty_rea action=call tool=inspect_binary_layout args={path:...}\n\n判据：\n· x86/x64 → 可以进一步动态\n· ARM/MIPS/RISC-V → 只能静态（除非有对应仿真环境）', { topic: 'firmware' });

add('ctf', 'CTF 逆向题一般怎么快速入手',
  '四步，别一上来就 IDA：\n1) `kitty_patch action=info` —— 架构、节表、是否加壳（30 秒）\n2) `kitty_die action=scan` —— 语言/壳指纹（10 秒）\n3) `kitty_sym action=imports` —— 用了什么库（反推语言：.NET/Python/Go）\n4) 按语言选工具：.NET→dnspy / Python→PyInstaller 特征 / Go→REA 的 Go 识别\n\n判据：能跑起来就先跑，看输入输出行为比读反汇编快。', { topic: 'ctf' });

add('ctf', 'CTF 里 check 函数怎么快速定位',
  '三个方向：\n1) **字符串**：找 "wrong"/"correct"/"flag" 附近引用 → kitty_patch action=find str\n2) **断点**：在 strcmp/memcmp/printf 下断 → 往回看调用栈\n3) **交叉引用**：反编译后找 check 的调用者\n\n判据：\n· 有明文字符串比对 → find 最快\n· 逐字符校验 → 断点更快\n· 加密校验 → 只能反编译看算法', { topic: 'ctf' });

add('ctf', 'CTF 里反调试怎么处理',
  '常见手法与对策：\n· IsDebuggerPresent / PEB.BeingDebugged → 断点改返回值或改内存标志\n· NtGlobalFlag / HeapFlags → 同上\n· 时间检测（rdtsc/RDTSC）→ 难搞，考虑 patch 掉检测\n· 异常处理反调试 → 需要正确处理异常分发\n\n工作台的工具面：\n· 静态：kitty_patch 找检测函数并 patch\n· 动态：kitty_x64dbg（C 通道）比 A 通道调试面安全\n\n判据：先静态定位检测点，再决定 patch 还是绕过。', { topic: 'ctf' });

add('ctf', 'CTF 里加壳题的最短路径',
  '三步：\n1) `kitty_die action=scan` 认壳（UPX 最常见）\n2) UPX 直接 `upx -d`（外部工具）→ 脱完再分析\n3) 非标准壳 → `kitty_dump module=<名> unmap=true` 内存 dump + 重建\n\n判据：\n· UPX 脱完节表恢复正常 → 直接分析\n· 内存 dump 一致率低是正常的（带壳）→ 只要代码段对就能看\n\n坑：别在壳上直接反编译 —— 看到的是壳不是程序。', { topic: 'ctf' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byKind = out.reduce((a, x) => (a[x.meta.__kind] = (a[x.meta.__kind] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_kind: byKind }, null, 1));

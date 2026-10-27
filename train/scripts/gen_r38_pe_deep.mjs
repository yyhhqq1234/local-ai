#!/usr/bin/env node
/**
 * gen_r38_pe_deep.mjs — R38 PE 深度目录补强（把 PE/ELF 从 13.4% 拉到 15%+）
 *
 * 覆盖 PE 的可选头数据目录与其他结构判读点：重定位/资源/TLS/延迟导入/异常/签名/Manifest/调试目录/导出转发/COFF 符号
 * 事实基础：kitty_patch info 的 PEInfo 字段 + kitty_sym + kitty_dump
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r38-pe-deep.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (kind, user, assistant, meta) => out.push({
  id: 'kitty-r38-' + kind + '-' + String(out.length).padStart(4, '0'),
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: Object.assign({ __stage: 're', __kind: kind, __round: 'r38' }, meta || {}),
});

const PE = [
  ['重定位表有什么分析价值',
    '位于 .reloc 节，记录"当加载基址 ≠ imageBase 时需要修正哪些地址"。\n\n分析价值：\n1) **判断是否可重定位**：有 .reloc → 可以被 ASLR / 手动改基址加载\n2) **定位绝对地址引用**：重定位项里都是代码里的绝对地址，是找全局变量/函数指针的线索\n3) **dump 一致率解释**：运行时重定位已应用，dump 和磁盘文件必然不同（属预期）\n\n判据：dump 一致率低 + 有 .reloc → 先归因重定位，别怀疑 dump。\n\n工具：kitty_dump 不做重定位修复（那是 Scylla 的活），只做布局重建。'],
  ['资源节 .rsrc 能看出什么',
    '.rsrc 存图标/版本信息/Manifest/对话框等。\n\n用途：\n1) **版本信息**（VS_VERSIONINFO）：公司名/产品名/版本号 —— 判断样本来源与家族\n2) **Manifest**：requestedExecutionLevel（requireAdministrator 说明要提权）\n3) **图标**：图标哈希可用于家族聚类\n4) 木马常把 payload 藏进资源节（资源释放型）\n\n判据：.rsrc 异常大（几百 KB 以上）而程序很小 → 检查里面是不是塞了二进制。\n\n工具：kitty_patch action=info 只能看节大小，取资源内容要外部工具（如 ResourceHacker）。'],
  ['TLS 回调是什么，为什么和加壳有关',
    'TLS（线程局部存储）目录里有一组回调，**在入口点之前执行**。\n\n加壳利用：把解压/反调试代码放进 TLS 回调 → 比入口点更早运行，常规断点（在入口点下断）会错过。\n\n识别：\n· 数据目录里有 TLS 项（非 0）\n· TLS 回调地址落在非标准节\n\n判据：入口点正常但样本行为"在入口前就发生了" → 查 TLS 回调。\n\n工具：工作台没有直接的 TLS 解析 action，需要反编译看 TLS 目录指向的数组。'],
  ['延迟导入（Delay Import）怎么看',
    '普通导入在加载时就解析；延迟导入在**首次调用时**才解析。\n\n加壳常用：把敏感 API 放进延迟导入，静态看 imports 时看不到，运行时才出现。\n\n识别：\n· 数据目录有 Delay Import 项\n· kitty_sym action=imports 的结果里缺少预期 API，但样本行为明显用了\n\n判据：imports 表干净得可疑（只有几个常见 API）+ 数据目录有延迟导入 = 重点查这里。'],
  ['异常目录 .pdata 说明什么',
    '.pdata 存异常处理信息（x64 的 unwind 数据）。\n\n用途：\n1) **判断是否 x64 原生**：x64 程序必须有 .pdata 才能正常抛异常\n2) **函数边界**：.pdata 的条目基本对应函数范围，可用于恢复被剥符号的函数边界\n3) 缺失 .pdata 的 x64 程序 → 可能是壳生成 / 畸形 / 或被剥\n\n判据：x64 + 无 .pdata + 反编译困难 = 壳或人工构造。'],
  ['签名（Authenticode）怎么判断有没有',
    '数据目录的 Security 项（索引 4）指向签名。\n\n判断：\n· 有 Security 目录且大小 > 0 → 有签名\n· 无 → 未签名\n\n进一步验证要看证书链（工具外做，如 Get-AuthenticodeSignature）。\n\n判据：\n· 未签名的驱动/系统组件 = 高度可疑\n· 有签名但证书过期/无时间戳 → 加载可能时好时坏（KMCS 不可信）\n\n注意：签名可被剥离，剥完就是"未签名"，不能据此判断原始状态。'],
  ['Manifest 里的 requestedExecutionLevel 有什么用',
    '三种取值：\n· asInvoker —— 普通权限\n· highestAvailable —— 尽可能高\n· requireAdministrator —— 强制提权（会弹 UAC）\n\n分析价值：\n1) 判断样本是否需要管理员（很多内核操作/驱动安装需要）\n2) 木马常伪装成 requireAdministrator 来"名正言顺"提权\n\n判据：普通工具却要求 admin → 看它提权后干什么。'],
  ['调试目录（Debug Directory）能透露什么',
    '存 PDB 路径/GUID/年龄。\n\n用途：\n1) **PDB 路径**：常含编译机用户名/项目名（信息泄露）\n2) **GUID + Age**：可以拿去公开符号服务器匹配（如果 PDB 公开）\n3) 有调试目录说明是开发构建（非发布 strip 版）\n\n判据：PDB 路径里出现 `C:\\Users\\<名字>\\...` → 直接拿到作者线索。'],
  ['导出转发（Export Forwarder）是什么',
    '导出表里某一项不是地址而是字符串（如 `NTDLL.RtlAllocateHeap`）→ 表示转发到另一个 DLL 的函数。\n\n用途：\n· API set / 转发 DLL 常见（kernel32 转发到 kernelbase）\n· 分析时看到"导出地址落在字符串区"就是转发\n\n判据：kitty_sym action=exports 里某条地址异常（落在 .rdata）→ 检查是不是转发。'],
  ['COFF 符号表还在说明什么',
    '正常发布版会 strip 掉 COFF 符号；还在说明：\n· 开发构建（未 strip）\n· 或者被人为加回去\n\n价值：有符号表 = 函数名/全局变量名直接可读，分析成本骤降。\n\n判据：file size 偏大 + 有符号表 → 先看符号名，可能不用反编译就懂逻辑。'],
  ['PE 里怎么找 OEP（原始入口点）',
    '加壳样本的真实入口点（OEP）。三条路：\n\n1) **栈平衡法**（pushad/popad 配对）：壳常用 pushad 保存现场，解压完 popad 后跳到 OEP —— 在 popad 后下断\n2) **内存断点**：对代码节下写断点，壳解压写回时中断，往回跟\n3) **区段特征**：解压后代码节的熵会下降，找熵突变的边界\n\n工具：kitty_x64dbg（C 通道）比 A 通道调试面安全。\n\n判据：OEP 处通常是编译器标准 prologue（push rbp; mov rbp,rsp）。'],
  ['怎么判断一个 PE 是 32 位还是 64 位',
    '两层判断，都要看：\n1) **COFF 头 machine**：0x014c = I386（32 位）/ 0x8664 = AMD64（64 位）/ 0xaa64 = ARM64\n2) **可选头 magic**：0x10b = PE32 / 0x20b = PE32+（64 位）\n\n两者应一致。\n\n判据：\n· machine 说 32 位但 magic 说 64 位 → 畸形或被改\n· 决定用哪个位数的调试器/注入器（bits=32/64）\n\n工具：kitty_patch action=info 里 is64 字段直接给结论。'],
  ['PDB 路径能还原出什么信息',
    '典型 PDB 路径：`C:\\Users\\dev\\source\\repos\\ProjectX\\x64\\Release\\ProjectX.pdb`\n\n可提取：\n· 用户名（dev）\n· 项目名（ProjectX）\n· 构建配置（Release/Debug）\n· 架构（x64/Win32）\n· 源码目录结构\n\n用途：家族归因、判断是否泄露构建、找同源样本（同路径 = 同作者/同机器）。\n\n判据：多个样本 PDB 路径相同 → 同源。'],
  ['怎么快速判断一个 exe 是打包的还是原生的',
    '四步 30 秒判断：\n1) `kitty_patch action=info` —— 节名/RWX/尺寸比\n2) `kitty_die action=scan` —— 壳指纹\n3) `kitty_sym action=imports` —— 导入表规模\n4) 看 file size vs sizeOfImage 的比例\n\n判据组合：\n· 节名异常 + 导入少 → 加壳\n· 节名正常 + 导入正常 + 尺寸合理 → 原生\n· 节名正常但导入极少（<10）+ 有 RWX 小段 → 高级壳（保留节名）'],
  ['.NET 程序怎么快速识别',
    '三条独立判据：\n1) 数据目录第 14 项（CLR Runtime Header）非 0\n2) 导入表有 `mscoree.dll` 的 `_CorExeMain` / `_CorDllMain`\n3) `kitty_die` 报 .NET\n\n识别后：\n· 用 `kitty_dnspy action=open`（有混淆先 `action=deobf`）\n· 不要用 Ghidra/IDA 硬啃 IL —— 效率差一个量级\n\n判据：有 CLR 头就是 .NET，直接切工具链。'],
  ['Go 编译的程序有什么特征',
    '静态链接为主，特征明显：\n· 体积大（几 MB 起，含 runtime）\n· 导入表很少（多是 syscall 直接调）\n· 字符串里有大量 runtime 相关（runtime.main / goroutine / GC）\n· 有 `Go build ID` 段（`.note.go.buildid`）\n\n分析：\n· 符号没剥的话函数名直接可读（含包路径）\n· 用 REA 的 Go 识别能力（list_procedures 会给恢复的函数名）\n\n判据：体积大 + 导入少 + 有 Go 字符串 = Go 程序。'],
  ['Rust 编译的程序怎么认',
    '特征：\n· panic 字符串（`panicked at`、`RUST_BACKTRACE`）\n· 大量 monomorphize 后的函数（名字带 hash 后缀）\n· 字符串里有 crate 名\n· 体积中等偏大，静态链接\n\n分析难点：函数名被 mangle（`_ZN...`），可读性差。\n\n判据：看到 `panicked at src/...` 就是 Rust。'],
  ['PyInstaller 打包的程序怎么拆',
    '特征：\n· 体积大（含 Python 运行时）\n· 导入表有 python3*.dll\n· 字符串有 `PYZ-00.pyz`、`_MEIPASS`\n\n拆法：\n· 外部工具（pyinstxtractor）先解包\n· 拿到 .pyc 后反编译\n· 工作台的 `kitty_proto` / `kitty_lua` 都不是这条线\n\n判据：有 _MEIPASS 就是 PyInstaller；工作台无直接工具，需外部解包后回到 PE/脚本分析。'],
  ['PE 的 overlay（附加数据）是什么',
    '文件末尾超出最后一个节 sizeOfRawData 的数据。\n\n用途：\n· 安装器/自解压包把 payload 放这里\n· 加壳器把加密数据附在后面\n· 数字签名也在末尾（但属 Security 目录管辖）\n\n识别：\n· file size > 最后一个节 pointerToRawData + sizeOfRawData\n· 差值就是要看的 overlay 大小\n\n判据：overlay 很大（MB 级）→ 提出来单独看，很可能是第二个 PE 或压缩包。'],
  ['PE 的节对齐和文件对齐不一致会怎样',
    'sectionAlignment（内存）通常 0x1000，fileAlignment（文件）通常 0x200。\n\n不一致的后果：\n· 加载器按 sectionAlignment 映射到内存\n· 磁盘读写按 fileAlignment\n· 两者混乱 → 手工解析偏移会算错\n\n判据：\n· sectionAlignment < 0x1000 → 非标准（某些壳/打包器）\n· 解析偏移必须用 pointerToRawData，不能用 virtualAddress 直接当文件偏移\n\n坑：把 RVA 当文件偏移用，读到的全是错位数据。'],
  ['怎么从 PE 里提取嵌入的第二个 PE',
    '三个位置：\n1) **overlay**（文件末尾附加数据）\n2) **资源节**（.rsrc 里的 RCDATA）\n3) **代码节里的加密块**（需运行时解密）\n\n识别方法：\n· 搜 `MZ` 签名（`kitty_patch action=find pattern="4D 5A"`）\n· 看命中位置的上下文是否像完整 PE\n\n判据：找到 MZ 后校验 e_lfanew 与 PE 签名，两个都对才是真 PE。'],
  ['PE 里怎么找全局变量',
    '三条路：\n1) **.data / .bss 节**：初始化的在 .data，未初始化在 .bss\n2) **重定位表**：绝对地址引用会出现在 .reloc\n3) **反编译器的交叉引用**：找 `mov reg, [0x...]` 形式的引用\n\n判据：地址落在 .data 且被多处引用 → 全局配置/状态变量。\n\n工具：kitty_ghidra / kitty_ida 的 xrefs 最快。'],
  ['怎么判断 PE 是否被修改过（除校验和）',
    '四个信号：\n1) checksumStored ≠ checksumComputed\n2) 时间戳异常（0 / 未来 / 与内容矛盾）\n3) 节之间有空洞数据（正常编译器会填充 0，被改过可能留残留）\n4) 签名无效（改过之后签名必失效）\n\n判据：2 个以上信号同时出现 → 高度可疑被改。\n\n注意：加壳样本天然"被改"，这些信号在壳上没意义，只对原生样本有效。'],
  ['PE 的 SizeOfImage 和实际节范围不一致怎么办',
    'sizeOfImage 应该 = 最后一个节的 VirtualAddress + VirtualSize 向上对齐。\n\n不一致的后果：\n· 按 sizeOfImage 分配/映射会出现空洞或截断\n· dump 时按 sizeOfImage 取会多读或少读\n\n判据：\n· sizeOfImage 明显大于节范围 → 可能是壳预留空间\n· 小于 → 畸形\n\n正确做法：dump 用 MODENUM 的真实窗口，不要用 sizeOfImage 硬算。'],
  ['怎么判断 PE 是 DLL 还是 EXE',
    '两个判据，看第一个就够：\n1) **COFF characteristics** 含 0x2000（IMAGE_FILE_DLL）→ DLL\n2) 有导出表（通常 DLL 才有，但 EXE 也能有）\n\n坑：\n· 扩展名不可靠（.dll 可以是 EXE，反之亦然）\n· 有导出不一定是 DLL（有些 EXE 导出函数给插件用）\n\n判据：只看 characteristics 的 0x2000 位。'],
  ['PE 的导入表里出现 ordinals（序号导入）说明什么',
    '按序号导入而不是按名字：`kernel32.dll #123` 这种。\n\n出现场景：\n· 作者故意隐藏调用了什么（序号不直观）\n· 老程序（某些系统 DLL 只有序号导出）\n· 加壳/恶意样本常用\n\n分析：需要查对应 DLL 的导出表把序号映射回名字（kitty_sym action=exports 对照）。\n\n判据：序号导入 + 导入表很小 → 刻意隐藏 API 使用。'],
  ['PE 的 Rich Header 是什么',
    '位于 DOS 头与 NT 头之间的一段未文档化数据（微软链接器写入），记录各工具版本与出现次数。\n\n价值：\n1) **家族归因**：Rich Header 的校验值 + 工具版本组合可区分编译环境\n2) **判断是否被重建/脱壳**：壳生成或人工构造的 PE 通常没有 Rich Header 或格式错误\n\n判据：原生样本有 Rich Header，壳生成的常缺失 → 辅助判据。'],
  ['怎么快速看一个 PE 的编译环境',
    '三个字段组合：\n1) **Rich Header** —— 链接器版本（VS 版本）\n2) **timeDateStamp** —— 编译时间\n3) **PDB 路径** —— 构建机与配置\n\n判据组合示例：\n· Rich Header 显示 VS2019 + 时间 2021 + PDB 路径 …\\Release\\ → 2019 年发布的发布版\n· 无 Rich Header + 时间 0 → 壳/手工构造\n\n用途：样本归因、判断是不是同一个人做的。'],
];

for (const x of PE) add('pe-deep', x[0], x[1], { topic: 'pe' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
console.log(JSON.stringify({ out: OUT, samples: out.length }, null, 1));

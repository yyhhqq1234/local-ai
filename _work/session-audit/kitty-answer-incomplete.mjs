// 为 28 条 incomplete 补答，并合并进 train-kitty-core.jsonl
import fs from 'node:fs';
import path from 'node:path';

const R = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/data/kitty-reverse';
const P = (f) => path.join(R, f);

// key = 问题全文（用于精确对齐）
const ANSWERS = {
  '用上次那个 pid 13297 继续，读基址第一行 qword。':
`先别直接读 —— 「上次那个 pid」是最容易出错的一环，绑定可能早就被换掉了。

[1] 校验当前绑定
kitty_ce op="CUR"
判据：回包里 pid 就是 13297 才算还挂着；不是就先 OPEN|13297 重绑（OPEN 幂等，重绑不会出问题）。
退出：CUR 的 pid 与目标一致。

[2] 取模块基址
kitty_ce op="MODBASE|<模块名>"      （名不确定就先 MODENUM 看清单）
判据：回包 base 落在 0x7FF6xxxx / 0x0040xxxx 这类映像基址区间。
退出：拿到唯一基址。

[3] 读第一行 qword
kitty_ce op="R|0x<base>|qword"
判据：PE 映像头 8 字节，正常是 0x0000000300905A4D（低 2 字节 4D 5A = "MZ"）；读到 0 或 ERR 说明基址不是映像基址。
退出：拿到 MZ 签名，说明基址+读通道都通。

坑：MODBASE 返回的是加载基址，不是首节地址；读 0x0 只能看到 DOS 头，要看入口就去 R|base+0x3C 取 e_lfanew 再跳。`,

  '当前挂着的目标进程 的分析做到一半，用上次那个 pid 13297 继续，读基址第一行 qword。 这里对不上。我之前的做法是 发过 OPEN，哪里有问题？':
`对不上大概率不是读错了，是**绑定被换过**。OPEN 是幂等的，但它会改 CUR —— 中途只要对别的 pid 发过一次 OPEN，CUR 就不是 13297 了，之后的 R 全打在错误的进程上（或者打在不存在的地址上回 0）。

按这个顺序定位：
[1] kitty_ce op="CUR"                → pid 是不是 13297
[2] kitty_ce op="LP"                 → 13297 还在不在进程表里
[3] kitty_ce op="MODENUM"            → 模块窗口有没有拿到（size=0 的模块改用镜像头兜底）
[4] kitty_ce op="R|0x<base>|qword"   → 首 8 字节应为 0x…5A4D（MZ）

判据：
· CUR.pid ≠ 13297 → 就是重绑问题，OPEN|13297 后重读
· CUR 对但 LP 里没有 → 进程已退，换新 pid
· 读回 0x0 → 地址不在映射内（不是基址），先 MODBASE 再读
· 读回 5A4D → 通道正常，之前"对不上"是拿错了进程

不要做的事：不要原地反复 R 同一个地址，ERR 不解决参数问题只会重复同一个错。`,

  '情况是这样：当前挂着的目标进程，我用 发过 OPEN 走了一遍，结果 用上次那个 pid 13297 继续，读基址第一行 qword。 不符合预期。下一步该怎么判断？':
`分三层判，自上而下，每层都要有结论再往下：

[1] 通道层
kitty_status probe=true          → 桥/cmd/rep 时戳是否新鲜
kitty_ce op="PING"               → 宿主活着才谈后面

[2] 绑定层
kitty_ce op="CUR"                → 当前绑定的 pid
kitty_ce op="LP"                 → 目标 pid 是否仍在
判据：CUR 与 LP 不一致 = 绑定失效，重 OPEN 即可。

[3] 地址层
kitty_ce op="MODBASE|<名>"       → base
kitty_ce op="R|0x<base>|qword"   → 期望 0x…5A4D
判据：非 5A4D 就不是映像头；ERR 则地址未映射。

交叉验证（可选，最稳）：kitty_dualview addr=<base> vt=qword 同时取 R / KM_R / KM_PR，三视图一致说明读到的是真映射，分叉说明有重定向或保护。

退出条件：能明确说出"是通道坏了 / 绑错了 / 地址不对"三者之一，再针对修。`,

  '宿主通道健康看一眼':
`kitty_status probe=true
判据：看四件事 —— cmd/rep 时戳是否在最近几十秒内、sync 根 pending 数是否为 0、最近回包有没有 ERR、KittyCE 进程是否存在。
· pending > 0 → 有未落定的异步作业，等一轮或 SYNC_ARCHIVE
· rep 时戳陈旧 → 宿主卡住，用 kitty_drv action=host 看门狗拉一次（单实例重拉 + PING + SYNC 归一）
· KittyCE 不在进程表 → 宿主没起来，kitty_init action=init 或 kitty_drv action=host

只读探活不要带 probe 也能看时戳，带 probe=true 会多发一次 PING，确认链路是活的。`,

  '抓一下这个 app 的 http 流量':
`三段式，先探再抓后解：

[1] 探针
kitty_net action=status
判据：mitmdump / tshark 是否可用；都缺就换等价路径（进程内 hook 或 kitty_frida 挂 SSL_read/SSL_write）。

[2] 起抓
kitty_net action=capture port=8080 out="logs/net-<ts>.pcap"
判据：返回 pid，说明后台已起。
注意：只抓明文 HTTP 直连；走 TLS 的要么给 mitm 装 CA，要么直接 hook 加解密函数，别指望 pcap 里能读。

[3] 收口
kitty_net action=stop pid=<pid>
kitty_net action=decode out="logs/net-<ts>.pcap" filter="http.request"

判据：decode 出 host + path + status 才叫抓到；只有 TCP 三次握手没有应用层 = 抓错网卡或没走代理。
退出条件：能列出该 app 的请求清单（方法/主机/路径/状态码）。`,

  '记事本那个进程，读一下它主模块基址的第一行。':
`[1] 绑进程
kitty_ce op="OPEN|notepad.exe"     （同名多开就用 pid，先 LP 看）
判据：回包 OK 且 CUR 指向目标。

[2] 取主模块基址
kitty_ce op="MODBASE|notepad.exe"
判据：base 形如 0x7FF6xxxxxxxx。

[3] 读首行
kitty_ce op="R|0x<base>|qword"
判据：低 2 字节为 4D 5A（MZ）→ 读到的是 DOS 头，正常。
若是 0x0 → 基址取错（可能拿到的是 size 为 0 的模块），MODENUM 复核再取。

补充：记事本是 64 位时 qword 读没问题；32 位进程也照样能读 qword（跨两个 dword），不影响判 MZ。`,

  '看看当前夜跑状态':
`kitty_loop_status
判据看五项：宿主是否在线、靶标是否在跑、服务通道是否健康、红线（keys/memory/protection）计数、特征库版本，以及最近一条 loop-<ts>.jsonl 的时间与结论。
· 最近日志时间很旧 → 夜跑没在跑，或跑完停了
· 红线计数 > 0 → 上一轮触发过门禁，先看日志里哪一站红的
· 特征库/模式库为空 → 跑起来也只会空转

只读操作，不动宿主。要真跑一轮用 kitty_loop mode=dry 先看流水，再 mode=round confirm=true。`,

  '按流程靶标进程叫什么、pid 多少，顺手把它的模块基址全拿下来':
`[1] 列进程
kitty_ce op="LP"
判据：按名字找靶标；同名多个挑主进程（父进程/窗口线程那条）。

[2] 绑定
kitty_ce op="OPEN|<pid 或 名>"

[3] 模块清单 + 基址
kitty_ce op="MODENUM"
判据：每行 name / base / size。size=0 的模块是驱动或特殊映射，用 kitty_pchain 或镜像头兜底取窗口。

[4] 交叉验证（可选）
kitty_sym action=exports source=mem module=<主模块名> limit=5
判据：能解析出导出名说明 base 正确。

退出条件：拿到 主模块名 + base + 全部模块 (name, base, size) 三元组清单。
坑：MODENUM 的顺序不保证，别按序号记，按 name 建索引。`,

  'R 和 W 的参数类型都有哪些？':
`vt 取值五种：byte | word | dword | qword | bytes:N

· byte   1 字节，0x00-0xFF
· word   2 字节
· dword  4 字节（默认，最常用）
· qword  8 字节（64 位指针/基址）
· bytes:N  N 字节裸读，回十六进制串；N 上限受 MEMDUMP_HEX 4096 约束

写的话形态一样：
kitty_ce op="W|0x<addr>|dword|1234"      （十进制或 0x 前缀都吃）
kitty_ce op="W|0x<addr>|bytes:4|90 90 90 90"

判据：回包带 echo 的 addr+vt+value 三项一致才算写入成功；值不符说明被拦截或页保护（改用 kitty_wpb 或 kitty_prot 提权后重试）。
注意 W 类必须 confirm=true，这是写回环门禁。`,

  '按流程用 IDA 批量把函数列表和字符串都导出来':
`[1] 先探档位
kitty_ida action=status
判据：Pro / Free / 无 —— Free 版没有 Hex-Rays，decompile 会空，只能走 functions+strings。

[2] 批处理分析
kitty_ida action=analyze target="<样本路径>" out="logs/ghidra-<name>-<ts>"
判据：产物落盘（四件套），超时按 600s 给足。

[3] 取函数
kitty_ida action=functions out="<产物目录>" limit=2000
[4] 取字符串
kitty_ida action=strings out="<产物目录>" limit=2000

判据：函数数 > 200 且字符串里能看到 API 名/路径/URL 才算分析成功；函数数个位数 = 分析没跑完或样本是壳。
退出条件：拿到 functions.json + strings 清单两件产物路径。

批量的关键：analyze 一次跑完，之后 functions/strings 都是读产物，不要反复 analyze。`,

  '按流程notepad2.exe 双击闪退，怀疑加壳但节表看着正常，怎么定性':
`节表正常不代表没壳 —— 现代壳会把原始节表还回来，只是节内容在内存里才解密。

[1] 静态定性
kitty_die action=detect target="notepad2.exe"
判据：编译器/壳/保护器三栏；UPX/Themida/VMProtect 这类会直接点名。

[2] 熵与节特征
kitty_patch action=info path="notepad2.exe"
判据：看各节 entropy、VirtualSize vs RawSize 差异、入口点是否落在最后一节或非 .text。
· entropy > 7.2 且入口在非常规节 → 高度可疑加壳
· RawSize 远小于 VirtualSize → 运行时解压

[3] 导入表贫富
kitty_sym action=imports path="notepad2.exe"
判据：只有 LoadLibrary/GetProcAddress 两三个导入 = 壳的典型签名。

[4] 动态定性（最关键）
kitty_x64dbg action=run target="notepad2.exe"
在入口停住后单步/跑到 OEP，用 kitty_dump module=<主模块> 转储内存镜像，看转储里是否出现完整导入表与正常节 —— 出现即确认是壳。

退出条件：能说出「是壳/不是壳 + 壳类型 + OEP 大致位置」三件事。`,

  '按流程跑一段调试脚本：下断、跑、收集、回读':
`用 program 一次给全动作序列，别一条条发（每条都要等回包，慢且容易错序）：

kitty_x64dbg action=program steps=[
  "bpl",                                        # 清旧断点
  "bp kernelbase.CreateFileW",                  # 下断
  "run",
  "savedata D:\\\\out\\\\arg1.bin, rcx, 64",    # 存第1参
  "savedata D:\\\\out\\\\arg2.bin, rdx, 260",   # 存第2参（宽字符路径）
  "run",                                        # 继续
  "bpl",
  "stop"
] confirm=true

判据：
· 命中停在 CreateFileW → savedata 文件非空且首 2 字节是盘符 UTF-16（如 43 00 3A 00 = "C:"）
· 没命中 → 参数断点条件不满足（进程没走这条 API），换 NtCreateFile 或加条件 bp

[读回]
kitty_x64dbg action=readdb / readlog logfile="<会话日志>"
判据：日志里能看到命中次数、寄存器快照、保存路径。

坑：savedata 的长度要给够（宽字符路径通常 260*2），给 64 会截断。`,

  '一键跑反作弊对抗，看有没有拦截面':
`kitty_acescan target="<靶标>" module="<主模块>" attach=true writeback=true samples=3
它一条龙做：驱动守卫 → 宿主探活 → OPEN → KM_ATTACH → 模块窗口 → 三视图门禁(R/KM_R/KM_PR) → 写回环 → 落 logs\\acescan-<ts>.json。

判据（两级）：
· gate=green 且写回全通 → **无拦截面**：三层视图一致、写回被接受
· gate=red 或写回失败 → 有拦截：
  - 三视图分叉 → 有内存视图重定向（EPT/hook）
  - 写回被拒 → 页保护或写保护（走 kitty_wpb 或 km 侧写）
  - KM_ATTACH 失败 → 内核面被拦

退出条件：能给出「拦 / 不拦 + 拦在哪一层」的结论，不是只看 green/red 一个词。
注意：samples 提到 3 以上能降噪，单轮偶发分叉多半是跨 tick 采样。`,

  '按流程先确认 kitty 通道和宿主还活着，再列一下当前进程表':
`[1] 桥健康
kitty_status probe=true
判据：cmd/rep 时戳新鲜、pending=0、最近回包无 ERR。

[2] 宿主存活
kitty_ce op="PING"
判据：回 PONG/OK 才算宿主活着。超时或 ERR → 走 kitty_drv action=host 自愈（单实例重拉 + PING + SYNC 归一）。

[3] 列进程
kitty_ce op="LP"
判据：能看到 pid/name 清单，且里面有你要的靶标。

三步任一失败就停在那一步，不要跳过探活直接 LP —— 通道死了 LP 只会超时，浪费时间。
退出条件：通道 ok + 宿主 ok + 进程表拿到。`,

  '注入这个 dll 到靶标':
`kitty_inject dll="<绝对 ASCII 路径>" via=ce confirm=true module="<DLL 文件名>"
via 三种：
· ce       走 A 通道 LUA injectDLL（默认，最通用）
· ps       .NET 托管注入，不依赖 CE
· loaddll  位数敏感，bits=64/32 要显式给

判据：
· 回包 OK + 自动 MODENUM 复核里出现该模块名 → 注入成功
· 有 OK 但模块不在 → 注入器执行了却没加载（位数不匹配 / DllMain 返回 FALSE）
· ERR → 路径含中文、权限不足、目标有防护

退出条件：MODENUM 里能看到目标 DLL 的 base+size。
坑：路径必须是 ASCII，中文目录先复制到纯 ASCII 路径；32/64 位必须对齐目标进程。`,

  '把这个跳转改成永远跳':
`两步：造字节 → 落补丁（带 expect 校验，防错位）。

[1] 算无条件跳转字节
kitty_asm action=jump from=0x<指令VA> target=0x<目标VA> kind=jmp
判据：短跳得 EB xx（rel8）；距离超 127 字节会报错，改 short=false 出 E9 rel32。

[2] 落盘补丁
kitty_patch action=patch path="<PE>" at="va:0x<指令VA>" expect="74 05"  bytes="EB 05" confirm=true
判据：
· expect 必须命中，不命中会拒写（这就是防错位的保险）
· 回包给校验和与备份路径 → 说明已写并留了 .bak

[3] 复核
kitty_patch action=hash path="<PE>"
或运行时 kitty_ce op="R|0x<指令VA>|byte" → 应为 EB。

退出条件：文件字节已变 + 运行时读回也变。
注意：只在该指令确实在磁盘文件里可定位时用静态补丁；内存里改就走 kitty_ce W 或 kitty_wpb。`,

  '按流程扫描区太大报错了，怎么处理':
`S_NEW 必须给显式区间，全地址空间扫会被桥拒（也会把宿主拖死）。

[1] 拿真实窗口
kitty_ce op="MODENUM"
判据：每行 name/base/size；只扫需要的模块窗口，别扫整片 0x7FF6…。

[2] 分窗扫描
kitty_ce op="S_NEW|dword|1234|0x<base>|0x<base+size>"
判据：pending 时用 wait=true 落定；结果用 S_GET top=N 取。
· 窗口仍大 → 按 64MB 切段，逐段 S_NEW（S_FREE 后再下一段，别叠着扫）

[3] 收尾
kitty_ce op="S_FREE"

判据：命中数合理（模块内同值几千个属正常，全部地址几百万就是扫宽了）。
退出条件：在模块窗口内拿到命中列表。
替代方案：已知特征字节走 AOB 扫描（更省），全量模糊扫描留到最后手段。`,

  '用 frida spawn 模式从启动就 hook':
`[1] 环境探针
kitty_frida action=status
判据：frida / objection 是否可用；不可用就走 kitty_inject + 自写 hook DLL。

[2] spawn 挂载
kitty_frida action=spawn pkg="<进程名或包名>" script="<hook.js>" out="logs/frida-<ts>.log"
判据：spawn 模式下目标被 frida 拉起并暂停在入口，脚本先加载再 resume —— 这才是"从启动就 hook"。

hook.js 最小骨架：
Interceptor.attach(Module.getExportByName(null, 'CreateFileW'), {
  onEnter(args) { console.log('CreateFileW', args[0].readUtf16String()); }
});

[3] 收口
看 out 日志里有没有 hook 命中行；无命中 = 目标没走该 API 或脚本注入失败。

退出条件：启动阶段就能看到 hook 回调输出。
坑：spawn 会接管进程生命周期，别对正在调试的目标用；某些反调试会检测 frida 端口，需要改名/延迟加载。`,

  '按流程把某个虚拟地址翻成物理地址再物理读':
`[1] VA → PA
kitty_km action=pa addr="0x<VA>"
判据：回包 PA 形如 0x1A3C5000，且低位页内偏移与 VA 的低 12 位一致 —— 不一致说明跨页了，重新对齐。

[2] 物理读
kitty_km action=pread pa="0x<PA>" vt="qword"（或 bytes:N）
判据：读出内容与用户态 kitty_ce op="R|0x<VA>|qword" 一致 → 无重定向；不一致 → 有 EPT/影子页（这正是三视图门禁要抓的东西）。

[3] 交叉
kitty_dualview addr="0x<VA>" vt=qword samples=3
判据：R / KM_R / KM_PR 三视图同值才算读到真实物理页。

退出条件：拿到 PA + 物理读值，并能说清与用户态视图是否一致。
注意：物理读只能用 pread；pwrite 是永久拒绝项（会把引擎写死），不要试。`,

  'unity 游戏想运行时看对象，注入 explorer':
`[1] 认引擎
kitty_engines path="<游戏目录>"
判据：Mono / IL2CPP / UE / Godot 分型 —— Unity 里 Mono 和 IL2CPP 的注入件完全不同。

[2] 注入运行时浏览器
kitty_uexplorer action=inject pid=<游戏pid>
判据：回包给注入结果；MODENUM 里出现 UnityExplorer 相关模块 = 成功。

[3] 用
游戏内出现 Explorer 面板后，按 GameObject / Component / Class 三层浏览，改值前先记原值。

判据：注入成功但面板不显示 → 该版本 Unity 需要对应运行时版本（Mono 用 Mono 版，IL2CPP 用 IL2CPP 版）；版本不符会静默失败。

退出条件：能在运行时列出场景里的对象与字段。
坑：IL2CPP 游戏先确认 libil2cpp.so/dll 版本，必要时先 kitty_il2cppdumper 出 dump.cs 再定位字段偏移。`,

  '按流程宿主可能挂了，检查一下 KittyCE 进程与桥的状态，必要时自愈':
`[1] 只读体检
kitty_status probe=true
判据：KittyCE 进程在不在、cmd/rep 时戳、pending 数、最近回包。

[2] 判定挂法
· 进程不在 → 宿主没起来
· 进程在但 rep 时戳陈旧 → 卡死（可能 STOP_PENDING）
· 进程在、桥通但 PING 不通 → 通道层问题

[3] 自愈（看门狗，单实例）
kitty_drv action=host hostStart=true
它做三件事：单实例重拉 + PING 探活 + SYNC 归一（pending 清零）。
卡在 STOP_PENDING 时先 kitty_drv action=recover，再 host。

[4] 复核
kitty_status probe=true → pending=0、rep 新鲜、PING 通。

退出条件：三项全绿。
红线：不要手杀驱动、不要重建 mhtglyts；attach 类操作会杀宿主，能不动就不动。`,

  'mono 的 unity 游戏，打开 assembly 看类':
`[1] 定位托管程序集
游戏目录下找 Assembly-CSharp.dll（Mono 方案），或 <Game>_Data/Managed/。
判据：能读到 PE + CLR 头，dnSpy 才打得开。

[2] 导入 + 列类
kitty_dnspy action=import target="<Assembly-CSharp.dll>" out="logs/dnspy-<ts>"
kitty_dnspy action=types out="<产物目录>" filter="Player"
判据：能看到命名空间/类名/方法签名；类型数是 0 → 是 IL2CPP 不是 Mono（IL2CPP 没有托管 DLL，走 dump.cs）。

[3] 深挖
kitty_dnspy action=decompile target="<类全名>"

判据：方法体能反编译出 C# 才算通；只有壳/花指令 = 被混淆（de4dot 处理后再来）。

退出条件：能列出目标类的方法与字段，并指出关键方法（如 Update/TakeDamage）。
注意：Mono 游戏运行时可配合 kitty_uexplorer 直接改字段，比改 DLL 安全。`,

  '读 notepad 主模块基址第一行 dword，进程就叫 notepad。':
`[1] kitty_ce op="OPEN|notepad"
判据：回 OK；若同名多开，回包会给候选，改成 OPEN|<pid>。

[2] kitty_ce op="MODBASE|notepad.exe"
判据：base 是映像基址（notepad 常落在 0x7FF6…）。

[3] kitty_ce op="R|0x<base>|dword"
判据：dword 应为 0x00905A4D（"MZ" + 0x90 对齐填充），这是 DOS 头首 4 字节的标准值。
· 读出 0x00000000 → 基址不对或页未映射
· 读出别的值 → 可能开了 ASLR 但读的是正确基址，只要低 2 字节是 4D 5A 就正常

退出条件：拿到 base 与首 4 字节，且低 2 字节 = 4D 5A。
坑：MODBASE 参数要带扩展名，只给 "notepad" 可能匹配不到模块。`,

  '回滚刚才那个补丁':
`kitty_patch action=rollback path="<PE 路径>"
判据：
· 回包给出还原后的文件校验和，且与补丁前记录的 hash 一致 → 回滚成功
· 报找不到 .bak → 当初用了 in_place=false（写 .patched），原文件没动，无需回滚
· 报 hash 不符 → 文件在补丁后又被改过，别强回滚，先 diff

复核：
kitty_patch action=hash path="<PE>"     → 与备份比对
kitty_patch action=info path="<PE>"     → 节表/入口正常

退出条件：文件字节回到补丁前状态。
纪律：每次 patch 都留了 .bak + 校验和，回滚只认 .bak，不要手工改字节"滚回去"。`,

  'kitty_ops 里 S_NEW 的签名是什么？':
`kitty_ops filter=S_
返回里看 S_NEW 的签名：

S_NEW|<vt>|<val>|<start>|<stop>
· vt    byte|word|dword|qword
· val   目标值（十进制或 0x 前缀）
· start/stop  必须显式给区间，十六进制 VA

配套 OP：
· S_GET top=N        取命中
· S_FREE             释放结果（扫完必做，否则驻留）
· S_SNAP             快照
· S_CHANGED / S_UNCHANGED  与快照比对（模糊扫描用）

判据：S_NEW 是异步的，回包 pending 时要 wait=true 落定再 S_GET。
用法示例：
kitty_ce op="S_NEW|dword|100|0x7FF600000000|0x7FF601000000"
kitty_ce op="S_GET" top=20
kitty_ce op="S_FREE"

完整表用 kitty_ops all=true（约 10KB，慎用）。`,

  '按流程把这个 dll 的导出表列出来，我要找它的对外入口':
`[1] 磁盘侧（静态）
kitty_sym action=exports path="<x.dll>" limit=200
判据：拿到 name / ordinal / RVA 三列；导出数为 0 说明是资源 DLL 或转发导出。

[2] 内存侧（目标在跑时更准）
kitty_sym action=exports source=mem module="<x.dll>" limit=200
判据：内存导出会反映运行时的转发解析结果，与磁盘不一致 = 有 hook 或被替换。

[3] 定位对外入口
· 找初始化/注册类：DllMain 不可导出，看 DllRegisterServer / DllGetClassObject / 自定义 Init*
· 找命令面：导出名含 Create/Open/Init/Register 的优先
kitty_sym action=resolve name="<DLL>!<函数>" → 拿 VA，供下断用

判据：能指出"哪个导出是对外入口"并给出理由（导出名 + 调用约定 + 是否被其他导入引用）。

[4] 反查谁在用它
kitty_sym action=imports path="<调用方.exe>" filter="<x.dll>"

退出条件：导出清单 + 入口函数 VA + 至少一个引用方。`,

  'Access granted 这串字面量是谁在用的？从已分析的引用面里追，别让我一个个函数翻。':
`用 REA 的特性追踪，一次给全链路：

[1] 追字面量
kitty_rea action=call tool="trace_feature" args={"query":"Access granted"}
判据：回包里每个引用点带 文件/函数/地址；命中为 0 说明该字符串不在已分析引用面（或被加密存储）。

[2] 拿具体函数档案
kitty_rea action=call tool="analyze_function" args={"procedure":"<命中函数>"}
判据：伪代码里能看到字符串加载指令（lea reg, [rip+off] 或 mov reg, imm）。

[3] 反查调用链
kitty_rea action=call tool="trace_call_path" args={"start":"<命中函数>","direction":"backward"}
判据：能回溯到入口/分发点，说明谁在什么条件下用到它。

备选路径（REA 不可用时）：
kitty_ghidra action=search out="<产物目录>" filter="Access granted"
kitty_ida action=xrefs out="<产物目录>" filter="Access granted"

退出条件：给出「哪个函数在什么分支打印它 + 上游调用者」两件事，而不是只给一个地址。
注意：先 kitty_rea action=status 确认服务在跑，首用会懒启动。`,

  '按流程用 x64dbg 在这个进程打开文件时断下来，把参数存下来':
`用 seed 一步挂上 API 断点 + 命中即存参：

kitty_x64dbg action=seed \\
  addr="kernelbase.CreateFileW" \\
  seedCmd="savedata D:\\\\out\\\\CreateFileW_arg1.bin, rcx, 260" \\
  saveDb=true confirm=true

判据：
· 命中后在 out 目录出现 .bin，首 2 字节是 UTF-16 盘符（43 00 3A 00 = "C:"）→ 抓到文件路径
· 文件为 0 字节 → 断点没命中（进程没走 CreateFileW，可能走 NtCreateFile）或参数寄存器取错

若要抓第二参（访问模式）：
seedCmd="savedata ...\\\\arg2.bin, rdx, 8"      （rdx = dwDesiredAccess，dword 有效）

多参数一起存：分两次 seed，或改用 program 串动作：
kitty_x64dbg action=program steps=["bp kernelbase.CreateFileW","run","savedata ...\\\\a1.bin, rcx, 520","savedata ...\\\\a2.bin, rdx, 8","run"] confirm=true

[回读]
kitty_x64dbg action=collect logfile="<会话日志>" / readdb

退出条件：拿到参数文件 + 能读出被打开的文件路径。
坑：x64 调用约定第 1/2 参是 rcx/rdx；x86 是栈上，要用 [esp+4]/[esp+8]。`,
};

// ── 应用补答 ──
const inc = fs.readFileSync(P('train-kitty-incomplete.jsonl'), 'utf8').split('\n').filter(Boolean).map(JSON.parse);
const missed = [];
let filled = 0;
for (const o of inc) {
  const u = (o.messages.find(m => m.role === 'user') || {}).content || '';
  const a = ANSWERS[u];
  if (!a) { missed.push(u.slice(0, 40)); continue; }
  const asst = o.messages.find(m => m.role === 'assistant');
  asst.content = a;
  o.meta = { ...o.meta, __flags: (o.meta.__flags || []).filter(f => f !== 'empty_assistant').concat(['answered']) };
  filled++;
}
fs.writeFileSync(P('train-kitty-incomplete.jsonl'), inc.map(o => JSON.stringify(o)).join('\n') + '\n', 'utf8');

console.log(JSON.stringify({
  total: inc.length, filled, missed,
  emptyAnswerAfter: inc.filter(o => !String((o.messages.find(m => m.role === 'assistant') || {}).content || '').trim()).length,
}, null, 2));

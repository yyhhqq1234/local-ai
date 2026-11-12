# -*- coding: utf-8 -*-
"""补齐源：CHAIN_X2 → chain_a2、CHAIN_X3 → chain_a3、DET_X1 → det_a"""

CHAIN_X2 = [
(
"给了一个 .NET 单文件打包的 exe（40MB），dnSpy 打不开。顺序？",
"""[1] triage —— 先判是不是单文件打包
kitty_die action=detect target=APP.exe
判据：文件体积远大于同功能托管程序（40MB vs 几 MB）、CLR 目录存在但元数据区可读性差、
.ini/.rdata 里出现 BundleExtractor 风格的压缩特征 → 单文件打包。
退出条件：判定「单文件」或「普通托管」。判错会导致你在错误的层找代码。

[2] static —— 取出内嵌的托管程序集
kitty_patch action=find path=APP.exe pattern="4D 5A" from=0 limit=32
判据：内嵌 bundle 里逐个 PE 的节表；托管程序集的 .text 里能找到 "BSJB" 元数据签名。
kitty_patch action=find path=APP.exe str=BSJB limit=8
退出条件：定位到至少一个含 BSJB 的内嵌 PE 偏移。

[3] static 二次 —— 抽出后用 dnSpy 读
kitty_dnspy action=decompile target=logs\\extracted\\app.dll out=logs\\dnspy-app
判据：能否读到 <=Program.Main 或入口类的 .cs。
退出条件：拿到业务入口。抽不干净（bundle 有压缩）时改走运行期：
kitty_ce op=MODENUM 看进程里加载了哪个 Assembly 模块。

[4] dynamic —— 运行期抓真正执行的程序集
kitty_ce op=OPEN|<pid>
kitty_ce op=MODENUM
判据：模块表里出现的 .dll（非系统）就是真正在执行的那个。
kitty_dump module=<该 dll> unmap=true path=logs\\asm.bin
退出条件：得到可直接反编译的程序集镜像。

[5] 导出
产物：内嵌程序集清单 + 业务入口 + 抽取方式（静态/运行期）。
判据：dnSpy 能打开产物并显示 <=Program.Main。
不做：在 40MB 的外层 exe 上用 dnSpy 反复试 —— 外层只是 loader。""",
),
]

CHAIN_X3 = [
(
"只给了一段 shellcode（binary 片段，没有 PE 头）。判断顺序？",
"""[1] triage —— 先判架构与位置无关性
kitty_asm action=assemble code="nop" base=0x0
判据：片段首字节落在 x86/x64 常见序言（48/4C/55/53/56/57）→ x64；
E8/E9/68 + 栈操作 → x86；先按位数分流，后面所有反汇编都依赖它。
退出条件：确定位数与是否需要基址（含绝对地址 = 位置相关）。

[2] static —— 用 IDA 的 raw binary 模式反汇编
kitty_ida action=status
判据：IDA 是否有 "Binary file" 加载器（有则可直接按 16/32/64 位加载）。
退出条件：产出函数边界（shellcode 里常见 call/pop 取 EIP 的 PEB 遍历起点）。

[3] static 二次 —— 认 API 解析模式
kitty_ida action=strings out=logs\\ida-shell-<ts> limit=40
判据：出现 kernel32.dll 明文 = 走 LoadLibrary 解析；
出现 0x60/0x30/0x18 之类的结构偏移 = PEB→Ldr 手工遍历（免 API 解析）。
退出条件：判定「API 解析方式」与「是否有编码（xor 循环）」。

[4] dynamic / 等价验证 —— 在自有靶标进程里跑并观测
kitty_ce op=ALLOC
kitty_ce op="W|0xVA|bytes:N|<shellcode>" confirm=true
kitty_prot action=protect addr=0xVA size=0x1000 protect=rwx confirm=true
kitty_inject 走 CE 的 createRemoteThread 等价面，或直接用 CE LUA 执行
判据：进程内出现新线程且其入口在 0xVA 附近；再看它调了哪些 API。
退出条件：拿到执行证据（线程创建 + 至少一次 API 调用）。
注意：这是在自有靶标进程里做，不要跨进程投递。

[5] 导出
产物：位数 + API 解析方式 + 行为面 + 编码层（若有）。
判据：能说明「它怎么拿到 API」与「它做了什么」两句话。
不做：不把 shellcode 直接塞进宿主进程 —— 载体只用自有靶标。""",
),
]

DET_X1 = [
(
"想给一段校验加日志，结果把目标写崩了两次。",
"""往返1｜动作：直接在某条指令位置写 5 字节跳转
kitty_ce op="W|0x7FF6DADB1234|bytes:5|E9 XX XX XX XX" confirm=true
回包：写入成功，但目标进程随即崩溃
判读：第一次失败。E9 是 rel32 跳转，位移要按「目标 - (本指令地址+5)」算，
我直接填了目标地址的高位 → 跳到垃圾页。

往返2｜动作：改用 kitty_asm 算相对位移
kitty_asm action=jump kind=jmp from=0x7FF6DADB1234 target=0x7FF6DAE00000
回包：给出 5 字节（E9 + rel32）
判读：位移正确了，但又崩 —— 因为可写不可执行。

往返3｜动作：查页属性
kitty_prot action=query addr=0x7FF6DADB1234
回包：Protect=PAGE_EXECUTE_READ
判读：第三次失败原因明确。该页可执行但不可写，写入是走了别的路径才成功的
（或者是 PTE 直写），执行时 DEP 生效失败。

往返4｜动作：先取写权限再写，并保存原字节
kitty_ce op="R|0x7FF6DADB1234|bytes:16"      → 记录原 16 字节（回滚用）
kitty_prot action=protect addr=0x7FF6DADB1234 size=0x1000 protect=rwx confirm=true
kitty_ce op="W|0x7FF6DADB1234|bytes:5|<kitty_asm 算出的 5 字节>" confirm=true
kitty_ce op="R|0x7FF6DADB1234|bytes:5"
回包：字节一致
判读：这次写入有效且页可执行。

往返5｜动作：把日志函数放到独立可执行页，别挤在目标代码里
kitty_ce op=ALLOC
kitty_prot action=protect addr=0xNEW_VA size=0x1000 protect=rwx confirm=true
kitty_ce op="W|0xNEW_VA|bytes:N|<日志桩：保存寄存器 → 写日志 → 恢复 → 跳回>" confirm=true
kitty_asm action=jump kind=jmp from=0x7FF6DADB1234 target=0xNEW_VA
判读：桩放独立页，原位置只留一条跳转 —— 这才是稳定的做法。

收敛｜末态验证
kitty_ce op="R|0x7FF6DADB1234|bytes:5"        → 与 kitty_asm 输出一致
kitty_ce op="R|0xNEW_VA|bytes:N"              → 桩字节一致
功能侧：触发原逻辑，日志落地且进程不崩
回滚：把记录下的原 16 字节写回原地址，再 kitty_ce op=FREE|0xNEW_VA
末态：日志生效、进程稳定、回滚路径可用。
复盘：三条硬条件 —— 相对位移用 kitty_asm 算、页必须 RWX、桩放独立页。""",
),
]

# （DET_FIX 已合并进 det_b.py 的第 7 条，此处不再重复提供）

# -*- coding: utf-8 -*-
"""re-detour-trajectory 扩量 E（91-120）"""

DET_E = [
("我在 32 位进程里读 TEB 用了 gs 寄存器，全错。",
"""往返1｜动作：按 x64 惯例找 gs
kitty_dbg action=regs
回包：无 gs 基址（32 位用 fs）
判读：第一次失败。32 位进程的 TEB 在 fs:[0]。

往返2｜动作：以为需要内核态
kitty_km action=attach pid=<pid>
回包：附加成功但读不到 TEB
判读：方向错了。

往返3｜动作：改用 fs 基址
kitty_ce op="R|0xFS_BASE|dword"
回包：拿到 TEB 指针
判读：这一步对了。

往返4｜动作：读 TEB 字段
kitty_ce op="R|0xTEB+0x30|dword"
回包：PEB 指针

收敛｜末态验证
kitty_ce op="R|0xPEB+0x0C|dword" → Ldr 指针可解析
末态：TEB/PEB 链可用。
复盘：32 位 fs、64 位 gs；先核位数再取基址。"""),

("我以为 sample 在读写注册表，其实在读 WMI。",
"""往返1｜动作：按注册表路径找
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=16
回包：命中少量（多为系统无关）
判读：第一次失败。

往返2｜动作：找 advapi 导入
kitty_sym action=imports path=SAMPLE.exe filter=Reg
回包：只有 RegQueryValueEx 少量
判读：不像注册表主力。

往返3｜动作：改看 COM/WMI
kitty_sym action=imports path=SAMPLE.exe filter=Co
回包：CoInitializeEx + CoCreateInstance
kitty_patch action=find path=SAMPLE.exe str=WbemScripting utf16=true limit=4
回包：命中
判读：坐实 —— WMI 查询。

往返4｜动作：取查询语句
kitty_patch action=find path=SAMPLE.exe str=SELECT utf16=true limit=8
回包：WQL 语句

收敛｜末态验证
WQL 语句与目标类名命中
末态：改为 WMI 语义分析。
复盘：有 COM 初始化先想 WMI（或其他 COM 服务），不要默认注册表。"""),

("我把 find 的 from 参数当结束偏移，搜不到后半段。",
"""往返1｜动作：from 给了小值以为限制范围
kitty_patch action=find path=SAMPLE.exe str=http from=0 limit=8
回包：只命中前段
判读：第一次失败 —— from 是起点不是终点。

往返2｜动作：以为字符串在后半段被截
kitty_patch action=info path=SAMPLE.exe
回包：.text 很大
判读：范围问题。

往返3｜动作：用 to 限定终点
kitty_patch action=find path=SAMPLE.exe str=http from=0 to=<文件总长> limit=32
回包：命中变多
判读：这一步对了。

往返4｜动作：定位位置
kitty_patch action=find path=SAMPLE.exe str=http limit=32

收敛｜末态验证
每个命中偏移落在合理节内
搜不到时先确认文件本身没被判错：
```
kitty_die action=detect target=SAMPLE.exe
```
判读：能正常识别说明文件可读，问题只在范围参数。

末态：范围参数用法确认 + 文件可读性已核。
复盘：from 起点、to 终点，两个都要给才能控范围。"""),

("我按 PVOID 读结构体指针，读成了 0。",
"""往返1｜动作：在错误偏移读指针
kitty_ce op="R|0xOBJ+0x0|qword"
回包：0
判读：第一次失败。

往返2｜动作：以为指针为空
kitty_prot action=query addr=0xOBJ
回包：合法私有区
判读：对象存在，字段位置错。

往返3｜动作：dump 头部看布局
kitty_ce op="MEMDUMP_HEX|0xOBJ|64"
回包：首字段是 vtable（指向模块），不是 0
判读：坐实 —— 我把偏移算成了 0 却读的是另一块。

往返4｜动作：按 dump 修正偏移
kitty_ce op="R|0xOBJ+0x8|qword"
回包：有效指针

收敛｜末态验证
指针可过 query 且指向预期区域
末态：偏移修正。
复盘：读 0 先 dump 看真实布局，别假定字段顺序。"""),

("我以为要改 .text，其实判据在服务端返回里。",
"""往返1｜动作：找校验分支
kitty_patch action=find path=APP.exe pattern="74 ?? 85 C0" limit=8
回包：命中 3 处
判读：方向可能错了。

往返2｜动作：逐处分析
kitty_ghidra action=analyze target=APP.exe
kitty_ghidra action=decompile out=logs\\ghidra-<n>-<ts> name=<候选>
回包：都是本地参数校验
判读：不是授权判据。

往返3｜动作：改看网络返回
kitty_net action=capture port=8080
kitty_net action=decode out=<pcap> filter="http" limit=20
回包：响应 JSON 里有 status 字段
判读：坐实 —— 判据在服务端。

往返4｜动作：改响应字段验证
kitty_ce op="S_NEW|bytes:8|<status 值>|0xSTART|0xSTOP" wait=true top=5
kitty_ce op="W|0xCAND|bytes:8|<新值>" confirm=true

收敛｜末态验证
行为切换 + 回读一致
末态：判据位置确认。
复盘：本地找不到判据时，先考虑服务端下发。"""),

("我在 dump 上做 patch，忘了 patch 后校验和要重算。",
"""往返1｜动作：直接改字节
kitty_patch action=patch path=logs\\d.bin at=0x1000 expect="74 05" bytes="EB 05" confirm=true
回包：成功
判读：—

往返2｜动作：加载验证
kitty_prot action=query addr=0xADDR
回包：镜像加载失败
判读：第一次失败。

往返3｜动作：查校验和
kitty_patch action=info path=logs\\d.bin
回包：Checksum 非 0 且与内容不符
判读：坐实 —— 校验和不匹配。

往返4｜动作：重算
kitty_patch action=patch path=logs\\d.bin at=0x1000 expect="EB 05" bytes="EB 05" confirm=true
判读：fix_checksum 默认 true，会重算

收敛｜末态验证
kitty_patch action=info path=logs\\d.bin → 校验和与内容一致
末态：镜像可用。
复盘：任何 patch 后核 Checksum；kitty_patch 默认会修，但手改不会。"""),

("我用 strings 找 API 名，结果导入是按序号。",
"""往返1｜动作：strings 搜 CreateFile
回包：0 命中
判读：第一次失败。

往返2｜动作：以为名字被加密
kitty_patch action=find path=SAMPLE.exe str=kernel32 limit=4
回包：命中（DLL 名是明文）
判读：DLL 名有，函数名没有 → 序号导入。

往返3｜动作：读导入结构
kitty_sym action=imports path=SAMPLE.exe
回包：全是 Ordinal
判读：坐实。

往返4｜动作：反查序号
kitty_sym action=exports path=C:\\Windows\\System32\\KERNEL32.dll
判读：按 Base+i 定位

收敛｜末态验证
序号全部映射到名字，抽样语义自洽
末态：导入面恢复。
复盘：函数名为空但 DLL 名有 → 序号导入。"""),

("我以为样本在 hook，其实是断点被写进了内存。",
"""往返1｜动作：看到 0xCC 判 hook
kitty_ce op="R|0xADDR|bytes:16"
回包：多个 CC
判读：第一次失败 —— 0xCC 是 int3。

往返2｜动作：查谁写的
kitty_dbg action=bp_list
回包：有我自己的断点
判读：坐实 —— 是我下的断点。

往返3｜动作：清理后重读
kitty_dbg action=bp_del id=<id>
kitty_ce op="R|0xADDR|bytes:16"
回包：原始字节
判读：这一步对了。

往返4｜动作：与磁盘比对
kitty_patch action=find path=SAMPLE.exe pattern="<原始字节>" limit=2

收敛｜末态验证
内存字节与磁盘一致
末态：确认是断点残留，不是 hook。
复盘：看到 0xCC 先查自己的断点表。"""),

("我在 64 位里给 P_BACK 用了 4 字节步长假设，漏了一半候选。",
"""往返1｜动作：按 4 字节密度估窗口
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x40000"
回包：0 条
判读：第一次失败。

往返2｜动作：以为窗口错
kitty_prot action=query addr=0xTARGET
回包：容器是 0x200000
判读：窗口确实小了。

往返3｜动作：按 8 字节密度给窗
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x200000"
回包：OK|4 条
判读：这一步对了 —— 64 位指针 8 字节，命中密度是 32 位的一半。

往返4｜动作：回验
kitty_ce op="R|0xCAND|qword"

收敛｜末态验证
链成立 + P_WALK 通过
末态：窗口按容器而非密度拍脑袋。
复盘：窗口由容器决定；密度只影响分片粒度。"""),

("我把 Debug 版当 Release 分析，偏移对不上官方文档。",
"""往返1｜动作：按文档偏移读
kitty_ce op="R|0xOBJ+0x10|dword"
回包：值不符
判读：第一次失败。

往返2｜动作：以为版本不同
kitty_die action=detect target=APP.exe
kitty_patch action=find path=APP.exe str=Assertion failed limit=4
回包：命中断言串
判读：坐实 —— 这是 Debug 构建。

往返3｜动作：核对结构布局
kitty_ce op="MEMDUMP_HEX|0xOBJ|96"
回包：多出调试字段（填充更大）
判读：Debug 下结构含额外成员，偏移整体偏移。

往返4｜动作：以 dump 为准重建偏移
kitty_ce op="R|0xOBJ+0x18|dword"
回包：合理

收敛｜末态验证
字段语义自洽（计数递增、指针可解析）
末态：按实际布局而非文档偏移。
复盘：先判 Debug/Release，Debug 会插字段。"""),

("我以为要解 VM，其实只是普通混淆常量。",
"""往返1｜动作：看到大 switch 判 VM
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<n>-<ts> filter=sub_
回包：有大 switch
判读：疑似 VM，继续确认。

往返2｜动作：找字节码存储区
kitty_patch action=find path=SAMPLE.exe pattern="<跳转表特征>" limit=4
回包：无独立字节码区
判读：第一次失败 —— 不是 VM。

往返3｜动作：看 switch 分支在干什么
kitty_ghidra action=decompile out=logs\\ghidra-<n>-<ts> name=<switch 函数>
回包：每个 case 是普通运算
判读：坐实 —— 编译期 switch 展开，不是 VM。

往返4｜动作：按普通逻辑读
kitty_ghidra action=decompile out=logs\\ghidra-<n>-<ts> name=<业务函数>

收敛｜末态验证
能解出业务语义（字符串比较、数值运算）
末态：VM 假设推翻。
复盘：VM 的标志是「独立字节码 + 解释器循环」，不是 switch 大小。"""),

("我用错误的方式算 RVA，把文件偏移当 RVA。",
"""往返1｜动作：按文件偏移当 RVA
kitty_ce op="R|0xBASE+0x1200|dword"
回包：值不符
判读：第一次失败。

往返2｜动作：以为节表错
kitty_patch action=info path=SAMPLE.exe
回包：节表正常
判读：方向错。

往返3｜动作：正确换算
kitty_patch action=info path=SAMPLE.exe
判读：RVA = 文件偏移 - PointerToRawData + VirtualAddress
回包：换算成功

往返4｜动作：验证
kitty_ce op="R|0xBASE+0x<正确RVA>|dword"
回包：符合预期

收敛｜末态验证
kitty_patch action=find 的偏移 → 换算 → 内存读取，三点一致
末态：换算链路确定。
复盘：文件偏移与 RVA 是两套坐标，必须先换算。"""),

("我以为要提权才能读，其实是我的窗口越界了。",
"""往返1｜动作：读高端地址
kitty_ce op="R|0x7FFFFFFF0000|dword"
回包：失败
判读：第一次失败。

往返2｜动作：以为需要管理员
kitty_status probe=true
回包：已是管理员
判读：不是权限。

往返3｜动作：查映射
kitty_prot action=query addr=0x7FFFFFFF0000
回包：INVALID_ADDRESS
判读：坐实 —— 该地址未映射。

往返4｜动作：按模块窗口重读
kitty_ce op=MODENUM
kitty_ce op="R|0xBASE+0x1000|dword"
回包：正常

收敛｜末态验证
地址在模块窗口内且可读
末态：确认是地址问题。
复盘：读失败先 query，再谈权限。"""),

("我把 dump 的 addr 当 VA 传，转储了错的内存。",
"""往返1｜动作：addr 传文件偏移
kitty_dump addr=0x1200 size=0x1000 path=logs\\blk.bin
回包：落盘成功但内容不对
判读：第一次失败。

往返2｜动作：以为 dump 有问题
kitty_ce op="MEMDUMP_HEX|0xBASE+0x1200|32"
回包：与 blk.bin 不同
判读：坐实 —— addr 需要 VA。

往返3｜动作：按 VA 转储
kitty_dump addr=0xBASE+0x1200 size=0x1000 path=logs\\blk2.bin
回包：内容一致

收敛｜末态验证
blk2.bin 首 32 字节 == MEMDUMP_HEX 输出
末态：转储口径修正。
复盘：dump 的 addr 是 VA；模块级转储用 module= 更稳。"""),

("我以为 S_FREE 会清掉扫描结果，其实它是清状态。",
"""往返1｜动作：想清理内存占用却调用 S_FREE
kitty_ce op=S_FREE
回包：OK
判读：—

往返2｜动作：继续 S_CHANGED
kitty_ce op=S_CHANGED
回包：无基线错误
判读：第一次失败 —— 状态被清了。

往返3｜动作：重建基线
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
kitty_ce op=S_CHANGED
回包：正常
判读：这一步对了。

往返4｜动作：明确语义
判读：S_FREE = 释放扫描状态（不是释放内存）
回包：—

收敛｜末态验证
链路 SNAP → CHANGED 恢复可用；SYNC_STAT 四项 0
末态：语义确认。
复盘：S_FREE 清状态；ALLOC 的内存用 FREE 释放。"""),

("我在 32 位环境用 qword 写，写坏了两个字段。",
"""往返1｜动作：qword 写
kitty_ce op="W|0xADDR|qword|100" confirm=true
回包：成功
判读：—

往返2｜动作：查相邻字段
kitty_ce op="R|0xADDR+4|dword"
回包：被改成 0
判读：第一次失败 —— 32 位下相邻字段被覆盖。

往返3｜动作：回滚
kitty_ce op="W|0xADDR+4|dword|<原值>" confirm=true
回包：恢复
判读：—

往返4｜动作：改按 dword 写
kitty_ce op="W|0xADDR|dword|100" confirm=true
kitty_ce op="R|0xADDR+4|dword"
回包：相邻字段未变

收敛｜末态验证
目标字段正确 + 相邻未变
跨视图确认：
```
kitty_km action=read addr=0xADDR vt=dword
```
判读：内核视图的 dword 应等于写入值；若内核视图显示高位被写，说明 qword 写生效了 —— 正是要避免的。

末态：宽度匹配 + 双视图确认未越界。
复盘：写前核位数与字段宽度；写后必查相邻。"""),

("我以为样本依赖 .NET 运行时，其实自带运行时。",
"""往返1｜动作：dnSpy 打不开
kitty_dnspy action=decompile target=APP.exe out=logs\\dnspy
回包：无法加载
判读：第一次失败。

往返2｜动作：查 CLR 目录
kitty_patch action=info path=APP.exe
回包：CLR 目录非零
判读：看似托管。

往返3｜动作：查是否自带运行时
kitty_patch action=find path=APP.exe str=coreclr limit=4
kitty_patch action=find path=APP.exe str=hostfxr limit=4
回包：命中
判读：坐实 —— 自包含部署（single-file + 自带 runtime）。

往返4｜动作：改查内嵌程序集
kitty_patch action=find path=APP.exe str=BSJB limit=8
回包：命中

收敛｜末态验证
抽出内嵌 dll 后 dnSpy 可打开
末态：改走「解包 + 反编译」。
复盘：自包含部署要先取内嵌程序集。"""),

("我用 kitty_patch find 搜 Unicode 串忘了 utf16，白找两轮。",
"""往返1｜动作：ASCII 搜
kitty_patch action=find path=SAMPLE.exe str=SOFTWARE limit=8
回包：0 命中
判读：第一次失败。

往返2｜动作：换大小写重搜
kitty_patch action=find path=SAMPLE.exe str=Software limit=8
回包：仍 0
判读：第二次失败。

往返3｜动作：加 utf16
kitty_patch action=find path=SAMPLE.exe str=SOFTWARE utf16=true limit=8
回包：命中
判读：这一步对了。

往返4｜动作：核对位置
kitty_patch action=info path=SAMPLE.exe
判读：偏移落在 .rdata

收敛｜末态验证
kitty_ce op="MEMDUMP_HEX|0xBASE+0xRVA|32" → 隔字节 00，确认 UTF-16LE
末态：明文串拿到。
复盘：Windows 程序大量用宽字符，搜不到先加 utf16。"""),

("我改了 IAT 想重定向，结果目标程序崩溃。",
"""往返1｜动作：改 IAT 指向自建函数
kitty_ce op="W|0xIAT_SLOT|qword|<自建地址>" confirm=true
回包：崩溃
判读：第一次失败。调用约定不匹配。

往返2｜动作：以为地址错
kitty_ce op="R|0xIAT_SLOT|qword"
回包：值是我写的
判读：写入正确。

往返3｜动作：查调用约定
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<n>-<ts> name=<调用点>
回包：stdcall/fastcall 与我的桩不符
判读：坐实。

往返4｜动作：按原约定重写桩
kitty_asm action=assemble code="<保存寄存器>\\n<逻辑>\\n<恢复并 ret N>" base=0xNEW_VA
kitty_ce op="W|0xNEW_VA|bytes:<N>" confirm=true

收敛｜末态验证
功能正常 + IAT 回读正确
末态：重定向可用。
复盘：IAT 重定向必须匹配调用约定与栈清理方。"""),

("我以为要找的是堆指针，其实是句柄表索引。",
"""往返1｜动作：按指针反查
kitty_ce op="P_BACK|0xTARGET|0xALLOC_BASE|0xALLOC_BASE+0x200000"
回包：0 条
判读：第一次失败。

往返2｜动作：扩窗重试
kitty_ce op="P_BACK|0xTARGET|0xBASE|0xBASE+SIZE"
回包：仍 0
判读：第二次失败。

往返3｜动作：核值的形态
kitty_ce op="R|0xADDR|dword"
回包：小整数（如 0x1C4）
判读：坐实 —— 这是句柄/索引，不是指针。

往返4｜动作：按整数扫
kitty_ce op="S_NEW|dword|0x1C4|0xSTART|0xSTOP" wait=true top=10

收敛｜末态验证
命中项中有一条跟随句柄变化
末态：确认是索引字段。
复盘：反查 0 命中的第一步是核值形态（是否像指针）。"""),

("我把重定位表当函数表用，白读了一遍。",
"""往返1｜动作：按 RUNTIME_FUNCTION 解析 .reloc
kitty_patch action=info path=SAMPLE.exe
回包：解析出乱值
判读：第一次失败 —— 用错结构。

往返2｜动作：以为表被加密
kitty_die action=detect target=SAMPLE.exe
回包：无壳
判读：方向错。

往返3｜动作：核结构定义
判读：.reloc 是 IMAGE_BASE_RELOCATION（PageRVA + BlockSize + 2 字节条目）
      .pdata 才是 RUNTIME_FUNCTION（12 字节）
回包：—

往返4｜动作：按正确结构读
kitty_ce op="R|0xBASE+0xRELOC_RVA|dword"
kitty_ce op="R|0xBASE+0xPDATA_RVA|dword"

收敛｜末态验证
两个结构各自解析出合理值（PageRVA 页对齐、Begin 落在 .text）
末态：结构对应关系确认。
复盘：先核结构大小再解析；12 字节是 .pdata，8 字节头是 .reloc。"""),

("我以为样本在联网，其实是在读本地缓存文件。",
"""往返1｜动作：看流量为零，怀疑隐蔽通道
kitty_net action=capture port=8080
回包：无流量
判读：—

往返2｜动作：查 socket 导入
kitty_sym action=imports path=SAMPLE.exe filter=socket
回包：0
判读：坐实 —— 没有网络能力。

往返3｜动作：查文件读取
kitty_patch action=find path=SAMPLE.exe str=.dat limit=8
kitty_sym action=imports path=SAMPLE.exe filter=CreateFile
回包：CreateFileW + .dat 路径

往返4｜动作：观测文件访问
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
判读：缓冲区里出现文件内容

收敛｜末态验证
缓存文件内容出现在内存缓冲区
末态：确认本地读，非联网。
复盘：无流量不等于无数据源。"""),

("我用 P_BACK 找静态区，忘了静态区在模块里而目标在堆里。",
"""往返1｜动作：在模块窗口反查
kitty_ce op="P_BACK|0xTARGET|0xBASE|0xBASE+SIZE"
回包：0 条
判读：第一次失败。

往返2｜动作：以为目标不在模块引用
kitty_prot action=query addr=0xTARGET
回包：堆区
判读：方向修正 —— 目标在堆里，但「持有它的指针」可能在模块里。

往返3｜动作：核参数方向
kitty_ops filter=P_BACK
判读：P_BACK 第二三参数是「搜索窗口」，不是「目标所在区」
回包：—

往返4｜动作：在模块窗口搜「谁指向堆目标」
kitty_ce op="P_BACK|0xTARGET|0xBASE|0xBASE+SIZE"
回包：仍 0 → 说明模块里没有直接引用，改用 pchain
kitty_pchain target=0xTARGET depth=3 mod=TARGET.exe

收敛｜末态验证
pchain 给出多级链 + 静态基址
末态：确认模块直接引用不存在。
复盘：搜窗口是「谁可能存这个值」，与目标所在区无关。"""),

("我把 S_NEW 的 vt 写成 float，被拒。",
"""往返1｜动作：直接传 float
kitty_ce op="S_NEW|float|1500.0|0xSTART|0xSTOP"
回包：ERR| 类型不支持
判读：第一次失败。

往返2｜动作：以为要写 1500 就行
kitty_ce op="S_NEW|dword|1500|0xSTART|0xSTOP"
回包：命中整数 1500，但不是 float 字段
判读：第二次失败（语义错）。

往返3｜动作：查类型表
kitty_ops filter=S_NEW
回包：支持 byte/word/dword/qword/bytes:N
判读：坐实 —— 没有 float 类型，必须用位模式。

往返4｜动作：按位模式扫
kitty_ce op="S_NEW|dword|0x44BB8000|0xSTART|0xSTOP" wait=true top=20

收敛｜末态验证
kitty_ce op="R|0xCAND|dword" 解回 1500.0
末态：float 用 dword 位模式扫。
复盘：OP 只认整数与字节；浮点用位模式。"""),

("我在错误模块里找导出，因为同名 DLL 有多个。",
"""往返1｜动作：按名字解析
kitty_sym source=mem module=<同名> action=exports
回包：解析到意外的导出集
判读：第一次失败。

往返2｜动作：核模块表
kitty_ce op=MODENUM
回包：同名三行，base 不同
判读：坐实 —— 解析到了另一份。

往返3｜动作：按 base 定向读
kitty_ce op="R|0xBASE_OF_CORRECT+0xEXPORT_RVA|dword"
回包：正确地址

往返4｜动作：交叉验证
kitty_sym source=file path=<对应磁盘文件> action=exports
回包：与内存一致

收敛｜末态验证
导出面与磁盘文件一致，base 归属明确
末态：同名困扰解除。
复盘：同名模块必须按 base 或路径区分。"""),

("我以为 S_UNCHANGED 会缩小范围，结果它扩大了。",
"""往返1｜动作：SNAP 后直接 UNCHANGED
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
kitty_ce op=S_UNCHANGED
回包：n 很大
判读：第一次失败 —— 未变集本来就大。

往返2｜动作：以为要改值
判读：UNCHANGED 是「筛掉变了的」，不是「收窄」
回包：—

往返3｜动作：先 CHANGED 再 UNCHANGED 交替
kitty_ce op=S_CHANGED
kitty_ce op=S_UNCHANGED
kitty_ce op=S_CHANGED
回包：n 递减

往返4｜动作：取样
kitty_ce op="S_GET|0|8"

收敛｜末态验证
候选 ≤10 且改值跟随
末态：交替法生效。
复盘：CHANGED 优先，UNCHANGED 用来剔噪，顺序反了就白做。"""),

("我把 dwMachine 判断反了，一直在 32 位工具里折腾。",
"""往返1｜动作：凭印象判 32 位
kitty_patch action=info path=SAMPLE.exe
回包：Machine=0x8664
判读：我看成了 0x14C。

往返2｜动作：用 32 位调试器
kitty_variants action=switch variant=ws-dbg-dbg32
kitty_x64dbg action=run target=SAMPLE.exe
回包：附加失败
判读：第一次失败。

往返3｜动作：核 MODENUM
kitty_ce op=OPEN|<pid>
kitty_ce op=MODENUM
回包：is64=1
判读：坐实 —— 64 位。

往返4｜动作：换 64 位
kitty_variants action=switch variant=ws-dbg-dbg64
kitty_x64dbg action=selftest
kitty_x64dbg action=run target=SAMPLE.exe
回包：成功

收敛｜末态验证
附加成功 + 入口字节一致
末态：64 位链路。
复盘：Machine 值要查表（0x14C/0x8664），别凭印象。"""),

("我用 hook 抓参数，抓到的是寄存器快照不是实参。",
"""往返1｜动作：入口处读寄存器
kitty_x64dbg action=seed addr=<函数VA> seedCmd=log
kitty_ce op="R|0xRCX|dword"
回包：值不合理
判读：第一次失败 —— 入口还没初始化参数。

往返2｜动作：往后跳几条再读
kitty_x64dbg action=seed addr=<函数VA+0x20> seedCmd=log
kitty_ce op="R|0xRCX|dword"
回包：合理
判读：这一步对了，但依赖指令偏移，脆弱。

往返3｜动作：改用返回处读
判读：x64 返回值在 RAX，入参已被消费
回包：—

往返4｜动作：用保存现场的栈位置
kitty_ce op="R|0xRSP+8|qword"
回包：第 5 参数

收敛｜末态验证
参数值与功能输入一致（两次调用值不同且可解释）
末态：参数获取点确定。
复盘：入口寄存器快照不一定有实参；按调用约定与指令位置判断。"""),

("我以为样本在检测虚拟机，其实是检测屏幕分辨率。",
"""往返1｜动作：查虚拟机指纹
kitty_patch action=find path=SAMPLE.exe str=VMware limit=4
kitty_patch action=find path=SAMPLE.exe str=VBox limit=4
回包：0 命中
判读：第一次失败。

往返2｜动作：查 cpuid
kitty_patch action=find path=SAMPLE.exe pattern="0F A2" limit=8
回包：命中（CRT 也用）
判读：证据不足。

往返3｜动作：查显示相关
kitty_sym action=imports path=SAMPLE.exe filter=GetSystemMetrics
kitty_patch action=find path=SAMPLE.exe str=1024 limit=4
回包：GetSystemMetrics + 分辨率常量
判读：坐实 —— 屏幕检测。

往返4｜动作：确认分支
kitty_ghidra action=search out=logs\\ghidra-<n>-<ts> filter=GetSystemMetrics

收敛｜末态验证
分支里的分辨率比较与失败行为明确
末态：判据改为「环境指纹」而非「虚拟机」。
复盘：环境检测面很宽，别只盯虚拟化指令。"""),

("我在 4KB 页边界读跨页数据，读到一半失败。",
"""往返1｜动作：一次读 8 字节跨页
kitty_ce op="R|0xADDR+0xFFC|qword"
回包：失败或截断
判读：第一次失败。

往返2｜动作：以为地址错
kitty_prot action=query addr=0xADDR+0xFFC
回包：本页可读
判读：地址没错。

往返3｜动作：分段读
kitty_ce op="R|0xADDR+0xFFC|bytes:4"
kitty_ce op="R|0xADDR+0x1000|bytes:4"
回包：两段拼成 8 字节
判读：这一步对了。

往返4｜动作：核下一段可读性
kitty_prot action=query addr=0xADDR+0x1000

收敛｜末态验证
拼接后 8 字节与语义自洽
末态：跨页读改用分段。
复盘：跨页读必须分段；页边界处的失败不是权限问题。"""),

("我以为要逆协议，其实 protoc 就能解。",
"""往返1｜动作：手工解析字节
kitty_net action=decode out=<pcap> filter="tcp" limit=20
回包：载荷看似无结构
判读：第一次失败。

往返2｜动作：找长度前缀
判读：首字节 0x0A 0x08 之类像是字段标签
回包：—

往返3｜动作：试 protobuf
kitty_proto action=status
kitty_proto action=decode target=<首帧 hex>
回包：解析出字段名与值
判读：坐实 —— protobuf。

往返4｜动作：全量解
kitty_proto action=decode target=<多帧>

收敛｜末态验证
解出的字段与界面元素一一对应
末态：协议确认。
复盘：先试标准序列化再手工逆。"""),

("我把「没有断点命中」当成「函数没被调用」。",
"""往返1｜动作：下断点后无命中
kitty_dbg action=bp addr=<函数VA> access=execute
回包：无命中
判读：—

往返2｜动作：直接下结论
判读：错误 —— 可能是地址错或路径未触发。

往返3｜动作：先验证地址
kitty_ce op="R|<函数VA>|bytes:8"
回包：合法序言
判读：地址对。

往返4｜动作：改用副作用确认
kitty_ce op="S_SNAP|bytes:16|0x数据区|0x数据区+0x1000"
kitty_ce op=S_CHANGED
回包：有变化
判读：坐实 —— 函数执行了，是我的断点没生效（如页被改）。

收敛｜末态验证
副作用出现 + 断点方式改为硬件/软件对比
末态：纠正结论。
复盘：无命中要三查 —— 地址、路径、断点实现。"""),

("我用错了 kitty_dump 的参数，转储了整个进程。",
"""往返1｜动作：只给 size 不给 module
kitty_dump addr=0x0 size=0x7FFFFFFF path=logs\\all.bin
回包：超时 / 空间不足
判读：第一次失败。

往返2｜动作：以为磁盘满了
判读：不是空间问题，是范围问题
回包：—

往返3｜动作：按模块转储
kitty_dump module=TARGET.exe unmap=true path=logs\\mod.bin
回包：成功
判读：这一步对了。

往返4｜动作：核大小
kitty_ce op=MODENUM
判读：落盘大小应与模块 size 量级一致

收敛｜末态验证
文件大小合理 + kitty_die 能解析
末态：转储口径正确。
复盘：转储用 module=；addr+size 只用于小块。"""),

("我把内存里的函数指针当数据，读了一堆无效值。",
"""往返1｜动作：按数据读
kitty_ce op="R|0xTBL+0x10|dword"
回包：无效值
判读：第一次失败 —— 该表是 8 字节指针数组。

往返2｜动作：以为表被加密
kitty_ce op="MEMDUMP_HEX|0xTBL|32"
回包：能看到 0x7FF6 前缀
判读：坐实 —— 是 64 位指针。

往返3｜动作：按 qword 读并验证
kitty_ce op="R|0xTBL+0x10|qword"
kitty_prot action=query addr=<读出的值>
回包：落在 .text

往返4｜动作：读出整表
kitty_ce op="MEMDUMP_HEX|0xTBL|128"

收敛｜末态验证
每个指针都落在 .text 且序言合法
末态：确认函数指针表。
复盘：先 dump 看前缀再定宽度。"""),
]

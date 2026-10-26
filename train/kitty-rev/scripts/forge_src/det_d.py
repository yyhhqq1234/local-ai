# -*- coding: utf-8 -*-
"""re-detour-trajectory 扩量 D（61-90）"""

DET_D = [
("我把「模块大小」当「扫描结束地址」，扫到了隔壁模块。",
"""往返1｜动作：用 SizeOfImage 当结束地址
kitty_ce op=MODENUM
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1C00000"
回包：命中里有别的模块的地址
判读：第一次失败。MODENUM 的 size 字段是 0（读不到长度），我把猜测值用上了。

往返2｜动作：以为命中了跨进程结果
kitty_ce op=CUR
回包：pid 正确
判读：不是跨进程，是我的窗口越界。

往返3｜动作：取真实长度
kitty_prot action=query addr=0xBASE
回包：RegionSize=0x1C00000
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1C00000" wait=true top=20
判读：RegionSize 与 SizeOfImage 一致，窗口本身没错。

往返4｜动作：改用「命中地址归属过滤」
kitty_prot action=query addr=0xCAND
回包：AllocationBase 与模块 base 不同
判读：坐实 —— 命中落在相邻分配区，不是本模块。

收敛｜末态验证
候选全部经 query 归属确认在本模块内，剩 3 条且改值跟随
末态：窗口边界与归属双重确认。
复盘：扫完必须做归属过滤，窗口正确不等于结果正确。"""),

("我读到的值是 1500，但界面是 1500.5，我以为是四舍五入。",
"""往返1｜动作：按 dword 扫 1500
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x1000000" wait=true top=20
回包：n=31
判读：能扫到，但界面是小数，说明字段另有表示。

往返2｜动作：修改一个候选看界面
kitty_ce op="W|0xCAND|dword|1200" confirm=true
回包：界面变成 1200.0（不是 1200.5）
判读：这个候选是整数显示缓存。

往返3｜动作：改按 float 位模式扫
kitty_ce op="S_NEW|dword|0x44BB8000|0xBASE|0xBASE+0x1000000" wait=true top=20
回包：n=2
判读：这一步对了 —— 1500.5f 的位模式是 0x44BB8000 的邻近值，需按实际值算。

往返4｜动作：按实际位模式复核
kitty_ce op="R|0xCAND|dword"
回包：解回 1500.5
判读：坐实。

收敛｜末态验证
改用 float 候选写入 0x44BB0000（1496.0），界面跟随
末态：float 字段确认，整数缓存排除。
复盘：界面有小数就必须按 IEEE754 扫，别在整数里找。"""),

("我想确认一个函数被调用，但下断点后程序直接退出。",
"""往返1｜动作：下执行断点
kitty_dbg action=bp addr=<函数VA> access=execute
回包：程序在命中前退出
判读：第一次失败。该函数有反调试前置。

往返2｜动作：以为地址错
kitty_ce op="R|<函数VA>|bytes:8"
回包：字节是合法序言
判读：地址没错。

往返3｜动作：改用只读观测
kitty_ce op="S_SNAP|bytes:16|0x函数数据区|0x函数数据区+0x1000"
kitty_ce op=S_CHANGED
回包：有变化
判读：这一步对了 —— 不碰调试接口也能确认执行。

往返4｜动作：用副作用交叉
kitty_sym action=imports path=SAMPLE.exe filter=Write
判据：该函数是否写文件/日志
回包：写日志
判读：日志落地即证据。

收敛｜末态验证
日志文件新增条目 + 时间戳落在本次运行窗口
末态：确认被调用，全程未 attach。
复盘：反调试目标优先用快照差分与副作用，不下断点。"""),

("我把 64 位 DLL 喂给 32 位工具，报「不是有效的 PE」。",
"""往返1｜动作：kitty_ida action=analyze target=MOD64.dll
回包：解析失败
判读：第一次失败。

往返2｜动作：以为文件损坏
kitty_patch action=info path=MOD64.dll
回包：节表正常，Machine=0x8664
判读：文件没问题，是工具位数不匹配。

往返3｜动作：核工具档位
kitty_ida action=status
回包：当前是 32 位分析器
判读：坐实。

往返4｜动作：换 64 位
kitty_ida action=analyze target=MOD64.dll
kitty_ida action=functions out=logs\\ida-64-<ts> limit=60
回包：正常

收敛｜末态验证
kitty_sym action=exports path=MOD64.dll → 与 IDA 视图一致
末态：64 位链路可用。
复盘：分析前先核 Machine 与工具位数。"""),

("我以为目标用了加密通信，其实只是 gzip。",
"""往返1｜动作：看到流量高熵，判加密
kitty_net action=decode out=<pcap> filter="tcp" limit=20
回包：载荷不可读
判读：第一次失败 —— 高熵不等于加密。

往返2｜动作：找 TLS 握手
判据：有无 16 03 01/02 记录头
回包：无
判读：不是 TLS。

往返3｜动作：查压缩魔数
kitty_proto action=decode target=<首帧 hex>
回包：首字节 1F 8B
判读：坐实 —— gzip。

往返4｜动作：解压
判据：解压后是 JSON
回包：明文

收敛｜末态验证
解压后的 JSON 字段与界面元素对应
末态：确认压缩而非加密。
复盘：先看魔数再判加密。"""),

("我改页属性失败，以为是权限不够，其实是地址没对齐。",
"""往返1｜动作：改保护
kitty_prot action=protect addr=0xADDR size=0x1000 protect=rw confirm=true
回包：ERR|PROTECT_FAIL
判读：第一次失败。

往返2｜动作：以为要管理员
kitty_status probe=true
回包：宿主已是管理员
判读：不是权限问题。

往返3｜动作：核地址对齐
kitty_prot action=query addr=0xADDR
回包：AllocationBase 与 0xADDR 不同页对齐
判读：坐实 —— 页保护按页粒度。

往返4｜动作：按页对齐改
kitty_prot action=protect addr=0xALLOC_BASE size=0x1000 protect=rw confirm=true
回包：成功

收敛｜末态验证
kitty_prot action=query addr=0xALLOC_BASE → Protect=RW
末态：改保护成功。
复盘：页操作先对齐到 AllocationBase。"""),

("我用 P_WALK 验证链，参数顺序写反了。",
"""往返1｜动作：按「偏移在前基址在后」传参
kitty_ce op="P_WALK|0xOFF|0xBASE"
回包：读到垃圾
判读：第一次失败。

往返2｜动作：以为链错了
kitty_ce op="R|0xBASE|qword"
回包：指向有效地址
判读：链本身没问题。

往返3｜动作：核签名
kitty_ops filter=P_WALK
回包：第一参数是基址，第二是偏移
判读：坐实 —— 我传反了。

往返4｜动作：按正确顺序
kitty_ce op="P_WALK|0xBASE|0xOFF"
回包：等于目标

收敛｜末态验证
两级链各回验一次
末态：链成立。
复盘：参数顺序按 kitty_ops，别靠记忆。"""),

("我在 dump 里找不到字符串，因为在内存里是解密的。",
"""往返1｜动作：在镜像文件里搜
kitty_patch action=find path=logs\\mem.bin str=http limit=8
回包：0 命中
判读：第一次失败。

往返2｜动作：以为 dump 不完整
kitty_die action=detect target=logs\\mem.bin
回包：节表完整
判读：dump 没问题。

往返3｜动作：在运行期搜
kitty_ce op="S_NEW|bytes:4|68747470|0xBASE|0xBASE+0x1000000" wait=true top=5
回包：命中 2 处
判读：这一步对了 —— 字符串是运行期解密的。

往返4｜动作：读明文
kitty_ce op="MEMDUMP_HEX|0xCAND|128"
回包：完整 URL

收敛｜末态验证
明文 URL 与抓包目标一致
末态：确认解密时机在运行期。
复盘：dump 是某一时刻的快照，解密可能在之后。"""),

("我把 WaitForSingleObject 的超时当成了睡眠。",
"""往返1｜动作：看到长超时值，判为固定延时
kitty_ce op="R|0xADDR|dword"
回包：0x00007530（30000ms）
判读：看似 sleep 30 秒。

往返2｜动作：以为能找到固定间隔
kitty_ce op="S_NEW|dword|0x7530|0xBASE|0xBASE+0x1000000" wait=true top=10
回包：多处命中
判读：第二次失败。多个等待点共用同一超时值。

往返3｜动作：看它等的是哪个句柄
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<n>-<ts> filter=WaitForSingleObject
回包：等的是事件/互斥体
判读：坐实 —— 是等待事件，不是 sleep。

往返4｜动作：按等待对象定位触发点
kitty_ce op="R|0xHANDLE|dword"
回包：句柄有效

收敛｜末态验证
触发对应事件后，等待立即返回（观测到行为变化）
末态：确认等待语义。
复盘：超时值不等于延时；要看等待对象。"""),

("我用 strings 找 DLL 名，漏掉了序号导入的那些。",
"""往返1｜动作：strings 搜 .dll
回包：只拿到 3 个名字
判读：第一次失败。

往返2｜动作：以为导入被裁
kitty_sym action=imports path=SAMPLE.exe
回包：8 个 DLL，部分靠序号
判读：坐实 —— 序号导入没有名字串。

往返3｜动作：按结构读导入表
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xIDATA_RVA|160"
回包：8 条描述符
判读：这一步对了。

往返4｜动作：序号反查
kitty_sym action=exports path=<目标DLL>
判读：按 Base+i 反推函数名

收敛｜末态验证
8 个 DLL 全部有归属，序号项能映射到名字
末态：导入面完整。
复盘：strings 只能看到名字导入，序号导入必须读结构。"""),

("我改了内存里的常量，程序重算覆盖了。",
"""往返1｜动作：直接改常量
kitty_ce op="W|0xADDR|dword|99" confirm=true
kitty_ce op="R|0xADDR|dword" → 99
判读：写入成功。

往返2｜动作：一秒后复查
kitty_ce op="R|0xADDR|dword" → 原值
判读：第一次失败。被重算覆盖。

往返3｜动作：找重算源
kitty_ce op="S_NEW|dword|99|0xBASE|0xBASE+0x1000000" wait=true top=10
回包：另有地址保持 99
判读：坐实 —— 读到的是副本。

往返4｜动作：改真值
kitty_ce op="S_NEW|dword|<原值>|0xSTART|0xSTOP" wait=true top=20
判读：逐个写入 + 立刻回读 + 隔拍回读
回包：其中一个保持 99

收敛｜末态验证
两次回读都等于 99 + 界面同步
末态：真值地址确认。
复盘：写后必须隔拍复查，立刻回读会被副本骗。"""),

("我以为要打内存补丁，其实改配置就够。",
"""往返1｜动作：找校验分支准备 patch
kitty_patch action=find path=APP.exe pattern="74 ?? 48 8B" limit=8
回包：命中 5 处
判读：方向偏了。

往返2｜动作：试图确认哪个分支是校验
kitty_ghidra action=analyze target=APP.exe
kitty_ghidra action=search out=logs\\ghidra-<n>-<ts> filter=<串>
回包：xref 指向配置读取后
判读：线索变了 —— 判据来自配置文件。

往返3｜动作：改看配置
kitty_patch action=find path=APP.exe str=config limit=8
回包：config.ini 路径
判读：这一步对了。

往返4｜动作：改配置并验证
判读：改 ini 后行为切换，无需 patch

收敛｜末态验证
行为切换 + 哈希未变（APP.exe 未改）
末态：确认走配置路径。
复盘：先确认判据来自哪里（代码/配置/服务端），再决定改哪里。"""),

("我把 readBytes 返回的长度当字节数，LUA 脚本报错。",
"""往返1｜动作：LUA 里按长度循环
kitty_ce op="LUA|local n=readBytes(0xADDR,16) return n"
回包：返回的是 table 不是数字
判读：第一次失败。

往返2｜动作：以为 API 名错
kitty_ops filter=LUA
回包：LUA 透传 CE API
判读：名字没错。

往返3｜动作：用 #n 取长度
kitty_ce op="LUA|local d=readBytes(0xADDR,16) return #d"
回包：16
判读：这一步对了。

往返4｜动作：拼十六进制
kitty_ce op="LUA|local d=readBytes(0xADDR,16) local t={} for i=1,#d do t[#t+1]=string.format('%02X',d[i]) end return table.concat(t,' ')"

收敛｜末态验证
输出与 kitty_ce op="R|0xADDR|bytes:16" 逐字节一致
末态：LUA 取字节路径可用。
复盘：readBytes 返回数组，长度用 #；与 R 的 bytes 输出交叉核对。"""),

("我用进程名 OPEN，结果桥连到了调试器进程。",
"""往返1｜动作：OPEN 同名
kitty_ce op=OPEN|TARGET.exe
回包：成功
判读：看着正常。

往返2｜动作：读特征地址
kitty_ce op="R|0xBASE+0x1000|dword"
回包：值不符预期
判读：第一次失败。

往返3｜动作：查锚点
kitty_ce op=CUR
回包：pid 属于调试器子进程
判读：坐实 —— 进程名匹配到了错误实例。

往返4｜动作：按 pid 钉死
kitty_ce op=LP
kitty_ce op=OPEN|<正确pid>

收敛｜末态验证
kitty_ce op=CUR 的 pid 与预期一致 + 特征地址值正确
末态：目标锁定。
复盘：同名/多实例场景一律按 pid。"""),

("我以为 APK 是纯 Java，其实逻辑在 so 里。",
"""往返1｜动作：jadx 全量反编译
kitty_jadx action=decompile target=app.apk out=logs\\jadx
回包：Java 侧只有调用桩
判读：第一次失败。

往返2｜动作：以为加固
kitty_apkscan action=scan target=app.apk
回包：无加固指纹
判读：方向错了。

往返3｜动作：查 native 库
kitty_apktool action=decode target=app.apk out=logs\\apk
判读：lib/arm64-v8a/ 下有多个 .so
回包：确认

往返4｜动作：转 so 分析
kitty_rea_binary path=logs\\apk\\lib\\arm64-v8a\\libnative.so
kitty_ghidra action=analyze target=logs\\apk\\lib\\arm64-v8a\\libnative.so

收敛｜末态验证
JNI 导出（Java_*）存在，能定位到 Java 调用点
末态：主战场转到 so。
复盘：先看 lib/ 目录再决定分析层面。"""),

("我把负偏移写成正偏移，读到的字段差一位。",
"""往返1｜动作：按 +0x10 读
kitty_ce op="R|0xOBJ+0x10|dword"
回包：值不合理
判读：第一次失败。

往返2｜动作：以为结构对齐错
kitty_ce op="MEMDUMP_HEX|0xOBJ|64"
回包：字段边界在 +0x0C 处
判读：坐实 —— 我多算了 4 字节。

往返3｜动作：按实际边界读
kitty_ce op="R|0xOBJ+0x0C|dword"
回包：合理值
判读：这一步对了。

往返4｜动作：确认字段宽度
kitty_ce op="R|0xOBJ+0x10|dword"
回包：下一个字段

收敛｜末态验证
相邻字段语义自洽（计数递增、指针可解析）
末态：偏移表修正。
复盘：偏移以 dump 的实际边界为准，不靠推算。"""),

("我调了 KM_W 写值，回 OK 但值没变。",
"""往返1｜动作：内核写
kitty_km action=write addr=0xADDR val=99 vt=dword confirm=true
回包：OK
判读：受理不等于生效。

往返2｜动作：立刻读
kitty_km action=read addr=0xADDR vt=dword → 原值
判读：第一次失败。

往返3｜动作：查是否 attach 对
kitty_km action=info
回包：pid 正确
kitty_dualview addr=0xADDR vt=dword samples=2
回包：三视图一致（都是原值）
判读：坐实 —— 写入被吞，且不是视图分叉。

往返4｜动作：改走 PTE 直写
kitty_wpb addr=0xADDR val=99 vt=dword restore=true accept_protection_bypass=true
kitty_km action=read addr=0xADDR vt=dword → 99

收敛｜末态验证
R 与 KM_R 都读到 99，3 秒后仍 99
末态：写入真实生效。
复盘：KM_W 回 OK 必须回读；被吞时改走 PTE。"""),

("我在错误的节里找代码，因为节名被改了。",
"""往返1｜动作：只看 .text
kitty_dump module=TARGET.exe unmap=true path=logs\\m.bin
判读：求 .text 里找入口
回包：反汇编全是数据

往返2｜动作：以为入口被壳改了
kitty_patch action=info path=TARGET.exe
回包：入口 RVA 落在 .rsrc 区间
判读：坐实 —— 节名与内容不符。

往返3｜动作：按内容而非节名判
kitty_prot action=query addr=0xBASE+0xEP
回包：Protect 含 EXECUTE
判读：这一步对了。

往返4｜动作：从该地址起反汇编
kitty_ghidra action=analyze target=TARGET.exe
kitty_ghidra action=functions out=logs\\ghidra-<n>-<ts> filter=entry

收敛｜末态验证
入口处解出合法序言与 CRT 调用
末态：按内容定位代码，节名作废。
复盘：节名只是字符串；权限与内容才是判据。"""),

("我把 S_NEW 的结果直接当「全部候选」，漏了后面的页。",
"""往返1｜动作：单块扫描后取样
kitty_ce op="S_NEW|dword|1500|0xBASE|0xBASE+0x400000" wait=true top=20
回包：n=5
判读：看着完成了。

往返2｜动作：只处理这 5 条
判读：改值后界面没变
回包：—
判读：第一次失败。

往返3｜动作：怀疑漏扫
kitty_ce op="S_NEW|dword|1500|0xBASE+0x400000|0xBASE+0x800000" wait=true top=20
回包：n=26
判读：坐实 —— 目标在后半段。

往返4｜动作：分块扫全
判读：逐块推进直到 SizeOfImage

收敛｜末态验证
全区间候选合并后逐条回验，找到跟随项
末态：候选完整。
复盘：单块结果不是全集；按 query 的 RegionSize 覆盖全程。"""),

("我把 hook 写进了系统 DLL，触发了完整性校验。",
"""往返1｜动作：在 kernel32 上下断点式 hook
kitty_ce op="W|0xK32_ADDR|bytes:5|<jmp>" confirm=true
回包：写入成功，程序随即崩溃
判读：第一次失败。系统页有校验。

往返2｜动作：以为写坏了指令
kitty_ce op="R|0xK32_ADDR|bytes:8"
回包：字节正确
判读：字节没错，是被检出。

往返3｜动作：改到自己的模块
kitty_prot action=query addr=<自有模块地址>
回包：Type=MEM_IMAGE（自有）
kitty_ce op="W|<自有模块>|bytes:5|<jmp>" confirm=true
回包：稳定运行
判读：这一步对了。

往返4｜动作：验证
kitty_ce op="R|<自有模块>|bytes:5"

收敛｜末态验证
补丁点回读正确 + 功能侧行为变化 + 无崩溃
末态：改自有模块，系统模块保持原样。
复盘：不动系统模块代码页；要拦 API 用 IAT hook 或断点。"""),

("我用 MODBASE 拿基址，拿到了磁盘里的 ImageBase。",
"""往返1｜动作：MODBASE 单点查
kitty_ce op="MODBASE|TARGET.exe"
回包：0x140000000
判读：看着合理。

往返2｜动作：用它算地址
kitty_ce op="R|0x140001000|dword"
回包：读失败
判读：第一次失败。

往返3｜动作：对照 MODENUM
kitty_ce op=MODENUM
回包：TARGET.exe|0x7FF6DADB1000|1|0
判读：坐实 —— MODBASE 回的是磁盘 ImageBase（fallback 路径）。

往返4｜动作：改用 MODENUM 的 base
kitty_ce op="R|0x7FF6DADB2000|dword"
回包：正常

收敛｜末态验证
以 MODENUM 为唯一 base 来源，地址可读
末态：地址计算链路修正。
复盘：MODENUM 权威；MODBASE 只做 fallback 且要交叉验证。"""),

("我以为样本在删文件，其实是创建。",
"""往返1｜动作：看导入就下结论
kitty_sym action=imports path=SAMPLE.exe filter=Delete
回包：DeleteFileW 存在
判读：草率 —— 有导入不等于调用。

往返2｜动作：静态看调用点
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<n>-<ts> filter=DeleteFileW
回包：xref=0
判读：坐实 —— 死代码，永远不会执行。

往返3｜动作：改看真正写文件的调用
kitty_sym action=imports path=SAMPLE.exe filter=Create
回包：CreateFileW 有 xref
判读：这一步对了。

往返4｜动作：动态确认
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x2000"
回包：有变化

收敛｜末态验证
运行后目标路径出现新文件（存在性检查）
末态：确认是创建不是删除。
复盘：导入存在 ≠ 被调用；xref 与运行期证据缺一不可。"""),

("我在 64 位里用 dword 读指针，高位丢失后地址失效。",
"""往返1｜动作：dword 读指针
kitty_ce op="R|0xADDR|dword"
回包：0xDADB2000
kitty_ce op="R|0xDADB2000|dword"
回包：读失败
判读：第一次失败。高 32 位（0x7FF6）丢了。

往返2｜动作：以为地址被释放
kitty_prot action=query addr=0xDADB2000
回包：INVALID_ADDRESS
判读：不是释放，是截断。

往返3｜动作：改读 qword
kitty_ce op="R|0xADDR|qword"
回包：0x7FF6DADB2000
判读：这一步对了。

往返4｜动作：验证
kitty_prot action=query addr=0x7FF6DADB2000
回包：MEM_IMAGE 合法

收敛｜末态验证
指针能过 query 且指向预期模块
末态：指针读取统一用 qword。
复盘：64 位指针一律 qword；截断后的地址不报错只失效。"""),

("我改了结构体指针，程序立刻崩，忘了还有别处引用。",
"""往返1｜动作：改指针字段
kitty_ce op="W|0xOBJ+0x8|qword|<新指针>" confirm=true
回包：程序崩溃
判读：第一次失败。另有持有者仍指向旧对象。

往返2｜动作：回滚
kitty_ce op="W|0xOBJ+0x8|qword|<原指针>" confirm=true
回包：程序恢复
判读：确认是这次写导致。

往返3｜动作：统计引用
kitty_ce op="P_BACK|0xOLD_OBJ|0xALLOC_BASE|0xALLOC_BASE+0x400000"
回包：4 个引用点
判读：坐实 —— 单点替换不成立。

往返4｜动作：改为改对象内容而不是换指针
kitty_ce op="W|0xOLD_OBJ+0xOFF|dword|<新值>" confirm=true
回包：稳定

收敛｜末态验证
行为变化 + 程序未崩 + 引用点无需改动
末态：改内容不改指针。
复盘：换指针前先数引用；单点替换在多引用下必崩。"""),

("我以为要逆算法，其实样本调用了系统 API 就完事。",
"""往返1｜动作：从字符串找算法名
kitty_patch action=find path=SAMPLE.exe str=sha limit=8
回包：0 命中
判读：第一次失败。

往返2｜动作：找常量表
kitty_patch action=find path=SAMPLE.exe pattern="67 45 23 01" limit=4
回包：0 命中
判读：第二次失败。

往返3｜动作：看导入
kitty_sym action=imports path=SAMPLE.exe filter=Crypt
回包：BCryptHashData / CryptCreateHash
判读：坐实 —— 用的是系统加密库，算法在系统里。

往返4｜动作：找算法标识
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=search out=logs\\ghidra-<n>-<ts> filter=BCryptOpenAlgorithmProvider
回包：参数含 SHA256 的宽字符串

收敛｜末态验证
算法标识字符串命中，输入输出可用系统 API 复现
末态：不需要逆算法，只需记录算法标识与密钥来源。
复盘：先看是否调用加密 API，再决定要不要逆实现。"""),

("我用 kitty_prot query 判「是否模块」，结果 MEM_IMAGE 也有非模块区。",
"""往返1｜动作：只看 Type
kitty_prot action=query addr=0xADDR
回包：MEM_IMAGE
判读：直接判为模块内 —— 太草率。

往返2｜动作：对照模块表
kitty_ce op=MODENUM
回包：AllocationBase 不在表里
判读：坐实 —— 是已卸载模块的残留或映射映像。

往返3｜动作：加固判据
判读：模块内 = Type=MEM_IMAGE 且 AllocationBase ∈ 模块表
回包：—

往返4｜动作：验证残留
kitty_ce op="R|0xADDR|bytes:2"
回包：4D 5A

收敛｜末态验证
归属判定改为「双条件」，残留区单独标记
末态：判定规则修正。
复盘：单看 Type 不够，必须叠加模块表核对。"""),

("我把 .pdata 当函数表，函数数量对不上。",
"""往返1｜动作：按 .pdata 条数估函数数
kitty_die action=detect target=SAMPLE.exe
判读：.pdata size / 12 = 条数
回包：421

往返2｜动作：与 Ghidra 对比
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=functions out=logs\\ghidra-<n>-<ts> limit=200
回包：函数数远超 421
判读：第一次失败 —— 两者口径不同。

往返3｜动作：理解口径
判读：.pdata 只覆盖需要栈展开的函数；叶子函数不在其中
回包：—

往返4｜动作：用 .pdata 做「栈回溯」而不是计数
kitty_x64dbg action=seed addr=<崩溃点> seedCmd=readdb
判读：readdb 能展开调用栈

收敛｜末态验证
栈帧展开成功，与 .pdata 条目对应
末态：.pdata 用于回溯，函数计数用反汇编器。
复盘：每个结构的用途不同，别拿它当另一种用途的替代品。"""),

("我在同一地址连续写两次，第二次没生效。",
"""往返1｜动作：连写两次同值
kitty_ce op="W|0xADDR|dword|99" confirm=true
kitty_ce op="W|0xADDR|dword|99" confirm=true
回包：两次都 OK
判读：—

往返2｜动作：读回
kitty_ce op="R|0xADDR|dword" → 原值
判读：第一次失败 —— 两次都被吞。

往返3｜动作：查保护
kitty_prot action=query addr=0xADDR
回包：Protect=RX（模块代码页）

往返4｜动作：先改保护再写
kitty_prot action=protect addr=0xADDR size=0x1000 protect=rw confirm=true
kitty_ce op="W|0xADDR|dword|99" confirm=true
kitty_ce op="R|0xADDR|dword" → 99

收敛｜末态验证
回读 99 + 双视图一致 + 保护已还原
末态：写入生效。
复盘：代码页写不进去不是「被拦」，先核 Protect。"""),

("我以为 S_SNAP 只支持 dword，其实支持 bytes。",
"""往返1｜动作：用 dword 快照
kitty_ce op="S_SNAP|dword|0xSTART|0xSTOP"
回包：可以跑
判读：—

往返2｜动作：想监控 16 字节结构
判读：dword 只能覆盖 4 字节
回包：—

往返3｜动作：改用 bytes:16
kitty_ce op="S_SNAP|bytes:16|0xSTART|0xSTOP"
回包：成功
判读：这一步对了。

往返4｜动作：取变化
kitty_ce op=S_CHANGED
回包：变化页列表

收敛｜末态验证
变化页里的 16 字节块与预期结构一致
末态：用 bytes:16 监控整结构。
复盘：先查类型支持面，别假设只有整数类型。"""),

("我拿错版本的参考文件算一致率，得出「脱壳失败」。",
"""往返1｜动作：dump 后算一致率
kitty_dump module=TARGET.exe unmap=true fix_iat=true path=logs\\d.bin reference=OTHER.exe
回包：一致率 41%
判读：第一次失败 —— 结论下早了。

往返2｜动作：以为壳有两层
kitty_die action=detect target=logs\\d.bin
回包：节表正常、熵正常
判读：不像双层壳。

往返3｜动作：核参考文件版本
kitty_patch action=hash path=OTHER.exe
kitty_patch action=info path=TARGET.exe
回包：节数/大小都不同
判读：坐实 —— 参考文件根本不是同版本。

往返4｜动作：换正确参考
kitty_dump module=TARGET.exe unmap=true fix_iat=true path=logs\\d2.bin reference=TARGET.exe
回包：98.2%

收敛｜末态验证
一致率 >95% 且 IAT 可解析
末态：脱壳成功。
复盘：一致率的有效性完全取决于参考文件是否同源。"""),

("我把 BATCH 的 ops 写成了单条字符串，解析错位。",
"""往返1｜动作：ops 传单个字符串
kitty_ce ops="R|0xADDR|dword"
回包：解析异常
判读：第一次失败。ops 是数组。

往返2｜动作：传数组但内含逗号
kitty_ce ops=["R|0xADDR|dword, R|0xADDR2|dword"]
回包：整条被当一条
判读：第二次失败。

往返3｜动作：一条一个元素
kitty_ce ops=["R|0xADDR|dword","R|0xADDR2|dword"]
回包：两条独立回包
判读：这一步对了。

收敛｜末态验证
回包条数 == ops 条数
解析异常时先判通道而不是猜格式：
```
kitty_ce op=PING
```
判读：PING 正常说明桥在，问题在 ops 的组织方式；PING 也超时则是通道问题。

末态：批量读正确 + 通道判活一次。
复盘：ops 是数组，元素内不能夹分隔符。"""),
]

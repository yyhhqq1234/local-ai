# -*- coding: utf-8 -*-
"""re-detour-trajectory 源 part A (1-15)。格式：选错 → 报错 → 换动作 → 收敛；≥3 来回，末态可验证。"""

DET_A = [
(
"我知道血量显示 1500，想直接扫出来。结果每一步都顶回来，完整走一遍给我看。",
"""往返1｜动作：一次扫全地址空间
kitty_ce op="S_NEW|dword|1500|0x0|0xFFFFFFFFFFFFFFFF" wait=true
回包：pending 后超时，无样本
判读：错在区间。全空间跨越大量未映射页，作业永远走不完。
不是桥的问题（PING 正常），是我给的窗口错。

往返2｜动作：改成整主模块，但 size 没取
kitty_ce op="S_NEW|dword|1500|0x7FF700000000|0x7FF700000000+0x05000000"
回包：ERR| 段数/格式错（表达式不被接受）
判读：错在写法。OP 只认字面量，必须先算成绝对地址。

往返3｜动作：取真实窗口
kitty_ce op=MODENUM
回包：kitty-target.exe|0x7FF6DADB1000|1|0        ← size=0
判读：size=0，窗口仍然算不出来。这是第二次失败。

往返4｜动作：镜像头兜底
kitty_ce op="R|0x7FF6DADB1000+0x3C|dword" 仍带表达式 → 被拒
改正：先 kitty_ce op="R|0x7FF6DADB1000|dword" 不行（那是 MZ 头）
正确写法：
kitty_ce op="R|0x7FF6DADB103C|dword"             → 0xE8 (e_lfanew)
kitty_ce op="R|0x7FF6DADB10E8+0x50|dword" 又要算：0x7FF6DADB1138
kitty_ce op="R|0x7FF6DADB1138|dword"             → 0x01C00000 (SizeOfImage)

往返5｜动作：分块扫
kitty_ce op="S_NEW|dword|1500|0x7FF6DADB1000|0x7FF6DADCD1000" wait=true top=20
回包：OK|done|n=37
判读：37 个候选，量级正常。

收敛｜改一次血量再收窄
kitty_ce op=S_CHANGED                                → n=3
kitty_ce op="S_GET|0|3"
kitty_ce op="R|0x7FF6DAE12340|dword"                 → 1480（与界面一致）
kitty_ce op="R|0x7FF6DAE12348|dword"                 → 1500（僵值）
kitty_ce op="R|0x7FF6DAE123F0|dword"                 → 1480（与界面一致）
末态验证：对 0x7FF6DAE12340 写入 1000 后 R 回读为 1000，界面同步变化 →
地址确认，另有同值地址是镜像副本（写它界面不动，已排除）。""",
),
(
"想脱 UPX 壳，先拿 IDA 硬啃，结果全是垃圾。把踩坑过程写出来。",
"""往返1｜动作：直接 kitty_ida action=analyze target=SAMPLE.exe
回包：函数数 3，反编译体全是 call $+5 / jmp 循环
判读：错在工具选择。壳的 stub 只有一个解压循环，IDA 解不出业务代码。
症状特征：函数极少 + 大量自跳转 = 停在壳层。

往返2｜动作：手工在 IDA 里追解压循环
回包：循环体里读取 .text 源区、写到 .text 目标区，但跳转目标靠寄存器算出
判读：静态追不动（写目标在运行期算），必须动态。

往返3｜动作：直接 kitty_ce op="S_NEW|dword|1500|..." 找目标值
回包：命中 0
判读：错在前提。壳没脱，目标逻辑还没解密进内存，扫不到是正常的。
症状：连导入都只有一个模块在内存里 —— 说明根本没跑到业务初始化。

往返4｜动作：换正规脱壳路径
kitty_unpack action=probe target=SAMPLE.exe
回包：识别 UPX，版本 3.96
kitty_unpack action=extract target=SAMPLE.exe out=logs\\unpacked
回包：产出 logs\\unpacked\\SAMPLE.exe
判读：这一步才对。之前一直在错误层面做功。

往返5｜动作：验证脱壳质量（不信任「看起来解开了」）
kitty_die action=detect target=logs\\unpacked\\SAMPLE.exe
回包：.text 熵 6.42，节名 .text/.rdata/.data/.rsrc 标准
kitty_dump module=<运行时> unmap=true fix_iat=true reference=logs\\unpacked\\SAMPLE.exe
回包：一致率 96.3%

收敛｜末态验证
kitty_sym action=imports path=logs\\unpacked\\SAMPLE.exe
回包：导入 47 项，含 RegSetValueExW / WinHttpOpen / CreateProcessW
末态：脱壳文件可比磁盘、IAT 可解析、导入面从 2 项回到 47 项 → 业务层可读。
之后才在脱壳产物上做 kitty_sym action=imports 的 xref，才拿到真正的行为面。""",
),
(
"P_BACK 一直打满 200，我改了三轮窗口才收敛。复盘一下。",
"""往返1｜动作：整模块窗口反查
kitty_ce op="P_BACK|0x7FF6DAE12340|0x7FF6DADB1000|0x7FF6DB7B1000"
回包：ERR|TOO_MANY_HITS|200
判读：错在窗口。整模块 0x0A000000 里凡是值等于该地址的 8 字节全被算进来，
池化分配器会把同一指针复制几十份。

往返2｜动作：凭猜缩到 16MB
kitty_ce op="P_BACK|0x7FF6DAE12340|0x7FF6DADB1000|0x7FF6DADB1000+0x01000000"
回包：仍是 200 条
判读：还是错。缩窗口不解决「容器归属」问题 —— 我把模块窗口当容器了，
指针实际存在堆上，模块里那些命中全是巧合的同值常量。

往返3｜动作：先问加载器「这块归谁」
kitty_prot action=query addr=0x7FF6DAE12340
回包：AllocationBase=0x1D2A0000000 RegionSize=0x400000
判读：目标在堆上。模块窗口根本没覆盖真凶，之前两轮方向都错。

往返4｜动作：按 AllocationBase 反查
kitty_ce op="P_BACK|0x7FF6DAE12340|0x1D2A0000000|0x1D2A0040000"
回包：OK|5 条
判读：命中 5 条，量级正常。

往返5｜动作：多跳直接交给 pchain，别手写窗口
kitty_pchain target=0x7FF6DAE12340 depth=3 mod=kitty-target.exe max_verify=24
回包：链条 3 级 + 每级验证结果
判读：pchain 内部按模块区域过滤，比手给窗口稳。

收敛｜末态验证
kitty_ce op="P_WALK|0x7FF6DADB1000|0x2A1B4C"
回包：读到 0x7FF6DAE12340（与目标一致）
末态：模块基址 + 偏移 → 2 跳 → 目标地址，P_WALK 回验通过。
复盘结论：先 query 定容器，再反查；不要在模块窗口里找堆指针。""",
),
(
"DBG_ATTACH 把宿主搞没了。我是怎么走回正路的？",
"""往返1｜动作：kitty_dbg action=attach addr=... iface=2
回包：要求 accept_host_loss=true
判读：这个前置提示本身就是信号 —— 该路径在本 build 有 fail-fast 风险。

往返2｜动作：按提示强上
kitty_dbg action=attach iface=2 accept_host_loss=true
回包：KittyCE 进程消失，桥 PING 超时
判读：确认失败。宿主被杀，通道全断，这一轮实验作废。

往返3｜动作：先救宿主，不继续调试
kitty_drv action=host reset_breaker=true
回包：宿主重拉成功，PING 正常
判读：这一步必须做 —— 不修通道就重试，只会连续杀宿主并触发看门狗熔断。

往返4｜动作：换通道。先用内存面取证据，不走调试器
kitty_ce op=MODENUM
回包：kitty-target.exe|0x7FF6DADB1000|1|0
kitty_dump module=kitty-target.exe unmap=true path=logs\\mem.bin
回包：落盘 + 节表重建
判读：没有调试器也能拿到全部代码与数据。

往返5｜动作：真需要断点时改走 C 通道
kitty_x64dbg action=selftest
回包：通道自检通过
kitty_x64dbg action=seed addr=0x7FF6DADB1234 seedCmd=savedata logs\\hit.bin, kitty-target.exe, 64
回包：命中并落盘
判读：C 通道不碰 CE 宿主，风险面完全不同。

收敛｜末态验证
kitty_ce op=PING → 正常
kitty_status probe=true → pending=0
savedata 落盘的 hit.bin 首字节与 kitty_ce op="R|0x7FF6DADB1234|bytes:16" 一致
末态：证据拿到、宿主存活、通道干净。
纪律：本 build 的 DBG_ATTACH 一律不走，需要断点走 kitty_x64dbg。""",
),
(
"dump 出来的镜像喂给 IDA，导入全是无效地址。三次返工过程。",
"""往返1｜动作：kitty_dump module=kitty-target.exe path=logs\\raw.bin（默认 unmap=false）
kitty_ida action=analyze target=logs\\raw.bin
回包：函数数正常，但导入表 0 项，所有外部调用显示 sub_xxx
判读：错在没 unmap。内存镜像是按页对齐映射的，IDA 按文件偏移读 → 错位。

往返2｜动作：直接 unmap 但不修 IAT
kitty_dump module=kitty-target.exe unmap=true fix_iat=false path=logs\\un.bin
kitty_sym action=imports path=logs\\un.bin
回包：导入项存在但地址全指向模块内（0x7FF6...）
判读：还是错。IAT 里存的是运行期解析后的绝对地址，unmap 只是搬运，
不修 IAT 就等于把运行时指针塞进磁盘格式文件。

往返3｜动作：从 ILT 回填
kitty_dump module=kitty-target.exe unmap=true fix_iat=true path=logs\\fixed.bin reference=SAMPLE.exe
回包：一致率 82.4%
判读：方向对了。82% 说明代码段对得上，但还有 17% 差异 —— 是重定位/校验和残留。

往返4｜动作：查差异来源
kitty_patch action=info path=logs\\fixed.bin
回包：Checksum 字段非 0，节 PointerToRawData 有 3 处与参考不同
判读：差异集中在头部与节表，不是代码。可以接受。

收敛｜末态验证
kitty_sym action=imports path=logs\\fixed.bin
回包：导入 38 项，KERNEL32/ADVAPI32/WINHTTP 全部可解析
kitty_ida action=analyze target=logs\\fixed.bin
kitty_ida action=imports out=logs\\ida-fixed-<ts> limit=20
末态：导入表可解析 + 反汇编里外部调用有名字 + 一致率 82.4%（头部差异已解释）。
结论：unmap 与 fix_iat 必须同时开，且必须给 reference 算一致率，否则你不知道修没修对。""",
),
(
"用 frida 挂 APK 一直崩，换了三条路才拿到 dex。",
"""往返1｜动作：kitty_frida action=attach pkg=<包名>
回包：ATTACH_FAIL（进程已退出，检测到 frida-server）
判读：错在时机。加固应用在 Application.onCreate 里做完整性检测，
attach 到已运行进程必然被发现。

往返2｜动作：改 spawn 模式但脚本里加了大量 hook
kitty_frida action=spawn pkg=<包名>
kitty_frida action=script pkg=<包名> script=<大而全的 hook 脚本>
回包：进程起来 2 秒后闪退
判读：还是错。hook 面太宽（含 dex 加载、类加载、反射），本身就成了检测特征。

往返3｜动作：最小化 hook，只挂一个点
kitty_frida action=spawn pkg=<包名>
kitty_frida action=script pkg=<包名> script=<只 hook DexFile.loadDex / openDexFile，落盘内存 dex>
回包：产出 3 个 dex 文件
判读：这一步对了。最小面 + 早期时机。

往返4｜动作：验证 dex 是不是真的业务层
kitty_jadx action=status
kitty_jadx action=decompile target=logs\\dex\\classes.dex out=logs\\jadx-1
回包：类名全是壳的 com.xxx.StubApp
判读：失败。拿到的是壳自己的 dex，业务 dex 在后续动态加载。

往返5｜动作：延后落盘时机（等业务 dex 加载完）
kitty_frida 脚本改为在 loadDex 返回后延迟 500ms 落盘
回包：产出 5 个 dex，其中一个含业务包名
判读：正确。

收敛｜末态验证
kitty_jadx action=decompile target=logs\\dex\\business.dex out=logs\\jadx-biz
kitty_rea_method path=app.apk class_name=<登录类> method_name=<签名方法>
末态：能在业务 dex 里定位到签名方法，且方法体出现字段拼接 + MessageDigest 调用。
复盘：spawn 早于 attach、hook 面越小越好、落盘要等业务 dex 加载完。""",
),
(
"找指针链，我按错的上一级结构算了三轮偏移。",
"""往返1｜动作：假设「血量在玩家结构 +0x1A0」，直接算
kitty_ce op="R|0x7FF6DADB1000+0x1A0|..." 表达式被拒 → 改真值 0x7FF6DADB11A0
kitty_ce op="R|0x7FF6DADB11A0|dword"
回包：0x00000000
判读：错在假设。模块基址+偏移读不到东西，说明玩家对象不在模块里。

往返2｜动作：改成「模块里存的是指向玩家的指针」
kitty_ce op="R|0x7FF6DADB11A0|qword"
回包：0x0000000000000000
判读：还是错。这个偏移根本没被写入过。

往返3｜动作：从已知的血量地址往上反查，不再猜偏移
kitty_ce op="R|0x7FF6DAE12340|dword"            → 1500（确认目标）
kitty_prot action=query addr=0x7FF6DAE12340
回包：AllocationBase=0x1D2A0000000 RegionSize=0x2000000
kitty_ce op="P_BACK|0x7FF6DAE12340|0x1D2A0000000|0x1D2A0100000"
回包：OK|4 条
判读：这一步才建立正确方向 —— 血量在堆对象里，先找「谁指向这个堆对象」。

往返4｜动作：拿到候选后逐条回验，而不是取第一条
kitty_ce op="P_BACK_RES|4"
kitty_ce op="R|0x1D2A0034010|qword"  → 0x1D2A0001234（不是目标，排除）
kitty_ce op="R|0x1D2A0041200|qword"  → 0x1D2A0012340（不是目标，排除）
kitty_ce op="R|0x1D2A0054500|qword"  → 0x7FF6DAE12340（命中）
判读：三条里有两条是「容器首地址」而非目标，必须逐条 R 回验。
之前的错误是假设候选顺序即相关性。

往返5｜动作：上一级继续反查，用 pchain 免手算窗口
kitty_pchain target=0x1D2A0054500 depth=2 mod=kitty-target.exe
回包：→ 0x1D2A0008000 → 模块静态区 0x7FF6DB2A1000

收敛｜末态验证
kitty_ce op="P_WALK|0x7FF6DB2A1000|0x1450"
回包：0x1D2A0054500 → 回验一级
kitty_ce op="R|0x1D2A0054500|qword" → 0x7FF6DAE12340 → 二级
末态：静态基址 + 两级偏移 → 血量地址，两级都通过 R 回验。
复盘：偏移是算出来的，不是猜出来的；每个候选都必须回验。""",
),
(
"读一个被保护的地址，W 一直失败，走过三条路径。",
"""往返1｜动作：直接写
kitty_ce op="W|0x7FF6DADB2000|dword|99" confirm=true
回包：ERR|WRITE_DENIED
判读：第一次失败。原因未定 —— 可能是页只读，也可能是保护机制拦。

往返2｜动作：猜是保护位问题，改页属性
kitty_prot action=protect addr=0x7FF6DADB2000 size=0x1000 protect=rw confirm=true
回包：ERR|PROTECT_FAIL
判读：第二次失败。连改页属性都被拒，说明拦在更上层（不是普通只读页）。

往返3｜动作：查真实状态，不再猜
kitty_prot action=query addr=0x7FF6DADB2000
回包：State=COMMIT Protect=PAGE_READONLY Type=MEM_IMAGE
判读：MEM_IMAGE 说明这是模块映射页 —— 改模块页容易被完整性校验抓到，
VirtualProtectEx 被拒也印证了有拦截面。

往返4｜动作：走 PTE 直改（不调保护 API）
kitty_wpb addr=0x7FF6DADB2000 val=99 vt=dword restore=true accept_protection_bypass=true
回包：DTB→PTE→自映射VA→改R/W→写入→还原，全链 OK
判读：通了。这条路径不需要目标进程句柄。

往返5｜动作：双视图回读（不信任单视图）
kitty_ce op="R|0x7FF6DADB2000|dword"        → 99
kitty_km action=read addr=0x7FF6DADB2000 vt=dword   → 99
判读：两视图一致，写入真实生效（不是影子页）。

往返6｜动作：复核 PTE 已还原
kitty_km action=pa addr=0x7FF6DADB2000
kitty_dualview addr=0x7FF6DADB2000 vt=dword samples=2
回包：三视图一致，无分叉
判读：暴露窗口已关闭。

收敛｜末态验证
末态：R=99、KM_R=99、三视图无分叉、PTE 已还原。
复盘：W 失败先 query，query 显示 MEM_IMAGE 就别硬改保护位 —— 直接走 wpb 并还原。""",
),
(
"KM_R 和 R 值不一样，我一开始以为是巧合。全过程。",
"""往返1｜动作：目标读值
kitty_ce op="R|0x7FF6DAE12340|dword"
回包：1500
判读：看着正常，但我知道这个值应该被改过。

往返2｜动作：用内核路由读同一地址
kitty_km action=attach pid=<pid>
kitty_km action=read addr=0x7FF6DAE12340 vt=dword
回包：1480
判读：不一致。第一反应是「读错地址」，但两次地址完全相同。

往返3｜动作：排除地址错误
kitty_prot action=query addr=0x7FF6DAE12340
回包：单次分配，AllocationBase 一致
kitty_dualview addr=0x7FF6DAE12340 vt=dword samples=3
回包：三视图——R=1500 / KM_R=1480 / 物理=1480
判读：物理与内核一致，只有用户态路径不同 → 用户态读被拦（典型 hook 返回假值）。

往返4｜动作：确认「拦的是读 API 而不是页」
kitty_km action=pa addr=0x7FF6DAE12340
kitty_km action=pread pa=0xPA vt=dword
回包：1480
判读：物理值 1480，坐实用户态路径返回了伪造值。

往返5｜动作：改用可信视图取真值
kitty_km action=read addr=0x7FF6DAE12340 vt=dword → 1480
判读：后续所有读都用 KM_R。

收敛｜末态验证
kitty_dualview addr=0x7FF6DAE12340 vt=dword samples=3 note=after-fix
回包：分叉记录落 logs/anti-ace-<date>.jsonl
末态：证据链完整 —— R/KM_R/物理 三视图 + 分叉 JSONL + 物理自证。
判读修正：之前基于 R 值做的所有「没变化」结论全部作废，重跑改值验证。
纪律：分叉不是错误，是结论；先取证再换视图。""",
),
(
"给 UE pak 解包，AES key 找错两轮才通。",
"""往返1｜动作：直接解包
kitty_fmodel action=list pak=<pak 路径>
回包：ERR|AES_KEY_REQUIRED
判读：确认加密。第一次失败，至少排除了「明文 pak」。

往返2｜动作：凭经验填一个常见测试 key（32 个 0）
kitty_fmodel action=list pak=<pak 路径> aesKey=0000...0000
回包：ERR|DECRYPT_FAIL 或索引读出乱码
判读：第二次失败。不能猜 —— AES-256 的 key 空间猜不出来。

往返3｜动作：换方向，去 exe 里找 key 落点
kitty_patch action=find path=<游戏 exe> str=crypto.json limit=8
kitty_patch action=find path=<游戏 exe> pattern="63 72 79 70 74 6F" limit=8
回包：命中一处 crypto.json 引用
判读：有配置文件引用，说明 key 可能在游戏目录的 json 里，不在 exe 里硬编码。

往返4｜动作：按引用去目录找
kitty_patch action=find path=<游戏 exe> str=..\\..\\ limit=16
判读：从拼接路径推出配置相对位置（常见 Content/Paks/ 同级）
实际查到 crypto.json 后取其 key 字段
判读：拿到 32 字节十六进制串候选。

往返5｜动作：验 key 是不是被加载器真用了
kitty_ce op=MODENUM                                    → base
kitty_ce op="S_NEW|bytes:32|<key 候选>|0xBASE|0xBASE+0x10000000" wait=true top=5
回包：命中 1 处（在模块的 .data 段）
判读：坐实该 key 被加载器加载 —— 这比「能解开包」更强的证据。

收敛｜末态验证
kitty_fmodel action=list pak=<pak 路径> aesKey=<key>
回包：资产清单（含 .uasset/.uexp）
kitty_fmodel action=extract pak=... out=logs\\ue
末态：能列出并导出一个资产；key 在内存中有命中证据。
复盘：不要把「能解密」当唯一判据；要证明 key 是被加载器使用的那个。""",
),
(
"想在不重启的情况下热更 DLL，改了三次方案。",
"""往返1｜动作：直接覆盖目标进程里的 DLL 文件
（文件已加载，写入）
回包：共享冲突 / 写入被拒
判读：第一次失败。映像已映射，文件被独占。

往返2｜动作：先卸载模块再覆盖
尝试远程 FreeLibrary
回包：不安全 —— 目标可能有别的线程正在执行该模块代码，卸载会导致崩溃
判读：方案错。热更的难点不是写文件，是「没人正在执行旧代码」。

往返3｜动作：改为「新名字 + 重定向」
把新 DLL 写成 _v2.dll，改导入表指向 —— 但导入表在内存里已解析，改不了
判读：第二次失败。磁盘改导入不影响已加载进程。

往返4｜动作：走内存 patch，不动文件
kitty_ce op=MODENUM                                   → 取目标 DLL base/size
kitty_ce op="R|0xBASE+0x1000|bytes:16"                → 记录原字节
kitty_asm action=assemble code="mov rax,0x<新函数VA>\\njmp rax" base=0x<目标VA>
判读：跳板方案 —— 在旧函数入口写无条件跳转到新实现，不动文件、不卸载模块。
kitty_ce op="W|0xBASE+0x1000|bytes:N|<跳板字节>" confirm=true

往返5｜动作：改完回读验证
kitty_ce op="R|0xBASE+0x1000|bytes:16"
回包：字节与新写入一致
判读：写入生效。

收敛｜末态验证
kitty_ce op="R|0xBASE+0x1000|bytes:N"   → 与补丁字节逐字节一致
功能侧：触发原调用路径，行为走新实现（日志/返回值变化）
回滚记录：原 16 字节已存日志，用同一条 W 写回即还原
末态：功能生效 + 可回滚 + 未动磁盘文件。
复盘：热更的正确层面是内存跳板，不是文件替换。""",
),
(
"要在一台新机上复现上次的地址，全对不上。三段纠错。",
"""往返1｜动作：直接用上次记的绝对地址
kitty_ce op="R|0x7FF75FCD1000|dword"
回包：读到的是别的模块的数据（不是崩溃，但值不对）
判读：错在地址复用。ASLR 每次启动都变。

往返2｜动作：以为关掉 ASLR 就行（改 PE 头 DllCharacteristics）
kitty_patch action=find path=TARGET.exe pattern="40 81" （DYNAMIC_BASE 位）
回包：找到候选
判读：这是改文件，属于重新打包，不是「跨机复现」；而且系统强制 ASLR 会覆盖。

往返3｜动作：改存模块内偏移
kitty_ce op=MODENUM                                 → 0x7FF6DADB1000（新的 base）
偏移 = 上次 0x7FF75FCD1000 - 上次 base 0x7FF75FCD0000 = 0x1000
kitty_ce op="R|0x7FF6DADB1000+0x1000|..." 表达式被拒
改真值：kitty_ce op="R|0x7FF6DADB2000|dword"
回包：0x00000000
判读：第三次失败。偏移换算对了，但地址内容不对 —— 说明模块基址选错了：
上一次分析的可能不是同一个模块。

往返4｜动作：先核对模块身份，再算偏移
kitty_ce op=MODENUM
回包：多行，逐行比对目标模块 name/base/size
判读：发现上次的 base 属于另一个同名 DLL 的旧版本，当前版本 size 变了。

往返5｜动作：按「节内偏移」而不是「模块内偏移」重建
kitty_patch action=info path=<同名 DLL 的磁盘文件>
节表 → 定位上次地址落在哪个节 + 节内偏移
kitty_ce op="R|0x<新base+节RVA+节内偏移>|dword"
回包：值符合预期

收敛｜末态验证
kitty_ce op="R|0x<新地址>|dword" → 目标值
kitty_km action=read addr=0x<新地址> vt=dword → 一致
末态：新机地址可复现，且换算链写成「模块名 + 节 + 节内偏移」三要素。
复盘：跨机复现必须存「模块身份 + 节内偏移」，绝对地址与模块内偏移都会漂。""",
),
(
"扫描一个 8 字节的时间戳，一直扫不到，走了四次。",
"""往返1｜动作：按 dword 扫十进制值
kitty_ce op="S_NEW|dword|1700000000|0x7FF6DADB1000|0x7FF6DADCD1000" wait=true
回包：OK|done|n=0
判读：第一次失败。零命中。

往返2｜动作：以为窗口太小，扩到整个模块
kitty_ce op="S_NEW|dword|1700000000|0x7FF6DADB1000|0x7FF6DB7B1000" wait=true
回包：OK|done|n=0
判读：第二次失败。扩窗无效 → 不是窗口问题，是类型或值的问题。

往返3｜动作：把值当十六进制再试（怀疑十进制/十六进制混淆）
kitty_ce op="S_NEW|dword|0x6553F100|0x7FF6DADB1000|0x7FF6DB7B1000" wait=true
回包：n=0
判读：第三次失败。0x6553F100 就是 1700000000 的十六进制，等价，必然一样。

往返4｜动作：核对类型的真实宽度（关键一步）
判读：时间戳在现代程序里常是 64 位 FILETIME 或 Unix 秒扩展成 8 字节；
用 dword 只能匹配到低 4 字节，而低 4 字节可能不在 4 字节对齐位置。
kitty_ce op="S_NEW|qword|1700000000|0x7FF6DADB1000|0x7FF6DB7B1000" wait=true
回包：OK|done|n=3
判读：换 qword 命中 3 条。类型宽度错，前面三轮全是无用功。

往返5｜动作：回读验证三条
kitty_ce op="S_GET|0|3"
kitty_ce op="R|0x7FF6DAE00800|qword"   → 1700000000
kitty_ce op="R|0x7FF6DAE01234|qword"   → 1700000012（另一个时间戳）
kitty_ce op="R|0x7FF6DAE09000|qword"   → 1700000000（符合）

收敛｜末态验证
kitty_ce op="W|0x7FF6DAE00800|qword|<新值>" confirm=true
kitty_ce op="R|0x7FF6DAE00800|qword"   → 新值
末态：写入并回读一致，界面时间同步变化。
复盘：扫不到先怀疑类型宽度，再怀疑窗口；扩窗是最贵的错误尝试。""",
),
(
"APK 重打包后装不上，签名问题，走了三次。",
"""往返1｜动作：apktool 解包 → 改 smali → 重打包 → 直接装
kitty_apktool action=decode target=app.apk out=logs\\apk
kitty_apktool action=build target=logs\\apk out=logs\\patched.apk
（用 kitty_adb 安装）
回包：INSTALL_FAILED_INVALID_APK / 无签名
判读：第一次失败。重打包产物没有签名。

往返2｜动作：用 debug key 签
签名（外部工具）后安装
回包：INSTALL_FAILED_UPDATE_INCOMPATIBLE（与已装版本签名不一致）
判读：第二次失败。同包名同 versionCode 但签名不同，系统拒绝升级。

往返3｜动作：改包名绕开冲突
改 AndroidManifest 的 package
回包：安装成功但应用启动即崩（找到的类名与包名绑定处不匹配）
判读：第三次失败。改包名破坏了硬编码的包名引用（含 native 侧）。

往返4｜动作：回到「同签名」路线 —— 先卸载再装，或保留原签名
kitty_apktool action=build target=logs\\apk out=logs\\patched.apk
卸载已装版本 → 用 debug key 签 → 安装
回包：安装成功
判读：正确路径。要么同签名（拿不到私钥），要么先卸载。

往返5｜动作：运行时验证 patch 是否真生效
kitty_frida action=spawn pkg=<包名>
kitty_frida action=script pkg=<包名> script=<hook 被改方法，打印返回值>
回包：返回值与 patch 预期一致
判读：patch 生效。

收敛｜末态验证
kitty_rea_android path=logs\\patched.apk
回包：清单可解析、包名未改、versionCode 未改
末态：安装成功 + 运行中方法返回值符合预期 + 包名与版本保持不变。
复盘：改包名是最贵的绕法，先试「卸载 + 重签」。""",
),
]

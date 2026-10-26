# -*- coding: utf-8 -*-
"""re-decision-chain 源 A3 (21-30)"""

CHAIN_A3 = [
(
"签名有效、公司名是微软，但文件名不像系统组件。判断顺序？",
"""[1] triage —— 先分离「签名链」与「身份」两件事
kitty_patch action=info path=TARGET.exe
判据：Security 目录可解析 = 签名结构完整；但这只证明「某证书签过」，不证明「它是微软的组件」。
退出条件：确认签名链有效性与证书 Subject 两栏。

[2] static —— 用路径与版本资源交叉
kitty_patch action=find path=TARGET.exe str=Microsoft utf16=true limit=16
kitty_patch action=find path=TARGET.exe str=Mozilla/4.0 limit=4
判据：版本资源（VS_VERSION_INFO）里的 CompanyName/OriginalFilename 是否与文件名一致；
不一致就是「借名」。
退出条件：给出「身份自洽 / 身份矛盾」判定。

[3] static 二次 —— 看它是否在系统目录之外
kitty_die action=detect target=TARGET.exe
判据：正常的系统组件不会从用户目录运行；PE 里若引用 %APPDATA% / %TEMP% 路径，矛盾加深。
退出条件：拿到 ≥2 条独立矛盾证据才算坐实借名。

[4] dynamic（受控）—— 只看加载面
kitty_ce op=PING
kitty_ce op=LP
判据：进程表里它是否被系统进程加载（lsass/services 加载 = 值得深查）。
退出条件：给出「是否被高权限进程加载」的结论。

[5] 导出
产物：签名链结论 + 身份矛盾清单 + 加载面结论。
纪律：不把「签名有效」当安全性结论；也不把「名字不像」当恶意结论。两条都要落到证据。""",
),
(
"APK 装完能跑，但 jadx 反出来只有壳的类。怎么进到业务层？",
"""[1] triage —— 先确认加固类型
kitty_apkscan action=scan target=app.apk
判据：APKiD 指纹（梆梆/爱加密/腾讯乐固/360/顶象）+ 是否只有 lib*/libshella-*.so。
退出条件：确定加固厂商与档位（整体加壳 / Dex 抽取 / VMP）。

[2] static —— 先拿壳外可见的部分
kitty_apktool action=decode target=app.apk out=logs\\apk
判据：AndroidManifest 的 application 类名是否被替换成壳类；
assets 下是否有加密的 dex（*.bin/*.dat）。
退出条件：确认业务 dex 的存放位置（assets / 内存 / 远端）。

[3] dynamic —— 脱壳取真实 dex
kitty_frida action=spawn pkg=<包名>
kitty_frida action=script pkg=<包名> script=<dump dex 的 hook 脚本> out=logs\\dex
判据：落盘的 dex 能被 kitty_jadx 解析且包含业务包名前缀。
退出条件：至少一个 dex 里能看到业务类（非壳类）。

[4] static 二次 —— 在脱壳产物上做业务分析
kitty_jadx action=decompile target=logs\\dex\\classes.dex out=logs\\jadx-app
判据：能否定位到登录/签名/加密方法。
退出条件：某个方法体里出现完整的字段拼接 + 摘要/加密调用。

[5] 导出
产物：加固指纹 + 脱壳 dex + 业务方法定位。
不做：硬读壳的 Java 层 —— 那是调度器，业务一定在脱出来的 dex 里。""",
),
(
"给了个 .so 文件（Android），要还原签名算法。顺序？",
"""[1] triage —— 先判架构与导出
kitty_rea_binary path=libnative.so
判据：ELF 架构（AArch64 / armv7）、是否 strip、导出符号（JNI 函数名 Java_xxx_yyy 是否保留）。
退出条件：确认 JNI 入口是否存在（存在则可以从 Java 侧反推调用点）。

[2] static —— 从 JNI 入口往下，不从字符串乱撞
kitty_ghidra action=analyze target=libnative.so
kitty_ghidra action=functions out=logs\\ghidra-so-<ts> filter=Java_
判据：JNI 函数体的第一个参数（JNIEnv*）用法；关键逻辑通常在 native 侧第二层。
退出条件：定位到「输入 → 变换 → 输出」三个点。

[3] static 二次 —— 认得算法族特征
kitty_patch action=find path=libnative.so pattern="67 45 23 01" limit=4
kitty_patch action=find path=libnative.so pattern="63 79 6E 67" limit=4
判据：MD5/SHA 的常量（0x67452301 系列）与轮常量；AES 的 SBox 特征字节。
退出条件：能说出「是标准摘要 / 是变种 / 是自定义」。

[4] dynamic —— Frida 在真机上验一次输入输出对
kitty_frida action=attach pkg=<包名>
kitty_frida action=script pkg=<包名> script=<hook JNI 入口，打印入参与返回值> out=logs\\jni.log
判据：同一输入多次调用输出是否稳定（含盐则不稳定，需再找随机源）。
退出条件：拿到 ≥3 组 (输入, 输出) 对，且与静态推导一致。

[5] 导出
产物：算法族结论 + 3 组输入输出对 + 关键常量偏移。
不做：把 .so 里搜到的每个字符串都当密钥 —— 先验证再用。""",
),
(
"固件 .bin，要找出里面跑的服务。顺序？",
"""[1] triage —— 先判容器与文件系统
kitty_die action=detect target=fw.bin
判据：是否有 MZ/ELF/UBI/squashfs 魔数（hsqs / sqsh / UBIV）或 gzip 容器。
退出条件：确定「单镜像 / 多分区 / 已压缩」。

[2] static —— 解出文件系统再谈服务
kitty_unpack action=scan target=fw.bin out=logs\\fw
判据：是否能切出分区表或直接解出目录树（bin/ etc/ lib/）。
退出条件：拿到根文件系统。解不开说明是私有容器，按偏移逐个试魔数。

[3] static 二次 —— 服务面清单，不看实现
kitty_patch action=find path=logs\\fw\\etc\\init.d\\* str=start limit=16
判据：init 脚本 / systemd unit 里启动的可执行文件 = 服务主体。
退出条件：列出「服务名 → 二进制 → 监听端口」三项。

[4] dynamic / 模拟 —— 只验可达性
kitty_net action=status
在隔离环境按 init 参数起该二进制，或直接静态读它的 bind/socket 调用：
kitty_sym action=imports path=logs\\fw\\usr\\sbin\\<服务> filter=socket
判据：是否有 bind + listen；端口号是常量还是配置文件。
退出条件：端口确定。

[5] 导出
产物：文件系统树 + 服务清单 + 端口表 + 未解容器说明。
不做：整盘 binwalk 到底再人工翻 —— 先定容器类型，再定向解。""",
),
(
"样本会写注册表，要定位写哪个键。顺序？",
"""[1] triage —— 先判持久化意图
kitty_sym action=imports path=SAMPLE.exe filter=Reg
判据：RegSetValueEx / RegCreateKeyEx 出现即确认；只看 RegQueryValue 说明是检测不是写入。
退出条件：确认写路径存在。

[2] static —— 先捞明文键名
kitty_patch action=find path=SAMPLE.exe str=Software\\ limit=32
kitty_patch action=find path=SAMPLE.exe str=Run utf16=true limit=16
判据：键名多为明文；命中 Software\\Microsoft\\Windows\\CurrentVersion\\Run 即自启动。
退出条件：拿到候选键名列表（≥1 条）。

[3] dynamic —— 在写入调用上取实参，而不是猜
kitty_ce op=PING
kitty_ce op=OPEN|<pid>
kitty_x64dbg action=seed addr=advapi32.RegSetValueExW seedCmd=log
判据：命中时第二个/第三个参数（hKey / lpValueName）直接给出真值。
退出条件：拿到 (主键句柄值 → 对应的子树, 子键名, 值名, 值数据) 四元组。
若调试器路径不可用，用等价路径：
kitty_ce op="S_NEW|bytes:16|<候选键名的宽字符编码>|0xBASE|0xBASE+SIZE" wait=true top=10
判据：命中地址落在堆/栈上即为键名缓冲，配合 kitty_ce op="R|0xADDR|bytes:64" 读全串。

[4] 导出
产物：注册表键全路径 + 值名 + 值数据 + 触发条件。
判据：能手工按该路径建键复现自启动。
不做：只交「会写注册表」—— 那不构成结论。""",
),
(
"要给一个自有 DLL 做兼容性修补（换掉一段校验分支）。顺序？",
"""[1] triage —— 先定位校验函数，不先想字节
kitty_sym action=exports path=TARGET.dll
kitty_ghidra action=analyze target=TARGET.dll
kitty_ghidra action=search out=logs\\ghidra-<name>-<ts> filter=<校验相关字符串>
判据：从字符串 xref 回到函数；函数体里有 cmp + 条件跳转 + 返回 0/1 的结构。
退出条件：拿到校验函数的文件偏移与目标跳转指令偏移。

[2] static —— 先算补丁字节，再动手
kitty_asm action=assemble code="xor eax,eax\\nret" base=0x<目标VA>
判据：nop 填充长度与原指令长度一致（避免破坏后续 rel 偏移）。
退出条件：拿到 expect 原字节 + 目标字节两串。

[3] 补丁 —— 带 expect 拒写，防错位
kitty_patch action=patch path=TARGET.dll at=0x<文件偏移> expect="<原字节>" bytes="<新字节>" confirm=true
判据：expect 不匹配必须拒绝；拒绝说明偏移算错，回头核 VA→文件偏移换算。
退出条件：patch 返回成功且自动备份 .bak 存在。

[4] 验证 —— 两道：静态字节 + 运行行为
kitty_patch action=find path=TARGET.dll pattern="<新字节>" from=<偏移-16> limit=2
kitty_patch action=hash path=TARGET.dll
判据：字节确认替换；哈希变化；校验和已重算（fix_checksum 默认 true）。
运行验证：调用原失败路径，返回应为「通过」。
退出条件：两道都过。

[5] 回滚点
kitty_patch action=rollback path=TARGET.dll
判据：能从 .bak 还原且哈希回到原值 —— 这条要先验一次，再交产物。""",
),
(
"要提取样本里内嵌的配置（C2 地址、密钥）。顺序？",
"""[1] triage —— 先判配置是明文、编码还是加密
kitty_patch action=find path=SAMPLE.exe str=http limit=16
kitty_patch action=find path=SAMPLE.exe str=.onion limit=4
判据：有明文 URL = 明文或简单异或；全无 = 加密或分片。
退出条件：判定配置形态。

[2] static —— 按形态分路
明文/异或：kitty_patch action=find path=SAMPLE.exe pattern="68 74 74 70" from=0 limit=32
判读：命中处前后 64 字节就是配置块，直接读。
编码：kitty_patch action=find path=SAMPLE.exe str=base64 相关字符表
加密：kitty_die action=detect 后看哪个节熵最高，配置常在该节首 0x200 内（结构体布局）。

[3] dynamic —— 配置一定会在运行期变明文，抓那一刻
kitty_ce op=OPEN|<pid>
kitty_ce op="S_SNAP|bytes:16|0xBASE+0x1000|0xBASE+0x11000"
运行到首次外联尝试前 → kitty_ce op=S_CHANGED
判据：变化页里必定有一处出现 http/域名形态的 ASCII。
退出条件：拿到明文配置块地址。
取样：kitty_ce op="R|0xADDR|bytes:256" 或 kitty_ce op="MEMDUMP_HEX|0xADDR|512"

[4] 交叉验证
kitty_net action=capture port=8080 观察首次外联目标
判据：抓到的域名/端口与提取的配置一致。
退出条件：一致即闭环；不一致说明配置有多份或走了备选。

[5] 导出
产物：配置结构表 + 明文字段 + 一条外联证据。
不做：把内存里所有 ASCII 都当配置交出去。""",
),
(
"要判断这个样本是不是同一个家族的新变种。顺序？",
"""[1] triage —— 先取可比对的指纹集
kitty_die action=detect target=NEW.exe
kitty_patch action=hash path=NEW.exe
判据：节名布局、熵曲线、导入组合、PDB 路径四项可比对特征。
退出条件：拿到四项指纹，且能在旧样本上取到同样四项。

[2] static —— 做「结构差分」而不是文本 diff
kitty_patch action=info path=NEW.exe
kitty_patch action=info path=OLD.exe
判据：节数/节名/入口节/数据目录布局是否同构；同构即同构建链。
退出条件：给出同构度（四项里命中几项）。

[3] static 二次 —— 函数级差分
kitty_ida action=analyze target=NEW.exe
kitty_ida action=functions out=logs\\ida-new-<ts> limit=200
kitty_rea action=call tool=compare_functions args={"left":<旧函数 Evidence>,"right":<新函数 Evidence>}
判据：函数级相似度高且差异集中在「新增的校验/新增的 C2 列表」= 变种而非新家族。
退出条件：拿到 ≥3 个高相似函数 + 差异摘要。

[4] dynamic —— 行为差分
kitty_ce op=OPEN|<pid>
kitty_ce op="S_NEW|bytes:16|<家族特征字节>|0xBASE|0xBASE+SIZE" wait=true top=10
判据：特征字节是否在新样本里出现且地址形态相似。
退出条件：行为面同族或明确不同族。

[5] 导出
产物：同族判定 + 同构度 + 差异清单（新增/删除/改动）。
判据：差异清单能落成「新增了什么能力」这句话。
不做：只凭哈希不同就判「新变种」。""",
),
(
"要交一份「该样本在目标机上有没有落地痕迹」的取证。顺序？",
"""[1] triage —— 先定痕迹类型，再定采集面
kitty_patch action=info path=SAMPLE.exe
kitty_sym action=imports path=SAMPLE.exe
判据：导入面给出可能的落地类型（文件/注册表/服务/计划任务）。
退出条件：列出 ≤5 个待查痕迹点，每个都有导入面支撑。

[2] static —— 提取落地路径常量
kitty_patch action=find path=SAMPLE.exe str=\\\\Users\\\\ limit=16
kitty_patch action=find path=SAMPLE.exe str=%APPDATA% limit=8
判据：路径模板 + 拼接规则决定真实路径形态。
退出条件：拿到可展开的路径模板（含变量位置）。

[3] 采集 —— 按模板查文件系统
kitty_ce op=PING 确认通道；文件系统侧走只读查询
判据：按模板展开后逐个核存在性与时间戳；时间戳落在样本运行窗口内才是痕迹。
退出条件：每个待查点给出「存在/不存在/时间不符」三态之一。

[4] 内存面补充 —— 只读
kitty_ce op=LP
判据：进程是否仍在运行；在运行则 kitty_ce op=OPEN|<pid> + MODENUM 看是否加载了可疑模块。
退出条件：给出「进程态 / 已退出」结论。

[5] 导出
产物：痕迹表（类型/路径/时间/证据来源）+ 未覆盖项。
判据：每条痕迹都有「导入面支撑 + 实际采集结果」两列。
纪律：不写「可能残留」；三态之外一律记为未覆盖。""",
),
]

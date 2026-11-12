# -*- coding: utf-8 -*-
"""forge2 B3 · ring0 可见面清单（20）+ B4 · 误报与取证失败模式（20）。检测/取证视角。"""
GROUP = "B"
CAT = "guard"

ROWS = [
    ("r0-handle-cb",
     "进程/线程句柄的打开，内核层能看到哪些信息？",
     "通过 ObRegisterCallbacks 注册的 pre/post 回调拿到：目标对象、请求的 AccessMask、调用方进程。判据："
     "READ 掩码对应 0x10/0x1FFFFF 之类的位组合，`kitty_acescan` 的写回环一旦触发跨进程访问，"
     "回调计数会 +1（可在驱动日志里比对前后值）。"),
    ("r0-proc-cb",
     "进程创建回调能拿到什么粒度？",
     "PsSetCreateProcessNotifyRoutineEx 给 (parent, pid, image path, command line)。判据："
     "回调触发时 `LP` 列表里同一 pid 出现，且 `image path` 与 `MODENUM` 首个模块名一致；"
     "两者不一致说明有路径重定向或改名。"),
    ("r0-image-load",
     "模块加载在内核层的可见点在哪？",
     "PsSetLoadImageNotifyRoutine：每次映射镜像都会回调，含 (FullImageName, ProcessId, ImageInfo)。判据："
     "`MODENUM|<pid>` 前后条目数差 N，与回调计数差 N 应相等；不等说明有模块走了手动映射（不走该回调）。"),
    ("r0-registry",
     "注册表访问怎么被看到？",
     "CmRegisterCallbackEx：pre/post 拿到 key 路径、操作类型、调用方。判据："
     "对 `HKLM\\SYSTEM\\CurrentControlSet\\Services` 的打开会命中回调；观测方式为比对操作前后的计数，"
     "而不是读值（读值不改计数）。"),
    ("r0-minifilter",
     "文件读写在内核的可见面是哪一层？",
     "minifilter 的 pre/post 回调（IRP_MJ_CREATE/READ/WRITE），可拿 FileObject、进程、偏移、长度。判据："
     "对同一文件做 1 次读，minifilter 的 READ 计数 +1；若文件被另一路径读到而计数不变，说明走了缓存或直接 IO。"),
    ("r0-section",
     "共享内存段（section）的创建与映射能看到吗？",
     "能，通过对象回调（ObRegisterCallbacks 对 Section 类型）或句柄表枚举。判据："
     "创建命名段后 `\\BaseNamedObjects` 下出现同名对象；两个进程的 `KM_PA` 对同一内容返回相同 PA 即共享页。"),
    ("r0-apc",
     "APC 注入在内核层的痕迹？",
     "线程 APC 队列与 KeInsertQueueApc 路径；用户态可见 `QueueUserAPC` 导入。判据："
     "目标线程的 `THREADS` 列表状态由 Wait 变 Runnning 且 RIP 落在非预期模块；内核侧对应 APC 计数 +1。"),
    ("r0-etw",
     "ETW 能覆盖到哪些内核事件？",
     "Microsoft-Windows-Kernel-Process（进程/线程）、Kernel-File（文件）、Kernel-Registry、Kernel-Network。判据："
     "`logman query providers | findstr Kernel-` 应列出这些 provider；未列出的说明系统版本裁剪过，"
     "对应事件不可依赖。"),
    ("r0-callback-enum",
     "怎么确认某个回调确实被注册了？",
     "枚举回调表（驱动侧）或看行为副作用。判据：注册后对目标类型对象的首次访问会走回调，"
     "表现为访问延迟增加（同一地址两次 `R` 间隔从 0.02 ms 升到 0.3 ms 量级）；"
     "单纯的读写结果不变不代表没回调。"),
    ("r0-handle-strip",
     "句柄权限被裁剪时会看到什么？",
     "ObRegisterCallbacks 的 post 回调可以改 AccessMask。判据："
     "`OPEN` 成功但 `R` 返回 `ERR|read-fail`，而 `KM_R` 正常 —— 说明句柄权限被降；"
     "此时 `kitty_prot action=query` 的返回仍是页属性，不反映句柄权限，别混。"),
    ("r0-thread-inject",
     "跨进程线程创建有哪些可见点？",
     "PsSetCreateThreadNotifyRoutine（线程创建）、句柄回调（THREAD_CREATE_THREAD 掩码）、镜像加载。判据："
     "目标 `THREADS` 数量增加而 `MODENUM` 无新增，说明是纯线程注入；若同时有新模块，先查模块来源。"),
    ("r0-driver-load",
     "驱动加载/卸载的痕迹怎么看？",
     "PsSetLoadImageNotifyRoutine 同样覆盖 .sys；另有注册表 Services 项。判据："
     "`kitty_drv action=status` 前后比对已加载服务列表，出现新项即加载；卸载后项消失但镜像可能仍在内存。"),
    ("r0-wfp",
     "网络连接在内核层能拿到什么？",
     "WFP 的 callout（FWPM_LAYER_ALE_AUTH_CONNECT）给 5 元组与进程 id。判据："
     "`kitty_net action=status` 探到抓包可用时，与 WFP 事件对时间戳；同一连接在两处 pid 应相同。"),
    ("r0-alpc",
     "ALPC 端口通信可见吗？",
     "对象回调覆盖 ALPC Port 类型；消息内容不在回调里。判据：端口创建后 `\\RPC Control` 或命名端口出现，"
     "可观测连接建立次数，但拿不到 payload —— 内容侧只能靠 ETW 或用户态 hook。"),
    ("r0-token",
     "令牌（token）相关访问的可见面？",
     "句柄回调对 Token 类型同样生效，AccessMask 含 TOKEN_ADJUST_PRIVILEGES 等。判据："
     "提权类操作前必有一次带 ADJUST 掩码的 open；可用回调计数 + `whoami /priv` 前后比对验证。"),
    ("r0-memory-probe",
     "内核能区分「普通读」和「探测读」吗？",
     "能看页错误与访问类型：探测读常落在未映射页，触发 PAGE_FAULT 后被吞。判据："
     "对同一地址连续 `R` 三次，前两次 `ERR|read-fail` 第三次成功 → 页在按需提交；"
     "全程成功但值不变 → 无探测特征。"),
    ("r0-hvci",
     "HVCI/内存完整性开着时，哪些观测会变？",
     "内核页的写与执行受限制，回调表本身被保护。判据：`msinfo32` 或注册表 `HVCI` 状态为开时，"
     "对内核地址的 `KM_W` 返回失败的概率显著升高；此时取证优先用 `KM_PR` 只读路径。"),
    ("r0-timing-side",
     "时序能不能作为可见面证据？",
     "能，但要成对比较。判据：同一地址 100 次 `R` 的均值 μ 与标准差 σ，与干净基线比；"
     "回调介入常表现为均值 +0.1~0.5 ms 且 σ 变大 2-3 倍。单次差异不作为证据。"),
    ("r0-obj-dir",
     "对象目录里能看出什么？",
     "`\\Device`、`\\BaseNamedObjects`、`\\KernelObjects` 下的命名对象是可见面。判据："
     "驱动创建的设备对象在 `\\Device\\<name>` 下可见，且符号链接（DOS 设备名）指向它；"
     "链接缺失时用户态 CreateFile 打不开该设备。"),
    ("r0-inventory",
     "做检测面清点的时候，清单应该包含哪几类？",
     "五类：句柄、进程/线程/镜像回调、注册表与文件回调、对象与端口、ETW/WFP。判据："
     "每类给出「可见字段 + 触发条件 + 验证命令」；缺任一类的清点表不能用于结论，"
     "因为不可见≠不存在。"),

    ("fm-exit",
     "目标进程退出导致读到 0，怎么避免误判成拦截？",
     "先确认存活：`CUR` 返回 pid 且 `LP` 里仍在；再 `R|<addr>|dword` 返回 `ERR|read-fail` 而不是 0。判据："
     "读到的是 ERR 还是 0 决定结论 —— ERR 记「未测」，0 才可能是改写；混淆这两者是最常见的假阳性。"),
    ("fm-guard",
     "页 guard 位导致的假分叉怎么排除？",
     "guard 页首次访问会成功并清位，第二次才正常。判据：`kitty_prot action=query` 报 PAGE_GUARD 时，"
     "连续三次 `R` 的结果应为「成功/成功/成功」，若第一次 ERR 第二次成功，是 guard 不是拦截；"
     "排除后重采样。"),
    ("fm-largepage",
     "大页下 PA 算错会怎样？",
     "会得到「物理读与虚拟读不一致」的假结论。判据：`KM_PA` 对同页内两个 VA 返回相同页基址时按 "
     "`pa | (va & 0x1FFFFF)` 修正；修正前不一致、修正后一致 → 前一次是算错，不是分叉。"),
    ("fm-cache",
     "CPU 缓存会导致读到旧值吗？",
     "同核同线程内不会，跨核可能看到时序差。判据：写入后立刻读（同一线程）应见新值；"
     "若跨线程读仍是旧值，加 `mfence` 语义的等待（sleep 1 ms）后重读，仍旧才判拦截。"),
    ("fm-testenv",
     "测试环境本身会不会制造差异？",
     "会：驱动版本、HVCI、杀软过滤、虚拟化嵌套都会改变读写路径。判据："
     "把 `kitty_drv action=status`、HVCI 状态、杀软服务列表三项记进基线；三项任一变化时，"
     "同一地址的历史结论不可直接复用。"),
    ("fm-driver-ver",
     "驱动版本不同会导致回包形态变化吗？",
     "会。判据：`PING` 返回的版本串（如 `OK|Kitty-bridge v0.2.9`）必须与预期一致；"
     "版本不同时 `KM_*` 的字段顺序可能变，按旧解析器读会得到错位值 —— 表现为「分叉」实则解析错。"),
    ("fm-type",
     "类型与长度不匹配会读到什么？",
     "dword 写、byte 读会得到低字节，看起来像「只写了一部分」。判据：写入 `0x11223344` 后按 byte 读应为 "
     "`0x44`（小端）；若 byte 读到 0，说明写入未落地，此时不能按 dword 回读结论判断。"),
    ("fm-aslr",
     "重启后地址变了，历史结论还能用吗？",
     "只有模块相对偏移可用。判据：`MODENUM` 取新基址，用 `新基址 + 旧偏移` 重算；"
     "若该处内容与历史不一致，先确认模块版本（`kitty_patch action=hash`）是否相同，再判差异。"),
    ("fm-read-cross-page",
     "跨页读会返回什么？",
     "第 N 页内读到页尾时可能越界。判据：`R|<addr>|bytes:16` 当 `(addr & 0xFFF) > 0xFF0` 时应报 "
     "`ERR|page-cross`；未报错而返回 16 字节，说明实现按映射区读，值可信但跨了页边界，结论要标注。"),
    ("fm-dump-lag",
     "转储出来的镜像与实时读不一致，孰对？",
     "实时读对当前状态，转储是快照。判据：`kitty_dump` 与 `R` 同时刻做，比对同一地址的 16 字节；"
     "不同说明期间有写入（看 `kitty_dump` 的耗时，> 5 s 时几乎必然有写）。"),
    ("fm-symbol-drift",
     "符号解析错位会造成什么假象？",
     "把函数名指到错误地址。判据：`kitty_sym action=resolve` 得到的 VA 必须落在该模块节范围内；"
     "越界说明 PDB 与镜像版本不符，此时所有按符号下的断点都不可信。"),
    ("fm-bp-limit",
     "断点数量上限导致的「没命中」怎么识别？",
     "硬件断点最多 4 个，软件断点受页保护限制。判据：`kitty_dbg action=bp_list` 返回条目数 = 设定数；"
     "若设定 6 个只回 4 个，说明后两个未生效，「没命中」不能作为「没执行」的证据。"),
    ("fm-attach-fail",
     "attach 失败时最容易出的错是什么？",
     "把「没附加」当成「行为不存在」。判据：`DBG_ATTACH` 返回 `ERR|debug-attach-unsupported` 或超时，"
     "此时 `DBG_REGS` 不应返回寄存器值；若仍返回值，说明读的是缓存/旧会话，结论作废。"),
    ("fm-time-skew",
     "时间戳不同源会怎样？",
     "三条证据的时间线会错序。判据：采集前用 `w32tm /query /status` 记偏移；"
     "偏移 > 100 ms 时，跨主机时间线只能给区间不给顺序。"),
    ("fm-proc-name",
     "同名进程多个实例，怎么确认测的是哪个？",
     "用 pid 不用名字。判据：`LP` 列出同名 pid ≥2 时，必须显式 `OPEN|<pid>`；"
     "仅用进程名时 `MODENUM` 返回的基址可能来自另一实例，表现为「地址对不上」。"),
    ("fm-sample-size",
     "采样多少次才敢下结论？",
     "分叉类 ≥3 轮，时序类 ≥100 次。判据：3 轮全一致才判一致；时序类给均值与 σ，"
     "差异需 > 3σ 才算显著。低于这两个数的结论一律标「未定」。"),
    ("fm-write-pollution",
     "回环写入污染了证据怎么补救？",
     "先还原再重采。判据：`restore_ok=false` 的页必须写进排除表，后续同类测试跳过；"
     "已污染的镜像不可用于「原始状态」结论，只能用于结构分析。"),
    ("fm-log-trunc",
     "日志被截断会掩盖什么？",
     "最常掩盖的是「前几轮都失败、最后一轮成功」。判据：`logs/anti-ace-*.jsonl` 行数应等于轮次数；"
     "行数少于预期时，先查写入异常（磁盘满/编码错），不许按残留行算成功率。"),
    ("fm-version-mix",
     "工具版本混用会怎样？",
     "回包字段与判据口径一起变。判据：每个 jsonl 行应含 `bridge_ver`；同一结论涉及多版本时，"
     "必须分段写明各自版本与结论，不能合并统计。"),
    ("fm-conclusion-scope",
     "哪些结论永远不能从单点采样推出？",
     "三类：「全局无拦截」（需覆盖多模块多页）、「谁改的」（需写断点/回调）、「何时改的」（需连续采样）。判据："
     "结论句里出现这三类断言而证据只有单点三视图，直接判为过度推断。"),
]

#!/usr/bin/env node
/**
 * gen_r32_r34.mjs — R32 七项系统条件 + R33 session-gate 判据函数 + R34 loop 站点命令序列
 *
 * 事实源（只读 DrCE）：
 *   README.md「让 KittyCE 满血运行的系统条件」七项表 + 一键到满血 + 三个必踩的坑 + 本机实测
 *   configs/reverse-hybrid/session-gate.mjs（949 行）的判据函数与 TASK_ONLY 清单
 *   kitty-toolbox/src/loop.ts 的站点序列与每站判据
 *
 * 内容用单引号字符串，内部反引号无需转义。
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r32-r34-ops.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (round, kind, user, assistant, meta) => out.push({
  id: 'kitty-' + round + '-' + kind + '-' + String(out.length).padStart(4, '0'),
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: Object.assign({ __stage: 're', __kind: kind, __round: round }, meta || {}),
});

// ===== R32 七项系统条件 =====
const R32 = [
  ['满血运行要满足哪七项',
    '七项条件，缺一项就掉半血：\n1) **CI 窗口开放**（OS ≤ Win11 23H2）\n2) **驱动阻止列表关闭**（VulnerableDriverBlocklistEnable=0x0）\n3) **VT 未被占用**（HypervisorPresent=False 且 VBS 未跑）\n4) **驱动进场顺序**（DrDriver 先于 CE）\n5) **宿主单实例**（恰好 1 个 KittyCE）\n6) **DBVM 开关**（Use DBVM Debugger=0x1）\n7) **干净 boot + 无第三方内核拦截**\n\n判据：七项逐个验，任何一项不满足都会表现成"驱动起不来"，但根因完全不同。'],
  ['第 1 项 CI 窗口怎么验',
    '查事件日志：\nGet-WinEvent -LogName Microsoft-Windows-CodeIntegrity/Operational\n\n看本 boot 的 Id ∈ {3023, 3077, 3099, 3085}：\n· **期望：3023=0、3077=0、3099=0**，只允许 3085（WHQL-ENFORCE-DISABLED）\n\n含义：3023/3077 出现 = 驱动被吊销拒绝；3099 = 策略刷新激活（会与加载时刻竞态）。\n\n判据：有 3023 或 3077 就是本 boot 不可达，别折腾驱动。'],
  ['第 2 项 blocklist 怎么改，为什么改完没用',
    '查：reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\CI\\Config" /v VulnerableDriverBlocklistEnable\n期望 0x0。\n\n两个必须记住的坑：\n· 改完**必须重启**\n· 本 boot 必须是 1→0 **之后的首个 boot**\n\n另外：这个值只管旧「易受攻击驱动阻止列表」，实际执行的是 WDAC 形态的 Driver Policy，走另一条通道。\n\n判据：设 0 后错误码不变 = 拦你的不是这个开关。'],
  ['第 3 项 VT 怎么算"没被占用"',
    '两条都要满足：\n· (Get-CimInstance Win32_ComputerSystem).HypervisorPresent = **False**\n· Win32_DeviceGuard.SecurityServicesRunning = **0**\n\n含义：Hyper-V / VBS / Credential Guard 全关。\n\n判据：HypervisorPresent=True 时 DBVM 起不来（硬件 VT 被别家 hypervisor 占了）。\n\n注意：HypervisorPresent=False 只是必要条件，不能拿它证明 DBVM 成功（DBVM 跑着也可能显示 False）。'],
  ['第 4 项驱动进场顺序怎么验',
    '看 kitty_init action=status 的 [L1] 两行：\n· aux 必须 RUNNING\n· mhtglyts 必须 RUNNING\n· 且 img=…\\Tools\\DrDriver.sys\n\n关键：**DrDriver 必须先于 CE 进场**。\n\n判据：顺序反了的表现是主驱恒 31，但看起来像"驱动坏了"。'],
  ['第 5 项为什么必须单实例',
    'Get-Process KittyCE 必须**恰好 1 个**。\n\n原因：同目录多开会抢桥文件（cmd.txt / reply）也会抢驱动句柄。\n\n实测反例：某次本机 3 个实例（4128/25064/32696）→ 满血前必须先收敛到 1。\n\n判据：kitty_status 里 instances=1。'],
  ['第 6 项 DBVM 开关的两个字段',
    '查：reg query "HKCU\\SOFTWARE\\Kitty Engine" /v "Use DBVM Debugger" → 期望 **0x1**（跨重启持久）。\n\n同时看 kitty_init action=status 的 [mode] 行：\n· imgIsVT=false ⇒ 还需要 KittyLoader(SVIP) 装 VT 映像后再 Start\n\n判据：开关=1 但 imgIsVT=false 是"未就绪"，不是"已开启"。'],
  ['第 7 项"干净 boot"具体指什么',
    '两条：\n· HiberbootEnabled = **0**（快速启动关闭，保证每次真冷启）\n· HKLM\\SYSTEM\\CurrentControlSet\\Services 下 360* / qhsafe / zhudong / huorong 为空\n\n原因：内核态 AV 会抢/拦 VT。\n\n判据：这两个都干净，才算"环境无干扰"。'],
  ['一键到满血的三步是什么',
    '1) **驱动层**：开机自愈任务\n   Get-ScheduledTaskInfo -TaskName KittyDrvBootHeal → LastTaskResult 期望 0\n   兜底：tools\\drv-boot-heal.ps1（blocklist 复核 → aux → DrDriver，早于 CE）\n2) **宿主层**：kitty_init action=init reload=true\n   链路：S0 关宿主释放句柄 → S2 重建 aux → S1 起 host → S3 main START → S5 dbvm-prep → OK|dbvm-ready\n3) **内核层**：只能在 CE 内验（服务返回码不算数）\n   LUA pcall(dbk_initialize) 期望 true\n   LUA pcall(dbvm_initialize) 期望 true\n\n判据：满血终态 dbk=true dbvm=true dbvmCR4=11874040 mem≈2.4M ept=true。'],
  ['为什么服务返回码不能当内核面判据',
    '因为 dbk64 只接受 CE 自己的加载器：\n· sc start dbk64 返回 31 是**正常表象**\n· 服务显示 STOPPED 但驱动可能在跑\n\n唯一真判据：CE 内 dbk_initialize / dbvm_initialize 的返回值。\n\n判据：dbvm-auto.ps1 -Stage Check 拿 31 当"本 boot 不可达"是**误报**。'],
  ['mhtglyts 已经 RUNNING 时还能调 dbk_initialize 吗',
    '不能。这是必踩坑之一：\n\nmhtglyts 已 RUNNING 时调 dbk_initialize → DriverEntry 失败 → CE 弹「DBK 错误」模态框 → Lua 线程阻塞 → 桥 PING 超时 → 看门狗连环重拉。\n\n正确顺序：**dbk64 先进，mhtglyts 后起**（tools\\dbvm-auto.ps1 源码注释同此）。\n\n判据：出现 DBK 模态框 + PING 超时 = 顺序错了。'],
  ['bcdedit 不存在怎么办',
    '本机实测 bcdedit.exe 在 System32 与 SysWOW64 **都不存在** → nointegritychecks 已无法查改。\n\n替代判据：改用 CI 事件（条件 1）+ blocklist 注册表（条件 2）。\n\n判据：不要因为查不到 bcdedit 就以为环境不完整 —— 判据换成上面两条即可。'],
  ['怎么快速判断"这台机器能不能跑满血"',
    '按七项过一遍，最省时间的顺序：\n1) OS build（< 26100）\n2) CI 事件（无 3023/3077）\n3) HypervisorPresent=False\n4) KittyCE 实例数=1\n5) 两个驱动 RUNNING 且映像对\n6) Use DBVM=1 且 imgIsVT 状态\n7) Hiberboot=0 + 无 AV 内核驱动\n\n判据：任一项不过就先修那一项，别急着调工具。'],
];
for (const x of R32) add('r32', 'fullblood', x[0], x[1], { topic: 'fullblood' });

// ===== R33 session-gate 判据函数 =====
const R33 = [
  ['session-gate 的核心设计是什么',
    '三条（源码注释原文）：\n· **待命态仅放行问询 + 锁定类**动作\n· 一切**跑数/写道动作须 TARGET 非空**\n· trail 须同 TARGET，**防串台**\n\n真相源 = configs/reverse-hybrid/sessions/<sessionKey>/{mode.json, target.json, trail.jsonl}；旧根四件降级为**广播镜像**，只读保留。\n\n判据：报错前缀 SESSION-/WIRE-SPLIT- 都属这一门。'],
  ['哪些动作被归为"必须 task 态"',
    'TASK_ONLY 正则清单（命中即要求 task 态）：\n· OPEN| / MODENUM\n· R| / W|（行首或分隔后）\n· S_NEW / S_SNAP / S_CHANGED / S_UNCHANGED / S_GET\n· P_BACK / P_WALK\n· ALLOC\n· kitty_（任何 kitty_ 工具）\n· trail-append\n· DBG_ / KM_ / SYNC_ARCHIVE\n\n判据：待命态发这些一律被拦，先 target-set 转任务态。'],
  ['trail 的"同串判据"怎么比',
    '不再对 JSON 转义文本做子串比较。规则：\n· **结构化声明优先全等**\n· 否则反转义后比\n· 归一化 = 反斜杠→正斜杠 + 折叠重复斜杠 + trim\n\n为什么改：之前用子串比，路径里恰好包含目标名就会误判"同 target"。\n\n判据：trail 记录 target 字段与当前 TARGET 归一后必须一致。'],
  ['WIRE-SPLIT 是什么，为什么要 DENY',
    '含义：用**自己的键继续写**，会分裂出一个**不可见分片** —— 工作台看不到那份数据。\n\n处置：调用方必须 **DENY + refresh 重解父链**，不能"接着写下去"。\n\n判据：`ERR|WIRE-SPLIT-DENY:<原因>；<refresh 提示>`。'],
  ['为什么缺键一定要 DENY 不能回落',
    '因为回落 default 会导致多会话互相污染：A 会话的任务态写进 B 会话。\n\n新口径：缺键一律 `ERR|SESSION-KEY-MISSING`，调用方须显式传 session。\n\n历史注记：shardPaths 的 default 回落**仅保留作路径兼容计算**（定位旧数据），门判据永不采用。\n\n判据：readShard 系 / checkSessionAction 都先过 requireSessionKey。'],
  ['sessionKey 怎么规范化',
    'sanitizeSessionKey：\n· 归一化路径分隔符与大小写敏感度\n· 保证键能安全映射到目录名\n\n判据：同一个会话不同写法（大小写、斜杠方向）应得同一个分片目录。'],
  ['hostId 是干什么的',
    '用于跨机识别：hostIdParts() 拆出机器标识，hostId() 生成当前机 id，hostMatches(stored) 比对已存值。\n\n用途：会话状态件跨机拷贝时判断"这是不是本机的状态" → 不是就 DENY（HOST-MISMATCH-DENY）。\n\n判据：旧件无 host 归属时也按"非本机"处理并提示 host-rebind。'],
  ['legacy 的旧 trail 怎么处理',
    '两条规则：\n· `LEGACY_TRAIL_REL` = configs/reverse-hybrid/agent-trail.jsonl（旧全局件）\n· t8 标记：旧 trail 里**无 session 的行不是"公共历史"，而是"迁移前历史"** —— 迁移时显式归 legacy\n\n还有 backfillLegacyTrail：就地补齐已存在的分片 trail（**幂等**，无改动不落盘）。\n\n判据：迁移不能把旧行当成本会话的记录。'],
  ['ascendToRoot 的根判据是什么',
    '深度定义：子 depth = 父 depth + 1，**根 depth = 0**。\n\nascendToRoot(self, parentOf, maxDepth=16)：沿父链上溯，到 depth=0 即根；maxDepth 防环。\n\n判据：上溯步数（steps）等于自身 delegationDepth 时就是根。'],
  ['classifyTrailRow 用来分什么',
    '按行里的 session 字段分流：有键 → 归属该会话分片；无键 → 归 legacy（迁移前历史）。\n\n用途：迁移与读取时决定这一行进哪个视图。\n\n判据：分错的后果是该行在某个会话下"消失"或串到别人那边。'],
  ['sanitizeWireHeader 防什么',
    '防止父链头被伪造/污染：清理请求里的 wire header（父会话信息），避免子会话把数据写到错误的分片。\n\n判据：parent-header-unresolved 就来自这里 → DENY 并提示 refresh。'],
  ['待命态到底还能做什么',
    '只放行：\n· 问询类（status / get 类）\n· 锁定类（target-set / mode-set / host-rebind）\n\n不能做：任何跑数、读写、扫描、反查、调试、trail-append。\n\n判据：需要动手就先 target-set 转 task 态，别在待命态硬试。'],
  ['target 空但我在做只读检查，会被拦吗',
    '看你做的是哪类动作：\n· 纯状态查询（kitty_status status / drv status）→ 放行\n· 带 kitty_ 前缀的工具调用 → 属 TASK_ONLY，被拦\n\n判据：只读也要看具体动作名是否命中 TASK_ONLY 清单。'],
  ['分片目录结构长什么样',
    'configs/reverse-hybrid/sessions/<sessionKey>/：\n· mode.json —— 模式\n· target.json —— 双字段（sessionGoal / targetProcess）\n· trail.jsonl —— 本会话轨迹\n\n旧全局件（session-mode.json / target-state.json / last-target.json / agent-trail.jsonl）降级为**广播镜像**，只读。\n\n判据：判据链只读分片，镜像只用于展示。'],
  ['为什么 trail 要按会话分片',
    '防串台：多会话并行时，全局 trail 会把 A 的步骤混进 B 的轨迹，复盘时无法区分。\n\n分片后：每会话一条独立轨迹，回溯时按 sessionKey 取。\n\n判据：trail-get 按目标/会话过滤时能看到干净序列。'],
];
for (const x of R33) add('r33', 'session', x[0], x[1], { topic: 'session' });

// ===== R34 loop 站点命令序列 =====
const R34 = [
  ['夜跑第一站 channel 做什么',
    '**排空通道**：发 PING 看能否在预算内回。\n\n· 回 → `PING ok after <ms>`，green，note=「排空完成：超时指令已出队」\n· 不回 → `PING fail within <budget>`，red，note=「通道仍脏：宿主忙/模态阻塞」\n\n判据：不排空就往下跑，第一批指令会顶到超时残留上。'],
  ['preflight 站查哪四样',
    '四行检查：\n1) \`bcdedit /enum\`（只读）→ testsigning 必须 **No**（否则 red，红线）\n2) \`sc query mhtglyts\` → RUNNING 为 green，否则 warn（红线：只 START/STATUS，禁 STOP）\n3) \`sc query Kitty_Dr_Private_Access\` → RUNNING 为 green，否则 warn\n4) channel dir 是否存在 → exists / missing\n\n判据：testsigning 不是 No 会直接判红，这轮不该跑。'],
  ['host 站的完整序列',
    '1) **enumerate** 枚举宿主进程（pid / responding / owned）\n2) 无宿主 → `BLOCKED: host-not-ready`\n3) 默认 `lifecycle=external`：**只读使用现有单实例，不启不停**（--host-lifecycle 才许自管）\n4) PING 判桥活性\n5) 宿主在但桥不响应（GUI 模态/未载 autorun）→ recover：kill stuck 后重启宿主\n6) 自启路径：清旧宿主 → start hostExe → `PING after boot try#N`\n7) BRIDGE_VER 取契约版本（T1 冻结 v0.2.1 异步扫描）\n8) host binding：`pid=…(own|foreign) bridge=…`\n9) 打会话戳 `host:<pid>`（G2 依据）\n\n判据：每步 verdict 都要 green 才继续。'],
  ['target 站的序列',
    '1) **reuse**：有现成目标且 age 在窗口内 → 直接复用\n2) age 太长 → `restart stale target`（recover）\n3) 无目标 → `start <targetExe>`，再 `settle` 确认沉降（本地进程表，**不走桥**）\n4) `CUR` 核对当前 pid\n5) 切换：**先按名 `OPEN|<proc>`**（避开陈旧 pid 句柄），失败再按 pid `OPEN|<pid>`\n6) `CUR` 复核 → `target ready`\n7) `MODBASE|<模块>` —— 注释写明「ASLR 动态解析，跨实例作废，禁硬编码」\n8) `MODENUM|<pid>` 拿模块范围\n\n判据：CUR 的 pid 与期望不一致 = 没切成功。'],
  ['s1-intake 站记什么',
    '指纹一行：\n\`sha=<16位> size=<字节> mods=<模块数> host=<pid> target=<pid> bridge=<版本>\`\n\n用途：这一轮的"起点快照"，后面出问题时用来确认环境没变（G2 跨会话稳定的依据之一）。\n\n判据：sha 取不到不拦轮，但要留 note。'],
  ['s2-triage 站判什么',
    '路由判据：\n\`route=<结论>（self=<自身模块 地址/大小> k32=<kernel32 基址>）\`\n\n它决定这轮走哪条分析线（自身模块 vs 系统模块）。\n\n判据：kernel32 基址拿不到说明模块枚举有问题。'],
  ['s3-static 站做什么',
    '批量静态：\`<模块数>模块 <清单> | MODBASE一致=<bool>\`\n\n关键判据是 **MODBASE 一致性**：多个模块的基址关系是否自洽。\n\n判据：MODBASE一致=false 说明模块布局异常（可能被改过或读错）。'],
  ['sig 站（稳定特征）取什么',
    '\`base / mz / lfanew / k32mz\` 四元组，标注为「session A 稳定特征」。\n\n用途：跨会话比对同一目标是否还是同一个映像（G2 判据的输入）。\n\n判据：mz / lfanew 异常 = 读到了非 PE 区域或地址错。'],
  ['scan 站的三步',
    '1) **ALLOC parse**：分配一块可写内存，裸 hex 回包按 hex 解析，**40 位地址不许截断**\n2) **W canary**：往槽位播种，命中数阈值 **≥ minHits** 才 green\n3) **S_NEW job**：异步作业（v0.2.1），记 jobId 与 jobStat\n\n判据：播种命中数不足 minHits 直接判红 —— 说明写入没生效。'],
  ['为什么 ALLOC 的地址解析要特别小心',
    '因为回包是**裸 hex**，且地址可达 40 位。\n\n坑：\n· 用 parseInt 默认转 number 会丢精度（超过 2^53）\n· 截断到 32 位会算错地址\n\n正确做法：按 hex 字符串解析，保留完整位宽。\n\n判据：地址看起来像 0x7FF6xxxx 但实际应有 40 位 = 被截断了。'],
  ['gate 站在什么时候判红',
    '三阈值任一红 → verdict=blocked：\n· G1 命中数不足\n· G2 跨会话不稳定\n· G3 内核证据缺失（未显式跳过却无回包）\n\n判据：\`abort:<reason>\` 会写进日志并落 blocker 文件。'],
  ['teardown 站收什么尾',
    '清理本轮临时状态、归档同步队列、把 gate 结果与证据落盘。\n\n判据：teardown 后 SYNC 类计数应归零；不归零说明还有残留指令在队列里。'],
  ['loop 的日志格式是什么',
    'logs/loop-<ts>.jsonl，每步一行：\n\`{ts, round, session, stage, cmd, reply, verdict, ms, note}\`\n\n判据：排查时按 stage 过滤，看 verdict=red 的那一步的 cmd 与 reply。'],
  ['一只手的站点顺序能简化吗',
    '不能随意简化，因为存在硬依赖：\n· channel 排空 → 否则首批指令撞残留\n· preflight → 否则红线状态下白跑\n· host → 否则没有通道\n· target → 否则没有对象\n· s1 指纹 → 否则事后无法判断环境是否变过\n\n判据：每站都能说出"跳过它会怎样"。'],
  ['宿主掉线时 loop 怎么自愈',
    '分三种：\n· 桥不响应（GUI 模态/未载 autorun）→ kill stuck + 重启宿主\n· 宿主不存在 → start hostExe 重试（boot try#N）\n· 多宿主并存 → 判红停跑（回包串台，不采信脏数据）\n\n判据：看日志里是 recover 还是 contention，处置完全不同。'],
];
for (const x of R34) add('r34', 'loop', x[0], x[1], { topic: 'loop' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byRound = out.reduce((a, x) => (a[x.meta.__round] = (a[x.meta.__round] || 0) + 1, a), {});
const chars = out.reduce((s, x) => s + JSON.stringify(x.messages).length, 0);
console.log(JSON.stringify({ out: OUT, samples: out.length, by_round: byRound, avg_chars: Math.round(chars / out.length) }, null, 1));

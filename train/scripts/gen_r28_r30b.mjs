#!/usr/bin/env node
/**
 * gen_r28_r30b.mjs — R28 DBVM 坑表 + R29 六门判据 + R30 夜跑闸门
 *
 * 事实源（只读 DrCE）：
 *   README.md 的 DBVM 归零坑表 + 驱动加载失败原因总表
 *   configs/reverse-hybrid/{ask,session,target,ops,dual-agent}-gate.mjs 的判据分支
 *   kitty-toolbox/src/loop.ts 的三阈值 gate / Cell 状态 / verdict 计算 / 通道排空 / 熔断
 *
 * 内容全部用单引号字符串：内部反引号无需转义，避免模板字符串被内嵌反引号截断。
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r28-r30-gates.jsonl';
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

const R28 = [
  ['DBVM 起不来，是不是配置问题',
    '先看**系统版本** —— 这是最硬的墙。\n\n仅 Windows 11 **23H2（build 22631）及以下**可用。24H2（26100+）/ 25H2 / 26H2（26300）实测不可用：\n· VT 主驱 Kitty_Dr_D_VT.sys 在 26H2 **DriverEntry 失败（SC 31）**\n· dbk64.sys 绕签名后仍然 31\n\n而且：关黑名单 / testsigning / 重签 / 换服务名 / 调顺序 **全部绕不过**，唯一解法是退回 23H2。\n\n判据：错误码 31 + 系统 build 在 26100 以上 = 版本墙，不是配置问题。'],
  ['DBVM 没起来但我发了 LUA，为什么整条链路像挂了',
    '因为触发了已知的**卡死链**：\n\nDBVM 未初始化就调 dbvm_getCR4 / getMemory / ept_reset → **Access Violation 卡死 Lua 线程** → cmd.txt 不再被消费 → 桥 PING 超时 + 看门狗连环重拉。\n\n表象非常像「驱动全挂」，但根因是一条不该发的 LUA。\n\n正确做法：DBVM 未确认就绪前，不要发任何 LUA 或 DBVM 相关 OP。\n\n判据：PING 全超时但驱动 SCM 状态正常 = 优先怀疑 Lua 线程卡死。'],
  ['怎么确认 DBVM 真的起起来了',
    '**旧判据已作废**：HypervisorPresent = True 不能当标准 —— 2026-10-26 实测推翻：DBVM 已在跑（关于框显示 DBVM 19）时该项仍为 **False**。\n\n正确判据：CE「帮助 → 关于」底部显示 DBVM 版本 19 与 bytes free / pages 信息。\n\n判据：这是**最终人读确认**，没有更可靠的程序化替代。'],
  ['DBVM 该由谁拉起',
    '硬规定：**只能由操作者通过 CE 拉起**。\n\n不要让 agent 自己触发 DBVM 启动 —— 初始化路径上有很多竞态，机器人操作会放大风险。\n\n判据：agent 只做「确认状态」，不做「启动动作」。'],
  ['DBVM 对运行环境有什么要求',
    '· 裸机（物理 VT-x / EPT）\n· x64\n· VM 内嵌套虚拟化**不保证**可用\n· HypervisorPresent=False 只是「没别家 hypervisor 占着」的必要条件，不是 DBVM 成功的判据\n\n判据：跑在虚拟机里就别指望 DBVM，走 kernel 模式的 KM 面。'],
  ['360 之类的安全软件会影响 DBVM 吗',
    '会。第三方内核残留是偶发失败的主要环境放大项：\n· 360AntiHijack（StartMode=System、**不可停**）会抢 VT / 参与监控\n· 必须**重启后物理删除**，热卸载无效\n\n其他放大项：异构 CPU（P/E/LP-E 混核）、深度 C-state、Modern Standby、内存混插。\n\n判据：环境干净时同样配置能起，装了安全软件就起不来 = 这类干扰。'],
  ['三视图里物理读是 ERR、pa=n/a 说明什么',
    '说明 **KM_PA 不可用**（没启 DBVM / VT 内核面），是**能力降级**，不是反作弊拦截。\n\n区分很重要：\n· 能力降级 → 换 kernel 模式或补内核面\n· 拦截 → 三路值不一致（分叉）\n\n判据：pa=n/a 但 R 与 KM_R 一致 = 只是少了一路视图，不是被拦。'],
  ['偶发分叉=1 要不要当拦截上报',
    '不一定。HP 上偶发分叉=1（比如 79 vs 78）常见原因是**两次采样跨了 tick**，值本来就在变。\n\n正确做法：同一时刻取 NAME / 多字段对照；多轮采样看是否稳定分叉。\n\n判据：同一时刻 NAME 分叉=0 → 说明是时序不是拦截。单轮样本不能定性。'],
  ['Use DBVM Debugger=0x1 但 imgIsVT=false 什么意思',
    '开关打开了，但**当前跑的主驱映像不是 VT 版**。\n\n处置：需要 KittyLoader（SVIP）装 VT 映像后再 Start。\n\n判据：kitty_init action=status 的 [mode] 行要同时看 Use DBVM Debugger 与 imgIsVT —— 两个都要对。'],
  ['DBVM 失败后反复重启机器有救吗',
    '版本墙的情况下没有。26H2 上实测 SC 31 绕不过任何配置手段。\n\n唯一解法：退回 Windows 11 23H2（build 22631）。\n\n判据：同一份 Kitty_Dr_D_VT.sys 在 23H2 上直接 RUNNING、DBVM v19 可用 —— 这就是仓库把 OS 上限定在 23H2 的由来。'],
  ['DBVM 相关证据该落哪',
    '本地日志（不入库）：\n· logs/syslimit-audit-<date>.md —— 系统层面审计\n· logs/dbvm-final-<date>.md —— DBVM 终态\n· logs/drv-load-failure-digest-<date>.md —— 驱动加载失败总表\n· logs/drv-reload-feature-<date>.md —— 刷新链\n\n判据：交付 DBVM 结论必须引这些文件，不能只写「试过了」。'],
  ['DBVM 模式下还能不能用 KM 面',
    '能，但**退化**：\n· mode=kernel（默认）—— KM 面完整\n· mode=dbvm —— DBVM 优先，KM 面退化\n\n判据：要做 R vs KM_R vs KM_PR 三视图对照时选 kernel 模式；要用 DBVM 的 EPT/CR4 能力时用 dbvm 模式，但别指望三视图完整。'],
];
for (const x of R28) add('r28', 'dbvm', x[0], x[1], { topic: 'dbvm' });

const R29 = [
  ['工作台的六道门分别管什么',
    '六门在 configs/reverse-hybrid/：\n· platform-gate —— 平台/环境准入\n· ask-gate —— 提问申请单绑定（会话键 + 目标）\n· session-gate —— 会话键与分片归属\n· target-gate —— 双字段（sessionGoal / targetProcess）绑定\n· ops-gate —— 操作序列合法性（区间/窗口/十进制偏移/成功判据）\n· dual-agent-gate —— 调查只读与硬禁清单\n\n判据：报错前缀就是门名，按前缀找对应 gate 文件。'],
  ['ask 时要带什么，缺了报什么',
    '两个都要绑：\n· 缺 sessionKey → ERR|ASK-NO-SESSION-KEY（不回落 default）\n· 缺 TARGET → ERR|ASK-NO-TARGET\n\n为什么：旧口径只验 questions 形状，不验会话归属 → 跨会话 ask 会混用。\n\n判据：ask 前先 target-get 确认两栏都在。'],
  ['手填 sessionKey 直接锁会话行不行',
    '不行。手填键/目标 → ERR|MANUAL-KEY-NEEDS-ASK。\n\n规则：手填严禁裸直锁，必须走 ask 选择题申请单（缺任一项都拒，不回落 default、不放行裸键）。\n\n判据：正确路径是 ask 申请单 → 拿到键 → 再用。'],
  ['session-gate 的 default 回落还能用吗',
    '不能用于判据。\n\n· 缺键一律 DENY：ERR|SESSION-KEY-MISSING\n· shardPaths 里的 default **只保留作路径兼容计算**（定位旧数据）\n· 门判据**永不采用** default 回落\n\n判据：调用方必须显式传 session，别指望默认值。'],
  ['target-gate 到底认哪个文件',
    '**只认分片**：configs/reverse-hybrid/sessions/<sessionKey>/target.json（与插件侧 readShardTarget 同源同口径）。\n\n旧文件 target-state.json / last-target.json **不再作判据**，它们的值只进 mirror 展示字段。\n\n坑：改旧文件以为生效了 —— 判据根本不读它。\n\n判据：新键无分片 = 未锁定（空 TARGET）。'],
  ['进程类动作和目标类动作绑的字段不一样？',
    '对，这是最容易搞混的一条：\n· **进程类动作**（OPEN / 扫描 / 读写 / 指针 / 对抗 / 转储）→ 必须绑 targetProcess\n· **目标类动作**（triage / 交接 / 报告 / trail）→ 必须绑 sessionGoal\n\n坑：把会话目标当进程名用 —— 工具会拿一段自然语言去 OPEN，必然失败且报错不直观。\n\n判据：target-get 里两个字段非空且不相等。'],
  ['ops-gate 要求「成功判据」是什么意思',
    '提交的操作序列里必须含判据词之一：**判据 / 验收 / RecoveredOutput / acescan green**。\n\n缺了就报「缺成功判据」。\n\n为什么：防止「发了指令但不知道算不算成」的裸操作进流水。\n\n判据：每一步后面都写清「凭什么判这一步成了」。'],
  ['ops-gate 对扫描窗口的具体判据',
    '· S_NEW / S_SNAP 必须给起止两个地址（缺 → 须显式区间）\n· span 必须 > 0 且 ≤ 0x1000000（16MB），超了报「窗口超限」\n· P_BACK 必须给目标 + 起止（三段）\n\n判据：这些是门层就拦的，不用等桥回 need-range。'],
  ['ops-gate 会拦 P_WALK 的 0x0 吗',
    '会，而且是**门层直接拒**：P_WALK 出现 0x0 → 「P_WALK须十进制0（禁0x0）」。\n\n原因：桥侧 Lua 对 0x0 会触发 format-nil。\n\n判据：写 |0 不写 |0x0。'],
  ['dual-agent-gate 的硬禁清单',
    '· HARD-BAN:KM_PW/DBG_ATTACH永不碰 —— 直接拒，没有参数能放行\n· INV-DENY —— 调查子会话**只读**：写 / 回环 / 真调试 / target-set 一律禁\n· empty-action —— 空动作拒\n\n判据：子会话要做写操作，必须走 EXECUTE-HANDOFF 交给限域执行。'],
  ['六门跑一遍怎么算正常',
    '跑 verify-reverse-gates.mjs：platform 12/12 · ask 13/13 · ops 12/12 · dual 11/11 · shield 20/20；**session 11/14 与 target 11/14 各 exit 1 是设计**。\n\n判据：其他门全绿 + 这两门按预期红 = 正常（它们需要真实会话态）。'],
  ['门禁红了能不能带病继续',
    '不能。红 = 停手出证据。\n\n规则：gate=green 且写回环全通 = 无拦截面；仍红 → 停手出证据，不硬闯。\n\n判据：红的项要落进证据文件，而不是重置后重跑。'],
  ['为什么门禁这么严（多层拒绝）',
    '因为工作台会碰宿主/驱动/内核面，一次误操作代价是整机重启。\n\n分层设计：\n1) 门层（ops/target/session）拦「明显不合法」的调用\n2) 桥层拦「参数/状态不对」的 OP\n3) 执行层拦「缺必填/缺确认」的调用\n\n判据：报错前缀能告诉你被哪一层拦的 —— 层不同，修法不同。'],
  ['target-gate 的 mirror 字段有什么用',
    'mirror 是**展示用**：把旧全局件（target-state.json / last-target.json）的值带出来给人看，方便对照。\n\n但它们**永不参与判据** —— 判据只看分片。\n\n坑：看到 mirror 里有值就以为已锁定 —— 实际可能是空的。\n\n判据：以分片是否存在为准。'],
  ['report 阶段还会过门吗',
    '会。报告属「目标类动作」，绑 sessionGoal；同时 ops-gate 要求序列含成功判据。\n\n判据：报告前的最后一轮操作里必须有明确的「判据」表述，否则门层会拦。'],
];
for (const x of R29) add('r29', 'gate', x[0], x[1], { topic: 'gate' });

const R30 = [
  ['夜跑一轮的流水是什么',
    '八站：收案 → 分诊 → 静态 → 定位 → 对抗 → 还原 → 修改 → 回归。\n\n末尾走 gate（三阈值）判定，红则 R3 降级 + 挂起并写 logs/blocker-<ts>.md，最后 teardown。\n\n日志：logs/loop-<ts>.jsonl，每步一行 {ts,round,session,stage,cmd,reply,verdict,ms,note}。\n\n判据：跑完看 gate verdict（green / degraded / blocked）。'],
  ['三阈值 gate 具体判什么',
    '三道：\n· **G1 命中数** —— hitsThisRound ≥ minHits 且回读抽样一致\n· **G2 跨会话稳定** —— 重启后还能复现（restartStable）\n· **G3 句柄不可见** —— 内核态路径已载入（kmStatus=loaded）则成立\n\nverdict 计算：reds 非空 → **blocked**；有 pending 类 → **degraded**；否则 **green**。\n\n判据：reds 里会写明是哪一条红（G1:命中数 / G2:跨会话稳定 / G3:句柄不可见）。'],
  ['G3 在什么情况下算红',
    '「KM 证据缺失（未显式跳过却无回包）」→ 红。\n\n两种情况要区分：\n· 显式跳过（kmSkipped）→ 不算红\n· 没跳过但拿不到 KM 回包 → 红\n\n判据：G3 红说明内核面本该有证据却没有，不是「没测」。'],
  ['manual_confirm 是什么状态',
    'Cell 的六态之一：green / red / na / pending / manual_confirm / skipped。\n\nmanual_confirm = 私有驱动场景的**人工确认位**：不判红、不拦放行，但会在 gate 与 pattern 里显式留痕。\n\n判据：它不改变 verdict，但报告里必须能看到这一项待人工确认。'],
  ['夜跑开始前要「排空」通道，怎么判',
    '发 PING 看能不能在预算内回：\n· 回 → PING ok after <ms>，green，note=「排空完成：超时指令已出队」\n· 不回 → PING fail within <budget>，**red**，note=「通道仍脏：宿主忙/模态阻塞」\n\n判据：通道没排空就跑，第一批指令会顶到超时残留上。'],
  ['指令超时后夜跑怎么自愈',
    '两层：\n1) **原子重投** —— 超时后重投一次（撕裂读自愈），日志记「重投 N」，verdict=warn\n2) **熔断** —— 连续 TIMEOUT 达阈值就 trip，记「熔断 trip xN」，red，停跑自愈\n\n判据：看到 trip 说明不是单次抖动，要先修环境再跑。'],
  ['中途出现两个宿主会怎样',
    '直接判红并**停跑**：contention@<where> 显示 N 宿主并存 → 回包串台，立即停跑（不采信脏数据）。\n\n为什么：桥靠文件通信，多宿主会抢 cmd/reply，回包来源不确定。\n\n判据：日志里有 contention 就是这条，先清成单实例。'],
  ['失败注入怎么复现红分支',
    'force_red 参数可取：hits / stability / handle / wedge。\n\n· hits → 压低命中数触发 G1\n· stability → 破坏跨会话稳定触发 G2\n· handle → 制造句柄可见触发 G3\n· wedge → 模拟桥楔死（不发通道，直接造 TIMEOUT）\n\n判据：注入时日志会写「故障注入 …（未发通道）」，用来验证红分支处置是否真执行。'],
  ['收案站（S1）怎么指纹',
    '本地文件 SHA-256 + size（同步计算，等价于 kitty_patch 的 hash 面）。\n\n关键：失败返回 null **不拦轮** —— 指纹算不出来不该阻断整轮。\n\n判据：日志里 s1 指纹为空但有 note = 文件不可读，不是流程失败。'],
  ['夜跑挂了要看哪个文件',
    '按顺序：\n1) logs/loop-<ts>.jsonl —— 每步 cmd/reply/verdict，定位红在哪一站\n2) logs/blocker-<ts>.md —— 红分支挂起时写的处置说明\n3) patterns/*.json —— 命中特征，用于下一轮\n\n判据：verdict=blocked 的步所在 stage 就是断点。'],
  ['夜跑和手工单步的取舍',
    '· 夜跑：标准流程、可复现、出证据 —— 适合已知目标类型的批处理\n· 手工：探索期、要看中间结果决定分支 —— 适合新目标\n\n坑：新目标直接夜跑 —— 出红只知「红」，不知前提哪步没满足。\n\n判据：手工能说清每步为什么，再交给夜跑固化。'],
  ['Cell 的六态分别什么时候出现',
    '· green —— 该项通过\n· red —— 该项失败（进 reds）\n· na —— 该项本轮不适用\n· pending —— 还需要后续步骤才能判\n· manual_confirm —— 私有驱动场景人工确认位\n· skipped —— 显式跳过（如 kmSkipped）\n\n判据：skipped 与 na 都不判红，但含义不同：skipped 是「我决定不测」，na 是「这项不适合测」。'],
  ['R3 降级是什么',
    '红分支的处置动作：**降级 + 挂起**，并写 logs/blocker-<ts>.md 记录阻塞原因。\n\n含义：不再自动往下试（避免刷检测），把当前状态固化成交接材料。\n\n判据：看到 blocker 文件就说明这一轮是人工接手，不是继续自动跑。'],
  ['teardown 阶段要做什么',
    '收尾：清理本轮产生的临时状态、归档同步队列、把 gate 结果与证据落盘。\n\n判据：teardown 后 SYNC 类计数应归零；不归零说明还有残留指令。'],
];
for (const x of R30) add('r30', 'loop', x[0], x[1], { topic: 'loop' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byRound = out.reduce((a, x) => (a[x.meta.__round] = (a[x.meta.__round] || 0) + 1, a), {});
const chars = out.reduce((s, x) => s + JSON.stringify(x.messages).length, 0);
console.log(JSON.stringify({ out: OUT, samples: out.length, by_round: byRound, avg_chars: Math.round(chars / out.length) }, null, 1));

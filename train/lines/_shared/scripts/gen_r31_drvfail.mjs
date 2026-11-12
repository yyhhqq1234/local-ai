#!/usr/bin/env node
/**
 * gen_r31_drvfail.mjs — 驱动加载失败 13 项 + 误判三件套 + platform 硬门
 *
 * 事实源（只读 DrCE）：
 *   README.md「驱动加载失败原因总表」13 项 + 「误判三件套」
 *   configs/reverse-hybrid/platform-gate.mjs 的 HARD_ALWAYS / PLAT_NAME+PLAT_VERB / SHELVED
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r31-drvfail.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (kind, user, assistant, meta) => out.push({
  id: 'kitty-r31-' + kind + '-' + String(out.length).padStart(4, '0'),
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: Object.assign({ __stage: 're', __kind: kind, __round: 'r31' }, meta || {}),
});

const DRV = [
  ['sc start dbk64 报 0x800B010C CERT_E_REVOKED',
    '这是**CI 驱动策略吊销**，不是没装驱动。\n\n链：Microsoft Windows Driver Policy（id 10.0.25873.0）判定 CE 的 dbk64.sys 已被微软吊销 → CI 事件 3023 + 3077 拒绝加载。\n\n表现：sc start → 0x800B010C；CE 弹「DBK 初始化失败」。\n\n判据：事件日志里有 3023/3077 + 错误码 0x800B010C，就锁定这一项。重装驱动无效。'],
  ['同一个驱动操作，上午成功下午失败',
    '这是**策略激活竞态**。\n\n机制：3099（策略刷新激活）每次 boot 出现的时机不定 —— 早于驱动加载 → 本 boot 必失败；没出现 → 放行。\n\n判据：同一操作不同时刻结果不同，且事件日志里 3099 的时间戳与加载时刻的相对位置能解释它。\n\n处置：不能靠"再试一次"，要按 boot 的时序判断。'],
  ['把 VulnerableDriverBlocklistEnable 设成 0 为什么没用',
    '因为那个值只管**旧的**「易受攻击驱动阻止列表」。\n\n实际执行的是 **WDAC 形态**的 Driver Policy，走的是另一条通道。\n\n判据：设成 0 后错误码不变（还是 0xCERT 类或 31），就说明拦你的不是 blocklist。'],
  ['驱动签名显示 UnknownError，加载时好时坏',
    '这是**签名链已死**：自研驱动签名 Subject 是上海明盛网络，**2015-12-06 过期近 11 年、无 Authenticode 时间戳**。\n\n后果：KMCS 验证不可信，能否加载取决于 CRL / 策略缓存窗口。\n\n判据：Get-AuthenticodeSignature 回 UnknownError + 证书过期且无时间戳 = 这条。\n\n注意：这解释了"时好时坏"，不是随机故障。'],
  ['报 577 或 0x800B0109 CERT_E_UNTRUSTEDROOT',
    '两种不同原因：\n· **577** = cannot verify digital signature（剥签名后无 audit 放行）\n· **0x800B0109** = CERT_E_UNTRUSTEDROOT（自签证书没进 Root / TrustedPublisher）\n\n判据：先看证书链是否完整，再看信任根是否装了。补信任根能解 0109，解不了 577。'],
  ['主驱恒 31，路径/服务名/宿主状态都查过了',
    '查 **mhtglyts qc 指向的映像**。\n\n已知坑：binPath 被写成 Kitty_Dr_D_VT.sys 时，.Kitty0/1/2 壳在 **DriverEntry 做调用上下文自校验** → SCM 上下文必然失败。\n\n关键特征：与路径括号/服务名/宿主状态**全都无关**，6 份同 hash 的映像全报 31。\n\n判据：qc 的映像名不对 + 换什么都 31 = 这一项。'],
  ['重启后双驱全起不来（ERR 2 / 31）',
    '可能是 **qc 指向的文件已不存在**：服务 qc 跨重启保留，但驱动目录树曾被清空 → 映像缺失。\n\n判据：查 qc 的 binPath 指向的文件是否存在；不存在就是 ERR 2 / 31。\n\n处置：恢复映像文件到原路径，或重建服务。'],
  ['宿主 DOWN 时 sc start 主驱恒 31',
    '这是**进场顺序错**。\n\n事实：主驱与 VT 面由 CE/宿主侧带起。\n\n正解：**host-first** —— 先起宿主，且用开机任务让 aux/DrDriver 早于 CE 进内核。\n\n判据：宿主先起再 start 主驱能成，反过来必 31。'],
  ['当前正常，一重启就挂',
    '这是 **CE 反向改写 qc**：CE 内 dbk_initialize() 自带一次装驱动动作 —— 把 mhtglyts qc 改成 VT 映像再 StartService → 31 → 返回 false。\n\n证据：服务键 LastWrite 时间与调用时刻吻合。\n\n判据：重启前正常、重启后 qc 变了 = 被 CE 改过。'],
  ['aux 重建失败报 1072 MARKED_FOR_DELETE',
    '因为**宿主持有句柄**：KittyCE 没关，驱动句柄没释放，服务处于待删除态。\n\n处置：先关宿主（S0 reload 流程就是先关宿主），再重建 aux。\n\n判据：1072 + KittyCE 进程还在 = 这条。'],
  ['同一文件换个服务名 sc start 报 ERROR 2',
    '这是**同名映像唯一性**：映像已经在内核里，再用另一个服务名去起同一个文件 → 报 2（FILE_NOT_FOUND 的误导性表现）。\n\n判据：换名重试无意义 —— 这条路上换名只会继续报 2。'],
  ['磁盘上找不到驱动文件，但服务能起来',
    '因为**映像已在内核**，服务只是控制面。\n\n典型场景：qc 指向的文件被删了，但驱动还在内存里跑 —— 此时服务状态不代表映像可用性。\n\n判据：重启后才会暴露（第 7 项）。'],
  ['第三方安全软件怎么排除',
    '360AntiHijack 是头号嫌疑：StartMode=System、**不可停**，会抢 VT / 参与监控。\n\n必须**重启后物理删除**，热卸载无效。\n\n其他放大项：异构 CPU（P/E/LP-E 混核）、深度 C-state、Modern Standby、内存混插、频繁 boot 放大竞态。\n\n判据：环境干净时同配置能起，装了安全软件就起不来。'],
];
for (const x of DRV) add('drvfail', x[0], x[1], { topic: 'drvfail' });

const MISREAD = [
  ['sc start dbk64 报 31，是不是驱动没起来',
    '**不是。这是正常表象。**\n\ndbkk64 只接受 CE 自己的加载器 —— 服务 STOPPED 但驱动**可能正在跑**。\n\n误判后果：以为驱动没起，反复 start/重装，把本来正常的链路搞乱。\n\n判据：用 kitty_status 看内核面可用性，不要用 sc query dbk64 的服务状态判驱动死活。'],
  ['Win32_SystemDriver.PathName 显示 VT 驱动 RUNNING，能当已加载吗',
    '不能。**它读的是注册表 qc**，不是已加载映像。\n\n历史上就有人据此误判"VT 驱动 RUNNING"。\n\n判据：要看实际加载的映像，用 sc qc 的二进制路径 + 进程/内核模块视图对照，不要只看 WMI 的 PathName。'],
  ['OpenService 报 1060 是不是初始化失败',
    '不是。**1060 = 服务不存在**。\n\n实际情况：Loader 会按 .dat 逐个删"从未安装"的别名服务（mygfrhgb / lgtrfghj / mhtfli92 这类），删不存在的必然 1060 —— 这是**预期行为**。\n\n判据：1060 出现在"清理别名服务"阶段 = 正常，不要当成故障去修。'],
];
for (const x of MISREAD) add('misread', x[0], x[1], { topic: 'misread' });

const PLAT = [
  ['哪些平台动作是绝对禁止的',
    '**无条件硬禁**（出现即 FAIL，不看上下文）：\n· steam://install/ 协议拉起\n· steamcmd +login\n· +app_update <数字>\n· epic vault\n\n另外「平台名 + 敏感动词同现」也 FAIL：steam/epic/gog 配上 steamcmd / 安装 / 店面 / 客户端下载 / 库核查 / 拥有态 / vault 拉包 / 页下载 / 账号会话 / store.steampowered / epicgames.com / gog.com。\n\n判据：命中就给等价路径，不执行。'],
  ['为什么用「平台名+动词同现」而不是单看平台名',
    '为了避免**文档提及误杀** —— 讨论"Steam 的 DRM 机制"不该被拦，执行 steamcmd 才该拦。\n\n判据：名称单独出现（在分析语境里）不拦；名称 + 动作同现才拦。'],
  ['哪些安卓线是搁置的',
    '搁置清单：mumu / nx_device / netease\\mumu / gameguardian / GG 浮标 / NECR / BREM / adb 7555 / 16384 已死。\n\n含义：不拉前端、不探 7555、不派 GG 任务；PC 任务禁回头做安卓线。\n\n判据：命中 SHELVED 就停，不要"顺便试试"。'],
  ['被平台门拦下之后走什么路',
    '等价路径（门自己会给）：\n· 本地已落盘包 —— 只读指纹\n· 自研靶标 —— tools/kitty-target.exe\n· targets 现货 —— 授权包落盘处\n· Ghidra 静态分块读头尾\n\n判据：获批前不得碰平台；等价路径能拿到同样的分析结论。'],
  ['平台门怎么自测',
    '跑：\n· node configs/reverse-hybrid/platform-gate.mjs --selftest\n· 或 --check-text --text "<待发动作>"\n· 或 --check-file <file>\n\n设计：零依赖、只读，exit 0=PASS / 1=FAIL。\n\n判据：拿不准的动作先 --check-text 过一遍。'],
];
for (const x of PLAT) add('platform', x[0], x[1], { topic: 'platform' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byKind = out.reduce((a, x) => (a[x.meta.__kind] = (a[x.meta.__kind] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_kind: byKind }, null, 1));

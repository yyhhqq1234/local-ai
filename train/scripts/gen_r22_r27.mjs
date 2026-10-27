#!/usr/bin/env node
/**
 * gen_r22_r27.mjs — 新知识点批次（B 路线）
 *
 * 事实源（只读 DrCE）：
 *   AGENTS.md §2 ACE 口径 / §4 驱动宿主红线 / §5 DBVM 雷区 / §7 运行纪律 / §9 防偏移
 *   docs/02-architecture.md 目录真相 + 硬引用表
 *   docs/03-usage.md 构建链 + 自检判据
 *   .dsh-kitty-overrides.md 三级配置解析
 *
 * R22 路径与编码纪律    R23 驱动宿主红线    R24 DBVM 雷区
 * R25 目录与硬引用      R26 构建与自检链    R27 证据口径
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r22-r27-discipline.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (round, kind, user, assistant, meta = {}) => out.push({
  id: `kitty-${round}-${kind}-${String(out.length).padStart(4, '0')}`,
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: { __stage: 're', __kind: kind, __round: round, ...meta },
});

// ===== R22 路径与编码纪律 =====
const R22 = [
  ['P_WALK 的 offset 为什么必须写十进制 0',
    `因为桥侧 Lua 对 \`0x0\` 会触发 **format-nil 错**。\n\n正确：\nkitty_ce op=P_WALK|0x7FF6DADB01A0|0\n错误：\nkitty_ce op=P_WALK|0x7FF6DADB01A0|0x0\n\n记忆点：地址可以用十六进制，偏移一律十进制。\n\n判据：报 format-nil 或 nil value 就是这里。`],
  ['靶标地址能不能写死',
    `不能。ASLR 每次启动都换基址。\n\n正确做法：一律动态解析 ——\n1) kitty_ce op=OPEN|<pid>\n2) kitty_ce op=MODENUM 拿 base\n3) 用 base + 偏移 算出实际地址再读写\n\n坑：把 0x7FF6DADB2450 硬编码进脚本，换个实例就全错，而且可能读到别的模块里去（更危险：看起来"有值"）。\n\n判据：重启目标后重跑同一脚本必须还能取到合理值。`],
  ['存储路径该放哪',
    `一律放项目根内：\n· dump/转储 → logs 或 vendor 下的专用目录\n· 反编译产物 → vendor/batch-ghidra、vendor/apk-rebuild 这类\n· 脱壳产物 → 统一目录收口\n\n坑：往 D:\\ 上散建目录 —— 会被根外禁建门禁拦（guard-root-only 会报 root-outside writes）。\n\n判据：tools\\guard-root-only.ps1 应回 GREEN。`],
  ['括号路径在 pwsh 里怎么处理',
    `必须加引号：\n\`Test-Path "$r\\logs\\dump.bin"\`\n不加引号会报 positional 参数错。\n\n原因：根目录名含 \`(\` \`)\`，pwsh 会把括号当表达式分组。\n\n判据：报参数位置错误（positional parameter）先查引号。`],
  ['转储前的三条纪律',
    `1) 一律用**绝对路径**（相对路径在子进程里基准不同）\n2) **先建目录**再写（工具不一定自动建）\n3) dump 中断后**先验产物再重跑**（读侧幂等，不会因为重跑而更糟）\n\n坑：中断就重跑但不检查已有产物 —— 可能覆盖掉部分有效数据。\n\n判据：产物大小和节级 copied 数能对上再继续。`],
  ['中文路径的坑怎么绕',
    `外部工具（cmd/aapt/java/python）对中文路径处理不一致，常表现为文件名变 ?? 或 not found。\n\n做法：\n· 中介产物一律落根内 ASCII 路径\n· 中文只留在文件内容里\n· aapt 这类工具的坑靠"根内 ASCII 路径"解决，不要另建 D:\\ 短路径\n\n判据：路径含中文且报 not found 时，先复制到 ASCII 路径重试。`],
  ['projectKey 怎么算的',
    `三步入参 + 四步规范：\n· 入参 = 会话 cwd（绝对路径）\n· 规范化：反斜杠转正斜杠 → 折叠重复斜杠 → 去尾斜杠 → 盘符小写\n\n所以 \`D:\\DrCE(26.2.16)\` 和 \`d:/drce(26.2.16)/\` 是同一个键。\n\n判据：overrides 里读不到配置时，先看 key 的规范化形态对不对。`],
  ['配置的三级优先序',
    `高 → 低：\n· L1 \`<root>\\.dsh-kitty\\overrides.json\` 的当前 projectKey 条目（**唯一可写**）\n· L2 \`~/.dsh/kitty-toolkit.json\`（旧全机单份，**只读，禁写**）\n· L3 插件 Config 默认值（全部相对 root）\n\n键级生效：某键在 L1 命中就用 L1，否则 L2，否则 L3。\n\n坑：去写 L2 —— 那是仓外文件，写不进去也不该写。\n\n判据：resolveOverrides 会返回每键的 sources（project / legacy-home / default）。`],
  ['配置能改哪些键',
    `白名单九个：kittyDir / hostExe / dbgExe / psExe / x64dbgScript / root / timeoutMs / driverEnsure / autoStartDriver\n\n坑：想改别的键（比如加个自定义字段）—— 会被拒或忽略。\n\n正确做法：路径用相对 root（root 自身用 \`.\`）或绝对路径原样透传。\n\n判据：白名单外的键不进生效值。`],
  ['多个项目共用一个 overrides 文件怎么写',
    `写一个键只动它自己，**同文件其它键与旧键一律保留**。\n\n唯一写入口是 writeProjectOverrides（合并写），不要手工整份覆盖。\n\n坑：手工重写整个 json —— 把别的项目/别的 cwd 的配置全删了。\n\n判据：写完再读，其它 projectKey 条目还在。`],
];
for (const [qi, ai] of R22) add('r22', 'path', qi, ai, { topic: 'path' });

// ===== R23 驱动宿主红线 =====
const R23 = [
  ['哪些是不能碰的系统开关',
    `三条红线：\n· \`testsigning=No\` **永不改**\n· SecureBoot 保持现状\n· \`mhtglyts\` 只许 START/STATUS，**禁 STOP**（停即本 boot 死）\n\n坑：为了"干净重启"去 stop 驱动 —— 直接把自己搞死，只能重启机器。\n\n判据：驱动状态异常时优先 recover，不要 stop。`],
  ['Kitty_Dr_Private_Access 能不能 stop',
    `不能。stop 会卡在 **STOP_PENDING**。\n\n正确做法：kitty_drv action=recover（专治 STOP_PENDING）。\n\n坑：看到 PENDING 就反复 stop/start —— 越试越卡。\n\n判据：recover 后状态应变成 RUNNING 或 STOPPED，不再是 PENDING。`],
  ['为什么只能有一个 KittyCE 实例',
    `同一 \`kitty\\\` 目录只许 1 个 KittyCE 实例 —— 桥是通过该目录的文件桥通信的，多实例会抢 cmd/reply 文件。\n\n正确做法：动手前 Get-Process KittyCE 确认单实例。\n\n坑：看到多个就随便杀一个 —— 要按 pid 确认哪个是活的宿主。\n\n判据：kitty_status 里 instances=1。`],
  ['改桥之后必须做什么',
    `**必须重启宿主**。\n\n原因：桥是 Lua 脚本，注入在宿主进程里；改了磁盘上的桥文件，运行中的宿主还在用旧版本。\n\n正确做法：kitty_drv action=host（单实例重拉 + PING + SYNC 归一）。\n\n判据：kitty_status 里 BRIDGE_VER 换成新版本号。`],
  ['跑批之前要清什么',
    `SYNC_ARCHIVE + SYNC_STAT，四项归零。\n\n为什么：残留指令会让新一批指令顶到旧队列上，结果对不上。\n\n正确做法：kitty_drv action=host 会连带做这两步；也可以单独发。\n\n判据：SYNC_STAT 四项都是 0。`],
  ['初始化提权为什么有时点不动',
    `因为任务主体错了：\n· 必须是**交互用户** + \`/RL HIGHEST\` + \`/IT\`\n· SYSTEM 主体会被中完整性进程（S-1-16-8192）的 query/run 拒绝访问 → 按钮点不动\n\n坑：用 /F 覆盖旧任务 —— 会保留旧 ACL，SYSTEM 建过的任务改成用户主体后仍然拒绝。\n\n正确做法：安装脚本**必须先删再建**。\n\n判据：kitty_init action=init 能自动提权（计划任务 KittyInitElev）。`],
  ['ACE 证据等级怎么标',
    `只许三种标注：\n· \`实测通过(操作者)\`\n· \`实测不过(操作者)\`\n· \`未实测\`\n\n口径：简易版 = ACE 实测通过（操作者本机）；完整版 = 实测不过；其余商业 AC 一律未实测。\n\n坑：写"可过市面全部检测"这类普遍命题 —— 禁止。\n\n判据：结论里出现"全部/所有/任意"这类断言就是超出口径。`],
  ['门禁红了能不能硬闯',
    `不能。\n\n规则：gate=green + 写回环全通 = 无拦截面；**仍红 → 停手出证据**，不硬闯。\n\n坑：红着继续换参数试 —— 那是在刷检测而不是在分析。\n\n判据：红的项要落进证据文件（logs/acescan-<ts>.json），而不是重置后重跑。`],
  ['两条永不碰的红线是什么',
    `1) \`KM_PW\`（物理写）—— 永不碰，卡死 Lua 引擎\n2) A 通道 \`DBG_ATTACH|force|unsafe\` —— 永不碰，fail-fast 杀宿主；真调试走 C 通道\n\n注意：这不是"风险较高"，是**永不**。\n\n判据：任何需要物理写或 A 通道 attach 的方案，都要换成等价路径（pread / kitty_x64dbg）。`],
  ['任务范围能自己扩吗',
    `不能。\n\n纪律：todo 每一项必须映射到计划的某一行；**映射不上的工作 = 计划外范围，停手请示**。\n\n坑：顺手把"看起来该修的"也修了 —— 这在长链路项目里会引入不可控变更。\n\n判据：交付的每一项都能指回计划条目。`],
];
for (const [qi, ai] of R23) add('r23', 'host', qi, ai, { topic: 'host' });

// ===== R24 DBVM 雷区 =====
const R24 = [
  ['Use DBVM Debugger=1 时 qc 该怎么写',
    `qc **必须保留 \`Kitty_Dr_D_VT.sys\`**。\n\n坑：为了消掉 not-green 而回写 \`DrDriver.sys\` —— 等于**永久关掉 DBVM**，而且不容易发现。\n\n正确做法：这条有守门工具（tools\\dbvm-guard.mjs），不要手工改 qc。\n\n判据：kitty_init action=status 的 [mode] 行显示 Use DBVM Debugger=1，且 mhtglyts imgIsVT 为 false（即 DrDriver）。`],
  ['DBVM 初始化按钮的两条分支',
    `· A：主驱已在跑 → 直接拉 CE\n· B：主驱 STOPPED 且 qc=VT → 开关先置 0 → 拉 CE → 桥调 \`dbk_initialize\` → 恢复 1\n\n关键前置：**拉 CE 前必须中和 cmd.txt**。\n\n坑：带着残留 cmd.txt 拉 CE —— 旧指令会在 hypervisor 启动期间被执行，行为不可预期。\n\n判据：cmd.txt 为空或已归档。`],
  ['dbk64 加载需要什么条件',
    `本 boot 必须可加载 \`sc start dbk64\`，前提是本次 boot 是 \`VulnerableDriverBlocklistEnable\` 由 **1→0 之后的首个 boot**。\n\n坑：改了注册表就想立刻见效 —— 那条设置要重启才生效，而且必须是"改动后的第一个 boot"。\n\n判据：sc start dbk64 能成功；失败就说明 boot 条件没满足。`],
  ['DBVM 触发为什么要直写 cmd.txt',
    `因为走桥工具的超时重试路径会在 hypervisor 启动期间**误判桥死**，然后触发重试/重拉，把启动过程搞坏。\n\n正确做法：触发必须直写 \`kitty\\cmd.txt\` 或走 GUI Lua 引擎。\n\n判据：DBVM 启动期间不要用 kitty_ce 发指令。`],
  ['DBVM 模式下 KM 面为什么退化',
    `因为 DBVM 优先时主驱换成 VT 版（\`Kitty_Dr_D_VT.sys\`），内核路由能力与 kernel 模式不同。\n\n· mode=kernel（默认）—— KM 面完整\n· mode=dbvm —— DBVM 优先，KM 面退化\n\n判据：需要用 KM_R/KM_PR 做对照时选 kernel 模式。`],
  ['DBVM 下三驱状态怎么读',
    `看 kitty_init action=status 的 [mode] 行与驱动行：\n· Use DBVM Debugger=1\n· mhtglyts imgIsVT 必须 false（即 DrDriver）\n· 三驱 RUNNING\n· 起 CE 后再 \`dbvm-auto.ps1 -Stage Start\`\n\n坑：只看"RUNNING"不看是哪个驱动镜像 —— 镜像错了 DBVM 实际没开。\n\n判据：镜像名与 imgIsVT 两个都要对。`],
];
for (const [qi, ai] of R24) add('r24', 'dbvm', qi, ai, { topic: 'dbvm' });

// ===== R25 目录与硬引用 =====
const R25 = [
  ['哪些目录名不能改',
    `三个都是代码硬引用，改名即断链：\n· \`storages/\`（复数）—— reverse-store.ts 默认 \`storages/reverse\`\n· \`patterns/\` —— kitty_loop 经 patternsDir 引用\n· \`KittyDebugTool/\`（大写）—— cordis.patch.yml 的 kittyDir\n\n坑：为了"规范命名"改成 storage/pattern —— 工具静默找不到，看起来像功能缺失。\n\n判据：改名后 kitty_loop / reverse_add_* 会报路径类错误。`],
  ['patterns 目录放什么',
    `夜跑特征库 3 件：2 个 \`*.json\` + \`GATE-BRANCHES.md\`。\n\n由 kitty_loop 通过 patternsDir 硬引用。\n\n判据：kitty_loop_status 里 patterns 条数应等于实际文件数。`],
  ['storages 存的是什么',
    `逆向存储域（G1/G3 模型的落盘处）：\n· \`storages/reverse/*.db\`\n· reverse-store.ts 默认就是 \`storages/reverse\`\n\n坑：以为可以随便清理 —— 那是 target/intent/obs/patch/asset 的唯一存储。\n\n判据：reverse_add_* 写入后能在该目录看到变化。`],
  ['源码与产物的分工',
    `· \`kitty-toolbox/src/\` —— 78 个 .ts 源码，给开发者和 Agent\n· \`kitty-toolbox/lib/\` —— 236 文件构建产物，给 DSH 运行时（main=./lib/index.js）\n\n坑：改了 src 不 build 就期待生效 —— 运行时加载的是 lib。\n\n判据：改完走构建链再 dev_reload_package。`],
  ['门禁配置在哪',
    `\`configs/reverse-hybrid/\` —— 38 文件：\n· \`router.md\` + \`preset.yml\`\n· 6 个门 \`*-gate.mjs\`（platform / ask / session / target / ops / dual-agent）\n· 8 个校验 \`verify-*.mjs\`\n· \`session-mode.json\`（真相源）+ \`target-state.json\`（双字段）\n· \`engines/\`\n\n判据：门禁报错时按名字找对应 gate 文件。`],
  ['vendor 里该有什么',
    `本地工具链（不入库）：\n· batch-ghidra / ghidra-12.1.3 —— Ghidra 线\n· drdump-ue-sdk / uedumper / dumper-7 —— UE 线\n· dsh-reverse-skill / dsh-reverse-security —— 技能与预设包\n· dbvm-ref —— DBVM 对照树\n· cpp2il / gdsdecomp / apk-rebuild —— 引擎与 APK 线\n\n坑：只装插件不装 vendor —— 工具注册成功但调用时报上游缺席。\n\n判据：报"预设包缺席"先查 vendor。`],
];

for (const [qi, ai] of R25) add('r25', 'layout', qi, ai, { topic: 'layout' });

// ===== R26 构建与自检链 =====
const R26 = [
  ['改了源码怎么生效',
    `两步，缺一不可：\n1) 构建：指定根内 tsc —— \`DSH_TSC_JS=<root>\\kitty-toolbox\\node_modules\\typescript\\lib\\tsc.js\`，跑 \`scripts/build.sh\`（workdir=kitty-toolbox）\n2) 重载：dev_reload_package kitty-toolbox（schema 下一请求生效）\n\n坑：构建时用全局 tsc 或别的项目 node_modules —— 版本不一致，产出的 lib 可能跑不起来。\n\n判据：lib 时间戳更新 + 重载后工具 schema 可见。`],
  ['怎么确认工具都注册上了',
    `\`node tools\\plugin-tool-selftest.mjs\` —— 退出码 0，输出 \`registered(62)\` + \`missing = 无\` + PING 版本号。\n\n判据：missing 不是"无"就是有工具没注册，按名字查注册处。`],
  ['几条自检各自的判据',
    `· \`selftest-v005.mjs\` —— 22/22 PASS；OPS=66；并发 6/6\n· \`audit-coverage.mjs\` —— 汇总 11✅/6🟡/2❌（2❌ 是启动器 GUI-only，预期内）\n· \`render-smoke.mjs\` —— 39/39 PASS\n· \`verify-skill-pack.mjs\` —— 87 ALL PASS\n· \`verify-preset-pack.mjs\` —— ALL PASS\n· \`verify-reverse-gates.mjs\` —— platform 12/12 · ask 13/13 · ops 12/12 · dual 11/11 · shield 20/20；**session 11/14 与 target 11/14 各 exit 1 是设计**\n\n坑：看到 session/target exit 1 就以为门禁坏了 —— 那是这两门需要真实会话态。\n\n判据：其他门全绿 + 这两门按预期红 = 正常。`],
  ['OPS 到底是 65 还是 66',
    `66 = 桥 65 + 通配 1。\n\n· kitty_ops 回"共 66 条=桥65+通配AL_*1"\n· 桥版本 v0.2.9-open-name-resolve-fixed\n· handler 65 / 目录表 66\n\n判据：数字对不上先看是不是把通配算重了。`],
  ['根外禁建门禁怎么用',
    `跑 \`tools\\guard-root-only.ps1\` —— 期望 GREEN，且 EXCEPTIONS=2。\n\n用途：确认没有任何产物写到项目根之外。\n\n坑：出现 root-outside writes 就说明某个工具把产物丢到 D:\\ 上了，查那条路径。\n\n判据：GREEN + EXCEPTIONS 数稳定。`],
  ['构建产物能不能直接判安装成功',
    `不能。发行 smoke **必须用根内隔离目录 + 显式 host peer fixture 回验真实 tgz**，不能借源码树的 node_modules 判安装成功。\n\n原因：源码树里的依赖会掩盖 tgz 里缺失的 peer 依赖。\n\n判据：隔离目录里装 tgz 后能 import 成功。`],
  ['atomic-build 单独跑要注意什么',
    `必须传根内 \`node_modules/typescript/lib/tsc.js\`。\n\n坑：不传的话它不会立刻报错，而是到 staged index.js 校验阶段才失败 —— 排查成本高。\n\n判据：失败信息指向 tsc 路径就是这里。`],
];

for (const [qi, ai] of R26) add('r26', 'build', qi, ai, { topic: 'build' });

// ===== R27 证据口径 =====
const R27 = [
  ['结论里能不能写"可过所有检测"',
    `不能。这是明确禁止的表述。\n\n只许三种标注：\`实测通过(操作者)\` / \`实测不过(操作者)\` / \`未实测\`。\n\n口径：简易版 = 实测通过；完整版 = 实测不过；其余商业 AC 一律未实测。\n\n判据：出现"全部/所有/任意/市面"这类普遍命题就是超口径。`],
  ['没有实测过的东西怎么写',
    `标 \`未实测\`，并写清"为什么没测"（缺环境/缺目标/没时间）。\n\n坑：拿推理当结论 —— 报告里读起来像测过，实际是猜的。\n\n判据：每条结论都能指到一条证据（日志行/文件/回包）。`],
  ['一次分析要怎么留痕才算完整',
    `两条线都要：\n· 过程：kitty_trail action=append（每步写事实，带 sessionGoal/target/step/text）\n· 结论：G3（target → intent → obs/patch/asset）\n\n判据：报告里能从 target 顺链条查到每条 finding 的 repro 步骤。`],
  ['finding 的证据长什么样',
    `必须带 reproSteps ≥1，且步骤要**可重放**：\n\`["1. kitty_ce op=MODENUM 取窗口", "2. kitty_ce op=R|0x…|dword 读初值", "3. 触发变化后重读，值变化"]\`\n\n反例：\`["发现内存可改"]\` —— 这是结论，不可重放，会被拒。\n\n判据：别人照步骤能复现同一现象。`],
  ['对抗结论的证据放哪',
    `· 单地址视图对比 → \`logs/anti-ace-<YYYY-MM-DD>.jsonl\`（dualview 自动写）\n· 完整门禁 → \`logs/acescan-<ts>.json\`（含 rows 逐步记录）\n\n判据：引证据要指到具体文件 + 行/轮次索引，不能只说"跑过了"。`],
  ['为什么补丁要记回滚信息',
    `因为补丁的价值取决于"能不能撤"。\n\n要记三样：\n· expect —— 打之前那里的字节（证明打对位置）\n· 回读 —— 打之后读到的字节\n· 回滚 —— .bak 路径或还原命令\n\n判据：缺回滚信息的补丁记录等于没交付。`],
];

for (const [qi, ai] of R27) add('r27', 'evidence', qi, ai, { topic: 'evidence' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byRound = out.reduce((a, x) => (a[x.meta.__round] = (a[x.meta.__round] || 0) + 1, a), {});
const chars = out.reduce((s, x) => s + JSON.stringify(x.messages).length, 0);
console.log(JSON.stringify({ out: OUT, samples: out.length, by_round: byRound, avg_chars: Math.round(chars / out.length) }, null, 1));

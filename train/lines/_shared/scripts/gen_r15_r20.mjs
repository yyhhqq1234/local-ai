#!/usr/bin/env node
/**
 * gen_r15_r20.mjs — R15 引擎路由 + R16 移动链 + R17 REA + R18 G3 + R19 会话 + R20 决策树
 *
 * 事实源（只读 DrCE）：
 *   engines.ts         routeEngine 的后缀表 7 条 + 目录兜底 6 条 + unknown 兜底
 *   apkjadx.ts         jadx via=java(JavaCLI) / via=bat；apktool jar 路径与 b/d 参数；apkid .bat 走 cmd /c
 *   rea.ts             status→list→describe→call；provider 绑定陷阱
 *   reverse-store.ts   parentId 必须引用既有记录（否则 throw）；addTarget 清 6 表恒得 target-1
 *   session-tools.ts   14 个会话动作白名单；task-dispatch transition 枚举；写 state 会 TASK-TRANSITION-UNKNOWN
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r15-r20-final.jsonl';
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

// ==================== R15 引擎路由 ====================
const R15 = [
  ['拿到一个游戏目录，先判断引擎', `直接交给路由：kitty_engines path=<游戏目录>\n\n它按"后缀优先、目录兜底"给结论，格式：\`ENGINE=<类型> TOOL=<工具> NEXT=<下一步> target=<路径>\`\n\n判据：回 ENGINE=unknown 才需要自己看（那时它会建议 kitty_patch info + kitty_sym）。`],
  ['后缀路由表有哪几条', `7 条（实现原文）：\n· assembly-csharp.dll → unity-mono → kitty_dnspy，NEXT=open\n· .bundle / .assets → unity-asset → kitty_assetrip，NEXT=list/export\n· .apk / .dex → apk → kitty_jadx/kitty_apktool/kitty_frida，NEXT=decompile\n· .lua / .luac → lua → kitty_lua，NEXT=decompile\n· .uasset / .umap → unreal-asset → kitty_fmodel，NEXT=list\n· .pck → godot → kitty_gdre，NEXT=list/recover\n· gameassembly.dll / global-metadata.dat → unity-il2cpp → kitty_cpp2il，NEXT=triage/dump\n\n判据：给的是文件路径就走这张表，命中即出结论。`],
  ['目录兜底判据是什么', `6 条（按实现顺序）：\n1) 有 GameAssembly + global-metadata → unity-il2cpp（cpp2il/il2cppdumper）\n2) 有 .pck → godot（gdre，NEXT=list）\n3) 有 *-Shipping.exe / .pak → unreal（uedump/fmodel/ue4ss，NEXT=triage）\n4) 有 .bundle → unity-asset（assetrip，NEXT=list）\n5) 有 .apk/.dex → apk（jadx/apktool，NEXT=decompile）\n6) 有 Assembly-CSharp.dll → unity-mono（dnspy，NEXT=open）\n\n判据：目录兜底是有序的，先命中先返回 —— 所以混合目录会按上面的优先级判。`],
  ['Unity Mono 和 IL2CPP 怎么区分', `· Mono：有 \`Assembly-CSharp.dll\`（托管 dll 直接可见）→ 用 kitty_dnspy\n· IL2CPP：有 \`GameAssembly.dll\` + \`global-metadata.dat\`（代码编译进 native）→ 用 kitty_cpp2il 或 kitty_il2cppdumper\n\n判据：两个都有说明是混合（少见），先按 IL2CPP 走，Mono 侧当辅助。`],
  ['IL2CPP 有两条 dump 路线，选哪个', `· kitty_cpp2il —— Cpp2IL，给 gameDir，NEXT=triage/dump\n· kitty_il2cppdumper —— Il2CppDumper，要 so + meta 两个路径\n\n选法：\n· 目录完整、想一把出 → kitty_cpp2il action=dump gameDir=<目录>\n· 只要那些文件、想精确控制 → kitty_il2cppdumper action=dump so=<libil2cpp.so> meta=<global-metadata.dat>\n\n判据：两条都能出 dump.cs；对不上类数时换另一条试，能看出是哪一侧的问题。`],
  ['UE 的目标该怎么入手', `路由会给 \`unreal → kitty_uedump/kitty_fmodel/kitty_ue4ss NEXT=triage\`。\n\n按目标选：\n· 要 SDK（类/函数/偏移）→ kitty_uedump action=triage → dump\n· 要 pak 里的资产 → kitty_fmodel action=list（加密 pak 要 aesKey）\n· 要运行时挂脚本 → kitty_ue4ss action=triage → inject\n\n判据：先 triage 再动手 —— UE 版本和 GObjects 偏移不对，dump 出来全是错的。`],
  ['Godot 的 .pck 怎么处理', `路由给 \`godot → kitty_gdre NEXT=list/recover\`。\n\n两步：\n1) kitty_gdre action=list target=<x.pck> —— 先看里面有什么\n2) kitty_gdre action=recover —— 还原脚本和场景\n\n判据：list 出的类型分布决定要不要 recover 全部（有的 pck 只含资源不含脚本）。`],
  ['Unity 资源 .bundle / .assets 怎么导', `用 kitty_assetrip：\n· action=list —— 先列清单\n· action=export —— 批量导出\n\n输入可以是文件或目录（路由区分这两种）。\n\n判据：不先 list 直接 export，碰到大包会很慢且可能漏类型。`],
  ['路由回 unknown 怎么办', `它会给建议：\`NEXT=kitty_patch info + kitty_sym\`。\n\n照做：\n1) kitty_patch action=info path=<主 exe> —— 看节表/架构/是否加壳\n2) kitty_sym action=imports path=<主 exe> —— 看导入了什么（能反推运行时/引擎）\n\n判据：节表有 .text/.rdata 但没引擎特征 → 自研引擎或静态链接，按 native 逆向走。`],
  ['路由能不能直接给下一步命令', `能，它输出 format 是 \`ENGINE=… TOOL=… NEXT=… target=…\`，NEXT 就是建议动作。\n\n但注意 NEXT 是**动作名**（open/list/triage/decompile/dump/recover），不是完整命令 —— 参数要你自己按目标填。\n\n判据：拿到 NEXT 后按对应工具的 action 拼参数，不要指望它替你拼。`],
];
for (const [qi, ai] of R15) add('r15', 'engine', qi, ai, { topic: 'engine' });

// ==================== R16 移动链 ====================
const R16 = [
  ['APK 到手先做什么', `三步定性，不要直接反编译：\n1) kitty_apkscan action=scan target=<x.apk> —— 查壳/指纹\n2) kitty_jadx action=decompile target=<x.apk> —— 看能不能正常出 Java\n3) 出不来或 dex 极小 → 有壳，走 kitty_unpack\n\n判据：dex 文件极小 + 有 native loader + stub Application → 加固，先脱再分析。`],
  ['jadx 走 java 还是 bat', `两条路（实现里自动分派）：\n· via=java → \`java -cp <lib/*> jadx.cli.JadxCLI -d <out> <target>\`\n· 否则 → 直接跑 jadx.bat\n\n为什么有 java 档：.bat 在含括号的路径下会被 cmd 断句（工作区根目录就带括号）。\n\n判据：bat 报 exit_code=255 且日志是 GBK 乱码 → 换 via=java。`],
  ['jadx 的 search 为什么不给结果', `因为实现里 search 只返回一条 HINT：\n\`HINT jadx-gui搜 https:// / AES / sign / SharedPreferences 定位接口与加密（GUI手动）\`\n\n它不真做搜索 —— 全量反编译后自己在产物里搜更快。\n\n判据：要搜字符串就在 decompile 产物目录里用文本搜索，别指望这个 action。`],
  ['apktool 的 decode 和 build', `· decode：\`java -jar apktool.jar d <target> -o <out> -f\`（-f 覆盖）\n· build：\`java -jar apktool.jar b <target> -o <out>\`\n\n前提：vendor/apktool/apktool.jar 存在，否则回 \`ERR|apktool.jar missing\`。\n\n判据：改完 smali 重打包后还要 zipalign + apksigner 签名才能装。`],
  ['apkscan 报 apkid missing', `APKiD 没装。回包会给 \`NEXT: pip install apkid 或 MobSF docker\`。\n\n注意：MobSF(docker) 和 Quark(pip) 是**外部服务**，本工具只做指纹收口，不会替你起容器。\n\n判据：急的话先 jadx 反编译看 dex 结构，壳的迹象也能看出来。`],
  ['apkscan 的输出为什么合并了 stderr', `因为 APKiD 把结果写在 stderr 上。\n\n实现里做了 \`stdout + stderr\` 合并。.bat 形态还会走 \`cmd /c\`。\n\n判据：你自己手跑 apkid 时记得 \`2>&1\`，否则看着像"没扫出东西"。`],
  ['脱壳产物怎么收口', `kitty_unpack：\n· action=collect —— 建统一目录收 BlackDex/FART 的输出\n· action=parse —— 清点 .dex\n\n判据：手机侧脱壳产物散落时先 collect 再 parse，直接 parse 会漏。`],
  ['frida 的四个 action', `· status —— 探 frida 环境\n· spawn —— 启动并挂\n· attach —— 附加已运行进程\n· trace —— 跟踪\n· capture —— 抓包（配合 R0capture）\n\n判据：目标还没起用 spawn，已在运行用 attach；先 status 确认 frida-server 在。`],
  ['要 hook 一个具体方法', `先静态定签名：kitty_jadx action=decompile 拿到类名+方法名+重载。\n再动态：kitty_frida action=attach pkg=<包名> script=<hook.js>\n\n判据：hook 打印的参数类型要和静态签名对上；对不上是重载选错了。`],
  ['APK 加固的判定链', `四步：\n1) apkscan → 指纹（哪家壳）\n2) jadx decompile → dex 数、Application 指向\n3) 看 classes.dex 大小（几百 KB 且业务类找不到 = 壳 dex）\n4) unpack collect/parse → 脱出来的真 dex\n\n判据：能正常解出业务 dex 且 Application 指向业务类，才算脱干净。`],
];
for (const [qi, ai] of R16) add('r16', 'mobile', qi, ai, { topic: 'mobile' });

// ==================== R17 REA 网关 ====================
const R17 = [
  ['REA 怎么用，为什么只有一个工具', `kitty_rea 是**全量网关**：一份 schema 覆盖上游 170 个工具。\n\n固定三段式：\n1) action=status —— 服务起没起\n2) action=list —— 列 170 个工具（可 query 过滤）\n3) action=describe tool=<名> —— **写 args 前必查契约**\n4) action=call tool=<名> args={...} —— 真调用\n\n判据：跳过 describe 直接 call，参数名错会白跑一次。`],
  ['rea_* 那些单工具和 kitty_rea 什么关系', `它们是常用工具的**快捷入口**（schema 已填好参数）：\n· kitty_rea_binary → inspect_binary_layout\n· kitty_rea_function → analyze_function\n· kitty_rea_javascript → analyze_javascript_application\n· kitty_rea_trace → trace_feature\n· kitty_rea_callpath → trace_call_path\n· kitty_rea_compare → compare_functions\n· kitty_rea_android → inspect_android_package\n· kitty_rea_method → inspect_android_method\n· kitty_rea_recover_js → recover_javascript_sources\n\n判据：常用的走快捷入口（参数明确），冷门的走 kitty_rea call。`],
  ['inspect_binary_layout 报 provider 不可用', `这是 **provider 绑定陷阱**：它固定绑 \`pwntools-elf\`（Linux x64 only），换 provider 参数无效。\n\n要分析 PE / 深度结构，改走会话态工具组：\n1) open_binary\n2) binary_overview\n3) list_procedures / analyze_function\n\n判据：报 provider_unavailable 不是环境问题，是选错入口了。`],
  ['REA 报 Ghidra 版本或 JDK 问题', `它校验两件事：\n· SUPPORTED_GHIDRA_VERSION=12.1.4 —— **同 major.minor 即 compatible**（12.1.3 属 12.1.x，接受）\n· JAVA_MAJOR=21 —— 环境 JAVA_HOME 是 17 时必须给 REA 子进程覆盖成 21\n\n判据：版本对、JAVA 21 还失败 → 往路径（括号）方向查。`],
  ['rea 的 call 参数怎么写', `action=call tool=<上游工具名> args={...}\n\nargs 是 JSON，字段名按 describe 的契约来。\n\n例：\nkitty_rea action=describe tool=analyze_function\nkitty_rea action=call tool=analyze_function args={"input_path":"X:/sample.exe","procedure":"main"}\n\n判据：参数名错会报未知字段，先 describe 再写。`],
  ['JS/Electron 分析怎么走', `用 kitty_rea_javascript（对应 analyze_javascript_application）。\n\n关键：参数名是 **input_path**（不是 path），format 可以 auto/asar/directory。\n\n输出会含 statistics（文件数/解析数/AST/findings）和 electron 相关字段。\n\n判据：input_path 给目录或 asar 都行，format=auto 会自动判。`],
  ['要按字符串追调用链', `· kitty_rea_trace query="<字面量>" —— 特性级追踪（参数是 query）\n· kitty_rea_callpath start=<起点> goal=<终点> —— 调用路径（方向 forward/backward）\n\n判据：知道"从哪到哪"用 callpath；只知道一个字符串用 trace。`],
  ['跨版本函数对比怎么做', `两步取 Evidence，一步比：\n1) kitty_rea_function procedure=<符号>（旧版）\n2) 同命令在新版取\n3) kitty_rea_compare left=<Evidence> right=<Evidence>\n\n判据：对比结果要能定位到具体基本块差异；只给相似度分数不算完成。`],
  ['rea 服务没起怎么办', `· action=status 看状态\n· action=start 拉起（首用懒启动）\n· 装依赖：npm install --prefix <root>/vendor/rea rea-agents\n\n判据：status 绿了再 list；list 空说明 MCP 握手没成，看 start 的日志。`],
  ['REA 和本地工具怎么分工', `REA（上游 170 工具，跨语言/跨平台分析能力强）：\n· 二进制布局/函数档案/JS-Electron/调用链/跨版本对比\n· 适合"要一份结构化证据"的场景\n\n本地工具（kitty_ghidra / kitty_ida / kitty_dnspy 等）：\n· 直接跑上游本体，输出原始\n· 适合"我要原始输出"或 REA 那条线不支持\n\n判据：要结构化 + 少手工 → REA；要原始/特定版本 → 本地工具。`],
];
for (const [qi, ai] of R17) add('r17', 'rea', qi, ai, { topic: 'rea' });

// ==================== R18 G3 数据模型 ====================
const R18 = [
  ['G3 的五个 add 各记什么', `· reverse_add_target —— 新建目标（**会话清零**，恒得 target-1）\n· reverse_add_intent —— 意图（target/scope/method 三元去重，命中即复用）\n· reverse_add_obs —— 观察/finding（**finding 必须带 reproSteps ≥1**）\n· reverse_add_patch —— 补丁（expect + 回读 + 回滚信息进 data）\n· reverse_add_asset —— 资产（parentId 只引既有）\n\n判据：finding 不带复现步骤会被拒 —— 这是硬校验。`],
  ['parentId 能引用什么', `只能引用**本会话既有记录**。\n\n实现里：\n· 给了 parentId 但库里没有 → throw \`parentId 无既有记录：<id>\`\n· 不给 → 该字段直接删掉（不建父子边）\n\n判据：先用 target-get 或看返回值拿真实 id，不要自己编。`],
  ['addTarget 为什么要会话清零', `因为它的语义是"开新案子"：清本会话 6 张表 + 计数器清零，再插 target-1。\n\n所以它永远是 target-1，不会累加。\n\n判据：想保留上一轮记录就别调 addTarget —— 它会把之前的清掉。`],
  ['子会话为什么不能直接 add', `子会话的写入口只有 reverse_submit（直写父 intent 下）。\n\nCHILD_DENIED_TOOLS 里包含 add 全家 + state/graph/report —— 子只读父视图。\n\n为什么：避免子会话在父的记录树上乱挂节点，破坏溯源结构。\n\n判据：子会话要落结论，走 reverse_submit(intentId=父意图)。`],
  ['finding 的 reproSteps 怎么给', `必须 ≥1 条，且要是**可重放的步骤**，不是结论描述。\n\n好例子：["1. kitty_ce op=MODENUM 取窗口", "2. kitty_ce op=R|0x…|dword 读初值", "3. 触发掉血后重读，值变化"]\n\n坏例子：["发现内存可改"]（这是结论，不可重放）\n\n判据：别人按你写的步骤能复现同一现象，才算合格。`],
  ['patch 记录要带什么', `expect + 回读 + 回滚信息，都进 data。\n\n因为补丁的可用性取决于"能不能撤"：\n· expect —— 打之前那的字节（证明打对了位置）\n· 回读 —— 打之后读到的字节\n· 回滚 —— .bak 路径或还原命令\n\n判据：缺回滚信息的补丁记录等于没交付。`],
  ['asset 记什么', `产物引用：路径 / 地址 / 哈希。\n\n典型：dump 出的 bin、脱壳的 dex、反编译产物目录、抓到的 pcap。\n\n判据：只记路径不记哈希，后续无法证明这份产物没被替换。`],
  ['整个记录链该长什么样', `一条完整链：\ntarget-1\n  └ intent-1（目标/范围/方法）\n      ├ obs-1（finding + reproSteps）\n      ├ patch-1（expect + 回读 + 回滚）\n      └ asset-1（产物引用）\n\n判据：report 时能从 target 顺 chain 查到每条 finding 的 repro 步骤，才算留痕完整。`],
  ['意图去重怎么判断', `按 (target, scope, method) 三元组去重 —— 同目标同范围同方法，命中就复用已有 intent，不新建。\n\n判据：同一方法重复登记会得到同一个 intent id，这是设计不是 bug。`],
  ['什么时候该调 addTarget', `只在"开新案子"时：\n· 换了一个完全不同的分析对象\n· 上一轮已收口归档\n\n不该调：同一个目标继续深入（那应该 addIntent）。\n\n判据：误调会把上一轮的 6 张表清空 —— 不可逆。`],
];
for (const [qi, ai] of R18) add('r18', 'g3', qi, ai, { topic: 'g3' });

// ==================== R19 会话真相源 ====================
const R19 = [
  ['kitty_settings 能干什么', `只放行 14 个会话动作：\ntarget-set / target-get / task-inherit / mode-set / mode-get / reverse-init / trail-get / root-get / host-rebind / task-open / task-get / task-dispatch / task-close / task-new\n\n其他动作回 \`ERR|kitty_settings 仅放行会话动作…实操走各 kitty_* 工具\`。\n\n判据：它是**会话状态机**，不是通用执行器。`],
  ['target-set 要给什么', `两个字段，必须分开：\n· sessionGoal —— 本轮会话目标（做事的目标）\n· target —— 目标进程名/路径/URL（可定位的实体）\n\n回包后转任务态。\n\n判据：两栏写成一样就是错 —— 它们进不同的下游（目标进 triage/交接/报告文本，进程名进 OPEN/扫描/读写）。`],
  ['双字段为什么要分开', `因为下游用途完全不同：\n\n· 会话目标 → 只进 skill-auto / triage / 交接 / 报告 / trail 文本\n· 目标进程 → 才进 OPEN / 扫描 / 读写 / 指针 / 对抗 / 转储\n\n判据：把会话目标和进程名混为一谈时，两栏相等 —— 这是最常见的错。`],
  ['mode 有几种，切换注意什么', `两种：task / standby。\n\n· mode-set 切状态\n· mode-get 只读\n· session-mode.json 是唯一真相源，缺文件 = 待命\n\n判据：切换后要 mode-get 确认；遇 standby 同停（PAUSED-DENY），重锁定即回。`],
  ['task-dispatch 的 transition 怎么写', `必带 type，取值枚举：\nenter-task{sessionGoal,targetProcess,targetKind} / enter-standby / stage-start{stage} / stage-complete{stage,evidence?} / stage-fail{stage} / retry-stage{stage} / block{stage,question} / answer{questionId,answer} / complete{evidence[]} / finish{evidence[]} / abandon{reason?} / set-consent{consent}\n\n判据：写 \`{"state":…}\` 会回 \`ERR|TASK-TRANSITION-UNKNOWN\` —— 不要自创字段名。`],
  ['收口序列是什么', `三步，顺序固定：\ntarget-set → task-dispatch{type:finish,evidence:[…]} → task-close\n\n判据：不 finish 直接 close 会缺终态证据；企图中途 close 会留下 open task。`],
  ['host-rebind 和 target-set 的区别', `· target-set —— 重建双字段（会话目标 + 目标进程），转任务态\n· host-rebind —— 只改宿主绑定；keepLock=true 时**只改 host，不动 mode/target**\n\n判据：换宿主不影响任务定义 → 用 host-rebind + keepLock；换目标 → 用 target-set。`],
  ['trail 怎么记', `kitty_trail action=append，参数：\n· sessionGoal —— 本轮目标（与工作台 TARGET 同串会自动跟进）\n· target —— 目标\n· step —— 本步动作名（如 R / P_BACK / 判据）\n· text —— 事实/回包摘要（≤2000 字）\n· stage —— 1接案~8取证 段名\n\n读：action=get，top 默认 50 上限 200。\n\n判据：trail 记的是**过程事实**，结论落 G3。`],
  ['root-get 干什么', `只读回 \`{root, rootSrc}\` —— 工作台根目录与来源判定（wire 会话 cwd → 包位置探测，去 env）。\n\n不落盘、不改 mode/target/trail。\n\n判据：路径相关报错先 root-get 看它认的根在哪。`],
  ['task-inherit 什么时候用', `跨会话继承任务：from=<源 sessionKey>。\n\n场景：换会话继续同一个案子，不想重填双字段和任务态。\n\n判据：继承完要 task-get 确认 generation 和阶段对得上。`],
  ['会话状态错了怎么回正', `按顺序查三层：\n1) kitty_settings action=mode-get —— 当前模式\n2) kitty_settings action=target-get —— 双字段对不对\n3) kitty_settings action=root-get —— 根目录对不对\n\n回正：mode-set 切回 task，或 target-set 重设双字段。\n\n判据：不要直接改 session-mode.json —— 工具是唯一正确入口。`],
];
for (const [qi, ai] of R19) add('r19', 'session', qi, ai, { topic: 'session' });

// ==================== R20 跨工具决策树 ====================
const R20 = [
  ['同一个值有四种读法，怎么选',
    `四种读法及取舍：\n\n1) kitty_ce op=R —— 用户态读，最快，**可能被 hook 骗**\n2) kitty_km action=read（KM_R）—— 内核路由读，绕用户态 hook，慢一点\n3) kitty_km action=pa + pread —— VA→PA→物理读，最底层，能看穿页表级拦\n4) kitty_prot action=extread —— 外部托管读，CE 不可用时才用\n\n决策：\n· 日常取值 → R\n· 怀疑被 hook → KM_R\n· 怀疑页表级拦截 → pa + pread\n· 要一次看全 → kitty_dualview（三路并读 + 自动判分叉）\n\n判据：只有一个读数时无法判断真假；要下结论必须有对照。`],
  ['看代码有五个入口，怎么选',
    `1) kitty_ghidra —— 免费，headless 批处理，vendor 里自带 12.1.3\n2) kitty_ida —— 有授权时最准，批处理导出\n3) kitty_rea_function —— 要结构化证据（伪码/汇编/引用一起给）\n4) kitty_dnspy —— 只对 .NET/\nMono 有效\n5) kitty_rea_binary —— 只要布局（节/段/符号），不反编译\n\n决策：\n· 有 IDA → kitty_ida\n· 没 IDA、要批处理 → kitty_ghidra\n· 要证据包（跨版本对比/调用链）→ kitty_rea_*\n· .NET → 只能 dnspy\n· 只想看布局 → rea_binary\n\n判据：选错入口的代价是白跑一次（尤其 rea_binary 不给你代码）。`],
  ['找地址有三条路，怎么选',
    `1) 扫描（S_NEW / S_NEXT / S_SNAP）—— 知道值不知道位置\n2) 反查（P_BACK / kitty_pchain）—— 知道位置要找指针链\n3) AOB 模式找（kitty_patch action=find）—— 找代码特征而不是数据\n\n决策：\n· 值已知（血量 3500）→ 扫描\n· 值未知（刚开局）→ S_SNAP + CHANGED/UNCHANGED\n· 地址已知要稳定化 → pchain\n· 找指令/函数入口 → find（pattern）\n\n判据：扫描解决"在哪"，反查解决"怎么稳定找到"。`],
  ['写内存有四档，怎么选',
    `按风险从低到高：\n1) kitty_ce op=W —— 用户态写 + 回读校验（首选）\n2) kitty_prot action=protect + W —— 页只读时先改属性\n3) kitty_wpb —— PTE 直改，绕保护 API，保护被反复刷回时用\n4) kitty_km action=write —— 内核路由写（对照用，不是主路径）\n\n绝不能碰：pwrite（永久拒绝，会卡死引擎）\n\n判据：每上一档都要能说清为什么低档不行。`],
  ['抓包有三条路，怎么选',
    `1) kitty_net action=capture —— mitmproxy 抓 HTTP(S)，出 pcap\n2) kitty_frida action=capture —— 手机侧 R0capture，绕证书固定\n3) kitty_proto action=decode —— 已有二进制载荷要解字段\n\n决策：\n· PC 端 HTTP → net\n· 手机 App → frida\n· 抓到的是 protobuf 帧 → proto\n\n判据：证书固定的场景 net 抓不到明文，必须走 frida。`],
  ['脱壳的整体顺序',
    `五步，顺序不能换：\n1) kitty_die action=scan —— 先认壳（不知道什么壳就没法选脱法）\n2) kitty_patch action=info —— 看节表特征确认（RWX + 尺寸异常）\n3) 脱：native 壳走内存 dump（kitty_dump unmap=true）；APK 壳走 kitty_unpack\n4) kitty_patch action=hash —— 记产物哈希\n5) 静态验证：kitty_ghidra / kitty_ida 能否正常解析导入表\n\n判据：跳过第 1 步盲脱，十次有九次脱出来是壳本身。`],
  ['要"证据包"还是"原始输出"',
    `判断标准：交付物给谁看。\n\n· 给自己快速看 → 本地工具原始输出（kitty_ghidra / kitty_ida）\n· 要给结论/做对比/进报告 → REA 结构化证据（kitty_rea_function / compare / trace）\n· 要对抗结论 → kitty_acescan 的 gate + json 证据\n· 要过程留痕 → kitty_trail + G3\n\n判据：报告里引证据要能指到文件+行，原始输出往往做不到。`],
  ['一键编排 vs 手工串联怎么选',
    `· kitty_acescan —— 对抗门禁八步一次跑完，出 gate 结论\n· kitty_loop —— 夜跑八站流水（收案→分诊→静态→定位→对抗→还原→修改→回归）\n· kitty_pchain —— 指针链三阶段一次跑完\n\n手工串联适用于：\n· 中间要看中间结果再决定分支\n· 目标行为异常，自动流水会掩盖问题\n\n判据：标准场景用编排（可复现），探索阶段手工（可调整）。`],
  ['工具报错时先看什么',
    `三层分流（顺序别错）：\n1) \`ERR|unknown-op\` / \`bad-arg\` → **参数问题**，查 kitty_ops 签名，不改工具\n2) \`ERR|need-range\` → **窗口问题**，MODENUM 拿真实区间\n3) \`ERR|no-open\` → **没挂目标**，先 OPEN\n4) \`ERR|KM_PW-DENIED\` → 设计如此，换路径\n5) 超时 → **通道/宿主问题**，kitty_status + kitty_drv status\n\n判据：参数类错误换工具是白费；通道类错误改参数也是白费。`],
  ['面对陌生目标的标准打法',
    `六步（每步都有判据）：\n1) 定性：kitty_die scan + kitty_patch info → 壳/编译器/架构\n2) 符号：kitty_sym imports/exports → 用了什么库（反推语言/框架）\n3) 路由：kitty_engines path=… → 引擎类型与建议工具\n4) 静态：kitty_ghidra / ida / rea_function → 关键逻辑\n5) 动态：kitty_x64dbg（C 通道）断点验证\n6) 落痕：kitty_trail + G3（target→intent→obs/patch/asset）\n\n判据：每步都要有"下一步做什么取决于这个回包哪一段"的明确依赖，没有就说明这步白做。`],
];

for (const [qi, ai] of R20) add('r20', 'decision', qi, ai, { topic: 'decision' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byRound = out.reduce((a, x) => (a[x.meta.__round] = (a[x.meta.__round] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_round: byRound }, null, 1));

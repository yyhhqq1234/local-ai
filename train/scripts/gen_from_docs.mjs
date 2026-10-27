#!/usr/bin/env node
/**
 * gen_from_docs.mjs — 从 DrCE docs 提炼「上游依赖 + 真实坑 + 排障」样本（R17 部分 / 跨轮公共）
 *
 * 来源：D:/DrCE(26.2.16)/docs/05-reference.md（只读）
 * 这些事实是实测踩出来的，模型学到了才不会乱调工具链。
 *
 * 输出：train/data/re-iter/r02-pitfalls.jsonl
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r02-pitfalls.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (kind, user, assistant, meta = {}) => out.push({
  id: `kitty-${kind}-${String(out.length).padStart(4, '0')}`,
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: { __stage: 're', __kind: kind, __round: 'r02', ...meta },
});

// ---------- 上游依赖（来自 05-reference 的表）----------
const UPSTREAM = [
  { tool: 'kitty_jadx', deps: 'jadx（走 `java -cp lib/*.jar jadx.cli.JadxCLI`，绕开 .bat 的括号路径坑）', when: 'APK Java 层反编译' },
  { tool: 'kitty_apktool', deps: 'apktool.jar（必须有 java）', when: 'smali 解包/重打包' },
  { tool: 'kitty_apkscan', deps: 'APKiD（输出走 stderr，插件已合并 stdout+stderr）', when: '查壳/指纹' },
  { tool: 'kitty_frida', deps: 'frida（+ objection / R0capture 指路）', when: '运行时 hook / 抓包' },
  { tool: 'kitty_gdre', deps: 'gdsdecomp / GDRE', when: 'Godot pck 还原' },
  { tool: 'kitty_assetrip', deps: 'AssetRipper（识别 AssetRipper.GUI.Free.exe）', when: 'Unity 资源导出' },
  { tool: 'kitty_dnspy', deps: 'dnSpyEx + de4dot（源码态）', when: '.NET 反编译/去混淆' },
  { tool: 'kitty_bepinex', deps: 'BepInEx / MelonLoader', when: 'Unity mod loader' },
  { tool: 'kitty_uexplorer', deps: 'UnityExplorer（经 kitty_inject 注入）', when: 'Unity 运行时对象浏览' },
  { tool: 'kitty_uedump', deps: 'UEDumper 1.11.1', when: 'UE SDK dump' },
  { tool: 'kitty_fmodel', deps: 'FModel / UnrealPak', when: 'UE pak 资产' },
  { tool: 'kitty_ue4ss', deps: 'RE-UE4SS', when: 'UE 运行时脚本 mod' },
  { tool: 'kitty_lua', deps: 'luadec / unluac（exe 或 jar 双档，via=java 自动分派）', when: 'Lua 反编译' },
  { tool: 'kitty_die', deps: 'DIE（Detect It Easy）', when: '查壳/编译器指纹' },
  { tool: 'kitty_ghidra', deps: 'Ghidra（vendor/ghidra-12.1.3 + batch-ghidra 编排）', when: '无 IDA 时反编译' },
  { tool: 'kitty_net', deps: 'mitmproxy / Wireshark(tshark)', when: '流量抓取与解码' },
  { tool: 'kitty_proto', deps: 'protoc / blackboxprotobuf / grpcurl', when: 'protobuf 解码' },
  { tool: 'kitty_il2cppdumper', deps: 'Il2CppDumper', when: 'IL2CPP 标准 dump' },
  { tool: 'kitty_cpp2il', deps: 'Cpp2IL', when: 'IL2CPP dump（另一条实现）' },
];

for (const u of UPSTREAM) {
  add('upstream', `${u.tool} 底层靠什么跑？如果它报依赖缺失我该看哪里？`,
    `${u.tool} 的上游：${u.deps}\n\n用途：${u.when}。\n\n排障顺序：\n1) 先 ${u.tool} action=status —— 它会直接告诉你依赖在不在、版本对不对\n2) 报缺依赖就按上面的上游补，不要急着换工具\n3) 依赖齐了才调 status 之外的动作\n\n判据：status 是绿的但动作还失败，说明问题不在依赖，去看路径/编码/权限这一层。`,
    { tool: u.tool });
}

// ---------- 真实坑与修法 ----------
const PITFALLS = [
  { q: 'kitty_ghidra 报 exit_code=255，日志里是 GBK 的「此时不应有 __\\vendor\\rea\\...」',
    a: `这是**括号路径**坑，不是 Ghidra 的问题。\n\n成因：Ghidra 的 analyzeHeadless.bat 走 cmd.exe，而工作区根目录是 \`D:\\DrCE(26.2.16)\`，路径里的 \`(\` \`)\` 会让 cmd 提前断句。\n\n修法：用 SUBST 建一个无括号的别名盘（如 \`X:\`）指向真实根，所有子进程路径走别名。插件里是 ensureAsciiRoot 干的这件事。\n\n判据：修好后同样的命令 exit_code=0；如果还是 255，看是不是 JAVA_HOME 没覆盖成 21。`, tag: 'encoding-path' },
  { q: 'REA 的二进制分析报 provider_unavailable',
    a: `三个可能，按顺序查：\n\n1) **provider 绑定陷阱**：\`inspect_binary_layout\` 固定绑 \`pwntools-elf\`（Linux x64 only），换 provider 无效。\n   深度分析必须走会话态工具组：open_binary → binary_overview / list_procedures / analyze_function。\n2) **版本/JDK**：Ghidra 校验 SUPPORTED_GHIDRA_VERSION=12.1.4 + JAVA_MAJOR=21。同 major.minor 即 compatible（12.1.3 属 12.1.x → 接受）。环境里 JAVA_HOME 是 17 时必须给 REA 子进程覆盖成 21。\n3) **括号路径**：同上，走 SUBST 别名。\n\n判据：provider 名字对了、版本 compatible、JAVA 21，三条齐了还报，才是真的 provider 侧问题。`, tag: 'rea' },
  { q: 'kitty_apkscan 明明扫出东西了但显示没结果',
    a: `APKiD 的输出走的是 **stderr**，不是 stdout。\n\n插件已经做了 stdout+stderr 合并，所以走工具调用是能看到的；\n但如果你自己直接跑底层命令，必须 \`2>&1\`，否则看起来像"什么都没找到"。\n\n判据：区分"真没壳"和"没读到输出"—— 后者往往伴随输出为空但退出码正常。`, tag: 'apk' },
  { q: 'kitty_lua 反编译报找不到 luadec',
    a: `luadec 有双档：exe 或 jar。\n\n插件里 via=java 会自动分派到 jar 档。所以：\n· 本机只有 jar → 确认 via=java\n· 本机只有 exe → 别加 via=java\n\n判据：action=status 会报它到底探测到哪一档。`, tag: 'lua' },
  { q: 'kitty_dbg attach 之后宿主进程没了',
    a: `这是已知行为，不是 bug：本 build 的 debugProcess 会随机 fail-fast 杀宿主（F-13）。\n\n所以 DBG_ATTACH 是双层闸门：force 只解默认拒绝，unsafe 才真调，并且必须显式 accept_host_loss=true 确认你接受宿主被杀。\n\n正确做法：真调试优先走 C 通道 kitty_x64dbg（program / seed / rununtil / collect），A 通道调试面只用来查状态。\n\n判据：只是要看状态就用 action=status，不要 attach。`, tag: 'debug' },
  { q: 'kitty_wpb 写完读回来还是旧值',
    a: `三个检查点：\n\n1) **target 是不是用户态地址** —— wpb 只支持用户态，内核地址会失败\n2) **restore=true 是否把它还原回去了** —— 默认写后还原 PTE，如果你的验证在还原之后读，会看到旧值（这是设计，不是写失败）\n3) **页状态**：NOACCESS 页或已换出页要加 permissive=true，按 PFN 重建整组保护位\n\n判据：写入那一刻的回读值才是判据，之后的读受 restore 影响。`, tag: 'wpb' },
  { q: 'kitty_km 的 pwrite 一直失败',
    a: `pwrite 是**默认拒绝**的设计：实测物理写会卡死 Lua 引擎（宿主活着但 tick 停摆），恢复只能重启宿主。\n\n所以它需要 accept_engine_wedge=true 才肯走，而且这是"破坏性确认"，不是普通参数。\n\n替代：改走 W（用户态写带回读）或 kitty_wpb（PTE 直改），两条都不需要碰物理写。\n\n判据：除非你明确要承担引擎卡死，否则不要碰 pwrite。`, tag: 'kernel' },
  { q: 'kitty_x64dbg 的 seed 断点没命中',
    a: `seed 的地址参数要能被调试器解析：\n· 符号写法 \`kernelbase.CreateFileW\` 走模块+符号解析\n· 数值写法要给 VA，不是 RVA\n· 目标进程必须是正在调的那个，seed 不会自动附加\n\n判据：readdb 里没有命中记录 = 断点没设上（符号解析失败）；\n有命中但 savedata 空 = 命中命令写错了参数（如位数 64/32）。`, tag: 'debug' },
  { q: 'kitty_dualview 三路读数不一致该怎么读',
    a: `三路是 R（用户态）/ KM_R（内核路由）/ KM_PR（经 KM_PA 的物理读）。\n\n判读表：\n· 三路一致 → 无视图分叉，问题在别处（去看逻辑而不是内存）\n· R 与 KM_R 不一致 → 用户态视图被改，重点查 hook / inline patch\n· KM_R 与 KM_PR 不一致 → 页表层有问题，怀疑 PTE 级拦截或换页\n\n注意：KM_PR 本 build 返回的是 table，桥已经转换过，不要自己再当字符串切。\n\n证据落在 logs/anti-ace-<date>.jsonl，samples 默认 1，间歇性问题要加到 5-10。`, tag: 'anti' },
  { q: 'kitty_acescan 报 gate=red 怎么定位是哪一层被拦',
    a: `它是一条流水：驱动守卫 → 宿主探活 → OPEN → KM_ATTACH → 模块窗口 → 三视图门禁 → 写回环。\n\n定位方法：看落到 logs/acescan-<ts>.json 里的逐项记录，红在哪一项就是哪一层：\n· 驱动守卫红 → 驱动没起，走 kitty_drv action=ensure\n· 宿主探活红 → 宿主掉了，走 kitty_drv action=host\n· KM_ATTACH 红 → 内核面打不开，走 kitty_km action=api 看可用面\n· 三视图分叉 → 有 hook，按上面 dualview 的判读表\n· 写回环红 → 写保护被拦，走 kitty_wpb\n\n判据：gate=green 且写回全通，才算无拦截面。`, tag: 'anti' },
  { q: 'kitty_ce 发了个 OP 直接回 unknown-op，是不是桥坏了',
    a: `不是。这是**本地早拒**：桥侧维护了 OP 名白名单，拼错在本地就拒掉，省一次往返。\n\n正确做法：\n1) 用 kitty_ops filter=<前缀> 查真实名字（比如 filter=P_ 查全部指针类）\n2) 按返回的签名逐段对位，参数顺序不能换\n3) 改对再发\n\n判据：unknown-op 一定是名字问题，不用怀疑通道；如果是参数问题会回 bad-arg，两者要分开。`, tag: 'a-channel' },
  { q: 'kitty_dump 出来的文件和原文件一致率很低',
    a: `先判断是不是带壳：壳会在运行时改代码段，dump 出来的内存镜像和磁盘原始文件本来就不同。\n\n排查顺序：\n1) kitty_patch action=info 看节表特征（RWX + VirtualSize/SizeOfRawData 比例异常 = 有壳）\n2) 有壳先脱再 dump，否则一致率低是必然的\n3) 无壳但一致率低 → 检查 IAT 是否回填（fix_iat=true）\n4) 还是低 → 加 sections=true 做节级比对，看是哪一节不一致（定位到具体节就知道改了什么）\n\n判据：一致率接近 1.0 才算重建正确；0.9x 通常就是 IAT 或某个节的问题。`, tag: 'dump' },
];

for (const p of PITFALLS) {
  add('pitfall', p.q, p.a, { tag: p.tag });
}

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');

const kinds = out.reduce((a, x) => (a[x.meta.__kind] = (a[x.meta.__kind] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_kind: kinds }, null, 1));

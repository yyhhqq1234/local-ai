#!/usr/bin/env node
/**
 * gen_r11_r14.mjs — R11 转储重建 + R12 运行时改造选型 + R13 对抗编排 + R14 驱动依赖
 *
 * 事实源（只读 DrCE）：
 *   dump.ts        unmapImage 按节表 VA→PointerToRawData 搬运；IAT 从 ILT 回填；不解引用/不修复重定位；参考比对给一致率
 *   mem-tools.ts   kitty_inject（ce/ps/loaddll 三档 + bits）、kitty_prot、kitty_wpb
 *   anti-tools.ts  acescan gate 五态（green/host-down/divergent/alloc-failed/writeblocked）、写回环 ⑦、降级语义
 *   driver-tools.ts kitty_drvio surf/open/probe、CommIoInject 证书吊销、kitty_init mode=dbvm/needElev
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r11-r14-adv.jsonl';
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

// ==================== R11 转储重建 ====================
const R11 = [
  ['dump 出来的镜像为什么不能直接当文件用', `因为内存里的镜像是**按 VA 展开**的：每个节在内存里位于它的 VirtualAddress，节与节之间有对齐空洞。\n\n而磁盘文件里的节数据位于 PointerToRawData。两者布局不同。\n\n所以必须 unmap（重建）：kitty_dump module=kitty-target.exe unmap=true\n\n判据：不做 unmap 的产物只能当原始字节看，反汇编器按 PE 结构解析会错位。`],
  ['unmap 具体做了什么', `三步：\n1) 头部（DOS/NT/节表）前 headersSize 字节按原样保留\n2) 逐节把 [VirtualAddress, +SizeOfRawData) 的数据搬到 [PointerToRawData)\n3) 按节表最大 rawPtr+rawSize 决定输出大小，其余补零\n\n回包会给每节的 name/va/rawPtr/rawSize/copied，可以逐节核对搬了多少。\n\n判据：copied 小于 rawSize 的节，说明那一段在内存里没读到（可能页未提交）。`],
  ['IAT 回填是怎么回事', `内存里 IAT 槽存的是**已解析的真实地址**，而文件里应该是指向名称表的 RVA。\n\nfix_iat=true 会从 ILT（导入名称表）把 thunk 回填回 IAT 槽 —— 这样重建后的文件导入表又能被解析器识别。\n\n回包会写 \`IAT 重建：从 ILT 回填 N 个 thunk\`。\n\n判据：N=0 说明 IAT 本来就是干净的，或者 ILT 不可用（节被改过）。`],
  ['一致率多少算正常', `看情况，别一刀切：\n\n· 无壳、未运行、纯静态加载 → 接近 100%\n· IAT 已解析 / 重定位被应用 → **必然低于 100%，属预期**\n· 带壳 → 明显偏低（壳会改代码段）\n· 运行中 dump → 低且不可预测（代码被 patch、数据被改）\n\n判据：回包注释里那句"（IAT/重定位差异属预期）"就是在提醒这一点，不要拿 99.9% 当唯一标准。`],
  ['它不解引用 IAT、不修复重定位，谁来干', `dump 只做**布局重建**，不做语义修复：\n· 不解引用 IAT —— 那是 Scylla / ImportREC 的活\n· 不修复重定位 —— 需要按 .reloc 表和 ImageBase 差异逐项修\n\n所以：\n· 只要静态分析看代码 → 重建后就能用\n· 要能再次运行 → 必须再补 IAT + 重定位\n\n判据：交付物表述里要写清"已重建布局，未修复导入/重定位"。`],
  ['sections=true 有什么用', `额外导出每节的独立 bin：\`<path>.<节名>.bin\`。\n\n用途：\n· 节级定点比对（只看 .text 变了多少）\n· 单节喂给反汇编器\n· 定位"是哪一节不一致"——比分整文件快得多\n\n判据：整文件一致率低但说不清原因时，加这个参数就能定位到节。`],
  ['dump 前该先确认什么', `三件事：\n1) 目标进程还活着且已 OPEN\n2) 模块窗口能拿到（MODENUM，注意 size 可能为 0）\n3) 是不是带壳（kitty_patch info 看节表 RWX 特征）\n\n为什么第 3 条重要：带壳时代码段在运行中才解密，你 dump 到的是解密后的（好事），但和磁盘文件比对一致率会很低（正常）。\n\n判据：先定性再 dump，否则会误判"dump 坏了"。`],
  ['dump 产物路径要注意什么', `要给 ASCII 路径。中文/括号路径在 Windows 上会坑到子进程（cmd 的括号断句问题）。\n\n建议：\n· 输出到工作区内，如 logs\\\\dump-<ts>.bin\n· 不要放在含括号的根目录下\n\n判据：路径报错但目录存在，基本就是路径字符问题。`],
  ['运行中 dump 和静态 dump 的区别', `静态 dump（文件直接读）：不经过进程，拿的就是磁盘内容，无需 unmap。\n\n运行中 dump：\n· 拿到的是**加载后的镜像**（VA 布局）\n· 已被运行时修改（IAT 解析、代码 patch、数据初始化）\n· 必须 unmap 才能被静态工具正常解析\n\n判据：进程还在跑就 dump → 一定 unmap=true；只是要文件副本 → 直接读文件，不用 dump。`],
  ['dump 完怎么验证没读错', `三层验证：\n1) 节级：看回包每节 copied 是否等于 rawSize\n2) 头部：文档开头 0x400 字节应与原文件一致（DOS/NT 头不随加载变）\n3) 一致率：有参考文件时看百分比，结合"是否带壳/IAT 是否已解析"解释偏差\n\n判据：头 0x400 都不一致 = dump 起点错了，不用再看后面。`],
];
for (const [qi, ai] of R11) add('r11', 'dump', qi, ai, { topic: 'dump' });

// ==================== R12 运行时改造选型 ====================
const R12 = [
  ['要往目标里塞 dll，三档怎么选', `kitty_inject 有三档：\n\n· ce（默认）—— 走 A 通道 LUA injectDLL，需要 CE 宿主在\n· ps —— .NET 托管注入器，不依赖 CE，给 pid 即可\n· loaddll —— 外部工具 DBG64/DBG32 的 loaddll.exe <dll>，bits 选 64（默认）或 32\n\n选法：\n· 宿主健康 → ce（最快）\n· 宿主挂了/不想动 CE → ps\n· 要指定位数（32 位目标）→ loaddll + bits=32\n\n判据：注入后自动 MODENUM 复核，回包里没有目标模块名就是没进去。`],
  ['注入成功怎么确认', `工具会自动做 MODENUM 复核，看回包里模块清单有没有你的 dll 名。\n\n补充确认：\n· kitty_sym source=mem module=<你的dll> —— 能列出导出即模块已加载\n· 有导出函数的话 resolve 一下拿地址，验证可调用\n\n判据：只在回包里看到"已注入"不算，必须看到模块出现在模块表里。`],
  ['页只读写不进去，prot 和 wpb 怎么选', `先走 prot（改属性），不行再 wpb（PTE 直改）：\n\nkitty_prot action=protect addr=0x… size=4096 protect=rwx confirm=true\n→ 写完记得还原成原属性\n\nkitty_wpb addr=0x… vt=dword val=100 accept_protection_bypass=true\n→ 走 DTB→PTE→改 R/W→写→还原 PTE，不碰保护 API\n\n选 wpb 的判据：\n· 保护被反复刷回（protect 改了立刻变回）\n· 目标是 PAGE_NOACCESS 或已换出（要 permissive=true）\n· 不想留 protect 调用痕迹\n\n判据：能 prot 就别 wpb —— 后者风险面大得多。`],
  ['prot 的 protect 取值有哪些', `noaccess / readonly / rw（默认）/ wc / x / rx / rwx / guarded\n\n常用：\n· rw —— 要写数据段\n· rwx —— 要写代码段并执行\n· rx —— 还原代码段\n\n判据：改之前先 action=query 记下原值，写完按原值还原 —— 不还原可能触发完整性检查。`],
  ['写保护绕过要什么确认', `kitty_wpb 必须 accept_protection_bypass=true（或 confirm），否则直接拒。\n\n这是显式风险确认，不是普通参数：它绕过页保护写入，写错会直接搞崩目标。\n\n配套参数：\n· restore=true（默认）写后还原 PTE\n· permissive=true 按 PFN 重建整组保护位（NOACCESS/换出页）\n\n判据：写完必须回读验证，而且要在 restore 之前读。`],
  ['prot 的 extread/extwrite 是什么', `外部托管档位（.NET 实现），不依赖 CE 内联：\n· extread —— 从外部进程读\n· extwrite —— 从外部进程写（value 给 dword）\n· alloc / free —— 在目标里分配/释放\n· query —— 查保护属性\n\n需要 pid 或先 OPEN。\n\n判据：CE 不可用时用这一档，代价是慢（每次起一个外部调用）。`],
  ['rwx 一把梭有什么代价', `kitty_prot action=rwx 走 CE 的 FullAccess，把页改成可读写执行。\n\n代价：\n1) 可执行+可写页是完整性检查的重点目标（很多反作弊会扫这个组合）\n2) 改完不还原会一直留着\n\n判据：只读需求别用 rwx；写完尽快还原成 rx。`],
  ['注入后想调函数怎么定位', `用 kitty_sym 走内存符号：\n\n1) kitty_sym action=exports source=mem module=<dll名> —— 拿导出与 VA\n2) kitty_sym action=resolve module=<dll名> name=<导出名> —— 直接要地址\n\n拿到 VA 后再用 kitty_ce op=R/W 或 LUA createRemoteThread 调用。\n\n判据：resolve 拿不到说明导出名写错或模块没加载，先回第 1 步列清单。`],
  ['改造类工具的风险排序', `从低到高：\n\n1) kitty_prot action=query / probe —— 只读\n2) kitty_prot action=protect —— 改属性，可还原\n3) kitty_inject —— 注入，改变目标状态但通常可控\n4) kitty_wpb —— 绕过保护直改页表，出错最容易崩\n5) kitty_km action=pwrite —— 永久拒绝（会卡死引擎）\n\n判据：能用低档解决就别上高档；每上一步都要能说清为什么。`],
  ['改完要不要还原', `要。三个层面：\n· 页属性 → 改回原值（protect/query 记的原值）\n· PTE → wpb 的 restore=true 会做\n· 内存值 → 看业务需求，测试完该还原\n\n判据：不还原的后果是目标行为异常且难以复现；对抗场景还会被完整性检查抓到。`],
];
for (const [qi, ai] of R12) add('r12', 'runtime', qi, ai, { topic: 'runtime' });

// ==================== R13 对抗编排 ====================
const R13 = [
  ['acescan 的 gate 有几种值', `五种（实现里的状态机）：\n\n· green —— 三视图逐轮一致且写回环全通\n· host-down —— 宿主探活失败，后面全部作废\n· divergent —— 三视图出现分叉（R vs KM_R 或 KM_R vs KM_PR）\n· alloc-failed —— 写回环里 ALLOC|64 拿不到槽位，环中止\n· writeblocked —— 写回环有步被吞（用户态写内核读、内核写用户态读不一致）\n\n判据：只有 green 能说"无拦截面"；其他四种各自指向不同层。`],
  ['acescan 一条命令都做了什么', `八步流水：\n① 驱动守卫\n② 宿主探活（失败 → gate=host-down）\n③ OPEN 目标\n④ KM_ATTACH\n⑤ 模块窗口\n⑥ 三视图门禁（R / KM_R / KM_PR，diverged>0 → gate=divergent）\n⑦ 写回环（默认开：ALLOC|64 → 用户态写内核读 → 内核写用户态读 → 还原释放）\n⑧ 结论 + 落 logs\\\\acescan-<ts>.json\n\n参数：target / module / addr / vt / samples（默认 3，上限 10）/ writeback（默认 true）/ attach\n\n判据：证据文件里 rows 是逐步记录，红在哪步就是哪层。`],
  ['写回环具体在验什么', `四步双向验证：\n1) ALLOC|64 在目标里要一块槽位\n2) 用户态写一个值 → 内核路由读，看一致\n3) 内核路由写一个值 → 用户态读，看一致\n4) 还原并 FREE\n\n被吞的步数记进 bad，非空 → gate=writeblocked。\n\n它验的是：**写入是否真的落到物理内存并被两条路径共同看见**。单向一致可能是缓存/影子页造成的假象。\n\n判据：写回环全通 + 三视图一致，才排除"只能读不能写"的拦截。`],
  ['gate=divergent 怎么定位到具体哪一路', `看 ⑥ 那行：\n\`门禁 red：N/M 轮分叉（索引列表）\`\n\n然后再看逐轮的 ⑦/⑥ 明细行，每行都写着三路值：\n\`#i addr=… pa=… 用户态=… 内核=… 物理=… 一致/<< 分叉\`\n\n判据表（同 dualview）：\n· 用户态 ≠ 内核 → 用户态视图被改，查 hook\n· 内核 ≠ 物理 → 页表层问题，查 PTE 拦截\n\n判据：光知道 diverged 没用，要指到哪一轮哪两路。`],
  ['KM 降级时 gate 还算 green 吗', `算，但会明确标注：\`自动降级=开（KM→R只读兜底，本轮仍按三视图一致计）\`。\n\n含义：内核面取不到数时，用 R 兜底，三视图退化成两视图，**判据强度下降**。\n\n判据：拿到 green 但带降级标注时，结论要写"未排除内核面异常"，不能等同正常 green。`],
  ['variants 切换怎么确认生效', `kitty_variants action=switch variant=<id> 之后下一次调用才生效（不是立即）。\n\n确认：\n1) kitty_status probe=true —— 看 BRIDGE_VER 与宿主 pid 有没有变\n2) kitty_variants action=list —— 看当前标记\n\n判据：切换后必须重新探活，别直接发指令。`],
  ['C 通道就绪怎么判', `看 bpl 行：含 \`SENT[restored|kept]\` 即链路通。\n\n注意一个坑：SelfTest 的 savedata 需要 notepad 调试目标，**空载 DBG 上 FAIL 属预期**（脚本预置行为），不代表链路断。\n\n判据：区分"链路不通"和"用例需要调试目标"—— 后者换个目标跑就过。`],
  ['acescan 的 samples 给多少', `默认 3，上限 10。\n\n· 常规体检 → 3\n· 抓间歇性分叉 → 8~10\n· 每加一轮就多约 4 次往返（R/KM_R/KM_PA/KM_PR）+ 写回环固定开销\n\n判据：间歇问题必须多轮；单轮 green 不能排除定时刷回类拦截。`],
  ['证据文件里该看什么', `logs\\\\acescan-<ts>.json 字段：ts / target / pid / module / addr / vt / samples / diverged / gate / rows。\n\n看三样：\n1) gate —— 结论\n2) diverged —— 分叉轮数\n3) rows —— 逐步记录，定位红在哪\n\n判据：交付时引具体行号或 round 索引，不能只说"跑过了"。`],
  ['dualview 和 acescan 该用哪个', `· 只想验一个地址的视图一致性 → kitty_dualview（轻，4 次往返/轮）\n· 要完整对抗结论（含驱动/宿主/写入能力）→ kitty_acescan（重，八步全跑）\n\n判据：日常排查用 dualview，出结论/交付证据用 acescan。`],
  ['gate=writeblocked 怎么继续', `说明写得进去但读不回来，或反过来。继续查三步：\n1) 看 ⑦ 那行 slot 和被吞步数\n2) 用 kitty_dualview 单独验那个槽位地址\n3) 换 kitty_wpb 写同一槽位再读，能通说明是保护层拦写不是内存问题\n\n判据：writeblocked 优先怀疑写保护/影子页，不要先怀疑内存损坏。`],
  ['gate=alloc-failed 怎么办', `ALLOC|64 拿不到槽位，写回环保不住。\n\n原因：目标地址空间里没有空闲可分配区（罕见），或 CE 的分配路径被拦。\n\n处置：\n1) kitty_prot action=alloc 单独试一次，看具体错误\n2) 换一个已知可写的现有区（不分配，直接写那里）\n3) 仍不行 → 这轮写回环跳过，结论只能报"写入能力未验证"\n\n判据：alloc 失败不等于有拦截，可能是环境问题，别直接下结论。`],
];
for (const [qi, ai] of R13) add('r13', 'anti', qi, ai, { topic: 'anti' });

// ==================== R14 驱动依赖 ====================
const R14 = [
  ['驱动和宿主的启动顺序', `固定顺序，不能换：辅助驱 → 宿主 → 主驱 START → 验真 → 拉 CE 等心跳。\n\n一键走：kitty_init action=init mode=kernel\n\n· mode=kernel（默认）—— KM 面完整\n· mode=dbvm —— DBVM 优先，KM 面退化\n\n判据：跳顺序的典型后果是主驱起来了但宿主没起，后续所有指令超时。`],
  ['kitty_drv 的四个动作', `· ensure（默认）—— 双驱 辅助→主驱，幂等，15s 内成功有缓存（force 可忽略缓存）\n· status —— 只看状态，不 ensure\n· host —— 看门狗：单实例重拉 + PING + SYNC 归一（含 SYNC_ARCHIVE + SYNC_STAT）\n· recover —— 修 STOP_PENDING 态，hostStart 控制是否重拉宿主\n· storm —— 连续 PING 压测，cycles 默认 20 上限 100，可选每轮附 KM_ATTACH|<pid>\n\n判据：正常自愈用 host 或 ensure；状态卡在 STOP_PENDING 才用 recover。`],
  ['storm 压测的判据', `cycles 轮连续 PING（可选带 KM_ATTACH），任一丢失就触发看门狗并计数。\n\n· cycles 默认 20，上限 100（实现里 Math.min）\n· 判据：20 次零丢失是基准线\n· 回包会给每轮明细和 incidents 列表\n\n用途：切换变体/改驱动后验证稳定性。\n\n判据：有一轮丢失就说明该变体不稳，别拿"大部分成功"当通过。`],
  ['drvio 和 drv 的区别', `· kitty_drv —— 会**启停**：ensure/recover/host/storm 都会动服务\n· kitty_drvio —— **只读不启停**：status/probe/open/surf\n\n什么时候用 drvio：\n· 只想看设备在不在，不想因为探测触发重启\n· 要清点本机驱动侧软件（WKE64 / CE 插件 / .dat / PDB / InjectTool）\n\n判据：排查阶段先用 drvio（无副作用），要修才用 drv。`],
  ['CommIoInject 为什么不能用', `它的设备驱动是 STOPPED 状态（证书吊销，设备不存在）。\n\n实现里直接返回：\n\`ERR|CommIoInject 所在驱动 STOPPED（证书吊销，设备不存在）；APC 链只做静态描述，不下发带参 IOCTL\`\n\n判据：这条路径不通，不要反复 probe；要注入走 kitty_inject 的三档。`],
  ['drvio 的 device 参数给什么', `probe/open 时给设备名，默认 \`DreamDumperDrunken\`。\n\n用法：\n· kitty_drvio action=status —— 看全部设备状态\n· kitty_drvio action=probe device=<设备名> —— 试打开\n· kitty_drvio action=surf —— 只看软件面（不碰驱动）\n\n判据：不知道设备名就先 status/surf 看清单，别猜。`],
  ['init 需要提权怎么办', `kitty_init action=init 内部走计划任务 \`KittyInitElev\` 自动提权，不需要你手打命令。\n\nmode=dbvm 时还有 VT 相关前置检查（主驱映像是 Kitty_Dr_D_VT.sys 且状态非 RUNNING 会判 pending）。\n\n判据：init 报需要提权就是计划任务没建起来，走 \`--reload\` 全量重建辅助驱再试。`],
  ['主驱起不来怎么查', `四层：\n1) kitty_drv action=status —— 两个驱动的 SCM 状态\n2) 看是哪一层：辅助驱（Private_Access）没 RUNNING → 主驱不会起\n3) STOP_PENDING → kitty_drv action=recover\n4) 反复失败 → kitty_init action=init reload=true 全量重建\n\n判据：STOP_PENDING 是最常见的卡点，它意味着上一次 stop 还没落定，等或 recover，不要硬 start。`],
  ['什么情况下要重启宿主', `三个信号：\n· PING 连续丢失且看门狗拉不回来\n· 出现过 engine-wedge（KM 写超时）\n· DBG_ATTACH 之后（本 build 会杀宿主，属于已知）\n\n重启：kitty_drv action=host hostStart=true\n\n判据：重启后必须 SYNC_STAT 四项归零才算干净。`],
  ['怎么确认整套依赖是健康的', `四层逐项：\n1) kitty_status action=status —— 通道 cmd/rep 时戳、sync pending、KittyCE 进程\n2) kitty_status probe=true —— 带一次实探\n3) kitty_drv action=status —— 双驱 SCM 状态\n4) kitty_selftest group=all —— 全链回归\n\n判据：PING 通 + SYNC 四项归零 + 宿主单实例，三条齐。`],
];
for (const [qi, ai] of R14) add('r14', 'infra', qi, ai, { topic: 'infra' });

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byRound = out.reduce((a, x) => (a[x.meta.__round] = (a[x.meta.__round] || 0) + 1, a), {});
console.log(JSON.stringify({ out: OUT, samples: out.length, by_round: byRound }, null, 1));

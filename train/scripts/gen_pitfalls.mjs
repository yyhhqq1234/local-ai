#!/usr/bin/env node
/**
 * gen_pitfalls.mjs — 避坑专项数据集（R21）
 *
 * 素材：216 个 ERR 码（316 处出现）+ docs 已知缺口 + 实现里的边界检查
 * 分类：A 门禁会话 / B 参数动作 / C 桥契约 / D 宿主驱动 / E 路径编码 / F 工具链 / G 产物 / H 顺序
 *
 * 每坑固定四段：触发条件 → 后果 → 正确做法 → 判据
 * 输出：train/data/re-iter/r21-pitfalls.jsonl
 */
import fs from 'node:fs';

const OUT = 'train/data/re-iter/r21-pitfalls.jsonl';
const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const out = [];
const add = (cls, user, assistant, meta = {}) => out.push({
  id: `kitty-pit-${String(out.length).padStart(4, '0')}`,
  messages: [
    { role: 'system', content: SYS },
    { role: 'user', content: user },
    { role: 'assistant', content: assistant },
  ],
  meta: { __stage: 're', __kind: 'pitfall', __round: 'r21', __class: cls, ...meta },
});
const P = (cls, q, a, tag) => add(cls, q, a, tag ? { tag } : {});

// ===== A 门禁 / 会话坑（8）=====
P('A', '切任务态报 ERR|MODE-NEEDS-DUAL 是什么意思',
  `意思是**双字段没齐**，不是配置坏了。\n\n触发：\n· 缺 sessionKey（不回落 default 共享分片）\n· 或缺锁定的 TARGET（会话目标 + 目标进程没都定）\n\n后果：mode-set task 被拒，会话停在待命；后续所有需要 task 态的调用都会 PAUSED-DENY。\n\n正确做法：先 kitty_settings action=target-set 把 sessionGoal 和 target 两栏都写上，再 mode-set task。\n\n判据：target-get 两个字段都非空且不相等，才算齐。`, 'session');

P('A', '提示 ERR|HOST-MISMATCH-DENY 说状态件属他机',
  `这是**跨机保护**：该会话状态件记录的 host 不是本机。\n\n触发：从别的机器拷来的会话目录 / 状态件里 host 为空或不同。\n\n后果：拒绝写盘（HTTP mutate 零写，分片字节没动）—— 也就是说你的 target-set / trail 全不会生效，但也不会污染。\n\n正确做法：kitty_settings action=host-rebind 先写回本机 host，再重锁任务态。\n\n判据：host-rebind 后 mode-get 能读到当前模式，且再写一次 trail 能看到新行。`, 'session');

P('A', 'ERR|SESSION-KEY-MISSING 怎么修',
  `task 类动作**必须显式给 session**，缺了直接 DENY，不会回落 default 共享分片。\n\n为什么这么设计：多会话并行时，回落 default 会把 A 会话的任务状态写到 B 会话里。\n\n正确做法：调 task-* 时把 session 参数带上（真实会话键）。\n\n判据：不带 session 永远失败，这是设计不是 bug —— 不要靠重试解决。`, 'session');

P('A', 'ERR|TASK-DISPATCH-MISSING 是什么意思',
  `两处都会报：\n1) task-dispatch 没给 taskTransition\n2) task-api 层 generation 和 transition 任一缺失\n\n后果：状态机不动，任务停在当前阶段。\n\n正确做法：task-dispatch 必须同时带 generation（从 task-get/task-open 拿）和 taskTransition（JSON，必含 type）。\n\n判据：generation 是乐观锁 —— 拿旧的 generation 会失败，要重新 task-get。`, 'session');

P('A', 'ERR|TASK-TRANSITION-UNKNOWN 为什么写 {"state":…} 就报',
  `因为 transition 的字段名固定是 **type**，不是 state。\n\n合法 type：\nenter-task{sessionGoal,targetProcess,targetKind} / enter-standby / stage-start{stage} / stage-complete{stage,evidence?} / stage-fail{stage} / retry-stage{stage} / block{stage,question} / answer{questionId,answer} / complete{evidence[]} / finish{evidence[]} / abandon{reason?} / set-consent{consent}\n\n后果：自创字段名直接被拒，状态机不动。\n\n判据：写 {\"type\":\"stage-start\",\"stage\":\"静态\"} 这种形态才对。`, 'session');

P('A', 'ERR|GATE-UNKNOWN 说门禁自检异常',
  `两种来源：\n· 任务状态文件损坏（storages/tasks/<session>.json 读不动）\n· 门禁自检抛异常，按 **fail-closed** 直接拒\n\n后果：执行被拒（安全侧行为，不是出错）。\n\n正确做法：先重试一次；仍红就跑 WS-SELFTEST 自检链。\n\n判据：不要试图绕过门禁去改状态文件 —— fail-closed 是故意设计。`, 'session');

P('A', 'ERR|WIRE-SPLIT-DENY:parent-header-unresolved 怎么办',
  `说明分片写入时**父会话头解析失败**，分片不能脱离父头存在。\n\n触发：会话目录被搬动/截断，或 parent header 缺失。\n\n后果：分片写被拒，避免写出孤儿数据。\n\n正确做法：按回包里的 refreshSessionHint 刷新会话上下文（重开或重挂），不要手工拼分片文件。\n\n判据：parent header 能解析后，同样的写会成功。`, 'session');

P('A', 'ERR|SETUP-CONFIG-INVALID 是什么限制',
  `setup 流程**只接受路径和超时类配置**，其他键一律拒。\n\n后果：配置写不进，环境初始化不完整。\n\n正确做法：只传路径（root/tool 路径）与超时类字段；要改别的走对应工具自己的参数。\n\n判据：报错里会指名是哪个 key 不被接受。`, 'session');

// ===== B 参数 / 动作名坑（10）=====
P('B', 'ERR|unknown action 出现 19 次是什么意思',
  `这是**最常见的坑**，也是成本最低的坑：action 拼错或不在该工具的 enum 里。\n\n分布：cpp2il/gdre/ghidra/ida/idamcp/il2cppdumper/variants/drv/x64dbg/dbg/drvio/init/km/prot/patch/asm/uedump/dnspy 都会报。\n\n后果：白跑一次往返。\n\n正确做法：action 取值只看该工具 schema 的 enum，不要照搬别的工具的动作名（比如把 patch 的 rollback 用到 dump 上）。\n\n判据：unknown action 一定是你写错了，不是工具坏了。`, 'param');

P('B', 'kitty_ce 拼错 OP 名会怎样',
  `回 \`ERR|unknown-op\` —— 这是**本地早拒**：桥侧维护 OP 名白名单，拼错在本地就拒，不发出去。\n\n为什么要记住：\n· unknown-op = 名字问题（改名字）\n· bad-arg = 参数问题（改参数）\n· 两者不要混\n\n正确做法：kitty_ops filter=<前缀> 查真实名字（如 filter=P_ 查指针类）。\n\n判据：改对名字后同参数能过。`, 'param');

P('B', '参数给了还是报缺参',
  `执行层有一批**硬性必填检查**，缺了直接返回 ERR| 且不发到桥：\n· kitty_km attach —— 需 pid\n· kitty_km read/pa —— 需 addr\n· kitty_km write —— 需 addr + val\n· kitty_km pread —— 需 pa\n· kitty_ghidra/ida analyze —— 需 target\n· kitty_cedump/gdre —— 需 gameDir 或 target\n\n后果：不发请求就失败，看起来像"工具没反应"。\n\n判据：这类错误不会改变任何状态，补参数重发即可。`, 'param');

P('B', 'confirm 类参数忘了会怎样',
  `一批**动手类**动作需要显式确认，不给就拒：\n· kitty_patch action=patch —— confirm=true\n· kitty_km action=write —— confirm=true\n· kitty_prot action=protect / rwx —— confirm=true\n· kitty_prot action=extwrite —— confirm=true\n· kitty_wpb —— accept_protection_bypass=true（或 confirm=true）\n· kitty_dbg action=go —— confirm=true\n· kitty_ce 的 W / LUA —— confirm=true\n\n后果：报 SINGLE-CONSENT-REQUIRED 类拒绝。\n\n判据：这类确认是**单次**的，不是全局开关 —— 每次调用都要带。`, 'param');

P('B', 'bits 参数什么时候用',
  `只有 kitty_inject via=loaddll 时才需要：64（默认）或 32。\n\n它决定用 DBG64\\loaddll.exe 还是 DBG32\\loaddll.exe。\n\n坑：32 位目标用 64 位注入器会失败（架构不匹配），但报错可能只说"注入未确认"。\n\n判据：注入后 MODENUM 复核没看到模块，先检查 bits 和目标的架构是否一致。`, 'param');

P('B', 'in_place 和 backup 的关系',
  `· in_place=true（默认）→ 原地改原文件\n· in_place=false → 写 <path>.patched，原文件不动\n· backup=true（默认）→ 原地改之前建 .bak\n\n坑：in_place=true + backup=false = 放弃了回滚能力，rollback 无从恢复。\n\n判据：不确定就 in_place=false 或至少保持 backup=true。`, 'param');

P('B', 'vt 参数能填什么',
  `只接受：byte / word / dword / qword（dualview 还支持 bytes:N）。\n\n坑：\n· 写 bytes 或 int 会 bad-arg\n· 大小写不统一（DWORD）可能不被接受\n· 用错宽度会读到错位的值（读 dword 但实际是 qword，高 4 字节丢失）\n\n判据：值和预期差一个数量级时，先怀疑 vt 宽度选错。`, 'param');

P('B', 'pa 和 addr 不要混用',
  `· addr = 虚拟地址（VA），用于 read/write/pa\n· pa = 物理地址（PA），只有 pread/pwrite 用\n\n坑：把 VA 当 PA 传给 pread，读出来是随机内存 —— 不报错，但值是垃圾。\n\n正确做法：要物理读先 kitty_km action=pa addr=<VA> 拿 pa，再用 pread。\n\n判据：pread 拿到的值和 KM_R 差很远，就是地址类型搞混了。`, 'param');

P('B', 'kitty_ce 的 ops 批量上限',
  `BATCH 上限 40 条，超过要拆批。\n\n坑：一批里有一条失败不影响其他条（逐条投递），所以看回包必须逐行看 \`#i\` 的状态，不能只看总 ok 数。\n\n判据：ok=<k> 小于 n 时，去 rows 里找哪一行不是 OK。`, 'param');

P('B', 'empty action 为什么有工具能过',
  `kitty_trail 的 append 在动作为空时是**通过**的（审计判据 empty=无）。\n\n坑：拿这个当通例会把别的工具搞坏 —— 其他工具的 action 都是必填。\n\n判据：不确定就看 schema 里 action 有没有 required: true。`, 'param');

// ===== C 桥契约坑（8）=====
P('C', 'ERR|need-range 反复出现',
  `两个 OP 硬要求显式区间：\n· S_NEW（扫描）—— 缺 → need-range；窗 ≤16MB、总 ≤64MB、≤4 窗\n· P_BACK（反查）—— 缺 → need-range；命中上限 200\n\n坑：给了 start/stop 还报，是**超限额**不是没给（最常见是拿整个地址空间当窗口）。\n\n正确做法：先 kitty_ce op=MODENUM 拿真实 size；size=0 时用镜像头 SizeOfImage 推；都不行给 16MB 兜底并分窗。\n\n判据：RANGE_INFO 能告诉你合法分配窗。`, 'bridge');

P('C', 'ERR|no-open 是什么意思',
  `当前没有挂上目标进程。\n\n坑：以为"刚才 OPEN 过"就一直有效 —— 宿主重启/target 退出后 open 状态会丢。\n\n正确做法：kitty_ce op=CUR 确认当前 pid，不对就 op=OPEN|<pid> 重挂。\n\n判据：CUR 回包里的 pid 和你以为的一致。`, 'bridge');

P('C', 'ERR|busy 说明什么',
  `上一条异步作业还没落定（扫描/反查多半是作业化的）。\n\n坑：看到 busy 就重发 —— 重发会顶掉上一条，结果是两个都没拿到。\n\n正确做法：kitty_ce op=JOB_STAT 轮询到 done，再取结果（S_GET / P_BACK_RES）。\n\n判据：JOB_STAT 的五态：none / no-job / running / done / error。`, 'bridge');

P('C', 'ERR|timeout 该怎么处理',
  `桥没在时限内回包，说明**通道层**有问题，不是参数问题。\n\n坑：timeout 后盲目重发同一条 —— 如果上一次其实执行了，重发会做两次（写操作尤其危险）。\n\n正确做法：\n1) kitty_status action=status 看 cmd/rep 时戳和 sync pending\n2) kitty_drv action=status 看双驱\n3) 恢复后用读操作确认上一次到底生效没有\n\n判据：timeout 之后的第一件事永远是"确认状态"，不是重发。`, 'bridge');

P('C', 'ERR|bad-arg 和 unknown-op 的区别',
  `· unknown-op → OP 名/action 名错（改名字）\n· bad-arg → 名字对但参数错（个数/类型/顺序）\n\n坑：混起来会南辕北辙 —— 改名字解决不了参数问题。\n\n正确做法：bad-arg 时用 kitty_ops filter=<OP名> 对签名逐段比。\n\n判据：签名里的 | 分段数就是参数个数，少一段或多一段都是 bad-arg。`, 'bridge');

P('C', 'ERR|too-big-rescan 怎么办',
  `S_NEXT 的交集重扫超过 PREV_CAP。\n\n坑：在上千候选集上硬 S_NEXT，一次都不成。\n\n正确做法：先 S_COUNT 看候选数 → 上千就缩窗口重扫，或换更具体的值 S_NEW。\n\n判据：候选数 > 50 就该先收敛，不是先 rescan。`, 'bridge');

P('C', 'ERR|no-target（P_WALK）',
  `P_WALK 从地址出发按偏移走一跳，没落到有效目标。\n\n坑：以为是自己 offset 算错，反复换 offset 试 —— 其实多数是这个候选根本不是指针。\n\n正确做法：换下一个候选；pchain 内部把这类归到 droppedBad，你手动跑时也该这么归类。\n\n判据：同一父下面大量 no-target，说明父地址本身可疑。`, 'bridge');

P('C', 'ERR|KM_PW-DENIED 是设计还是故障',
  `**设计**。pwrite 全入口永久拒绝：门禁层先拒、执行层纵深拒，accept 旗不再放行。\n\n坑：以为加 accept_engine_wedge=true 就能写 —— 不能，实测物理写会卡死 Lua 引擎（宿主活着但 tick 停摆）。\n\n正确做法：取证走 pread（物理读）+ R/KM_R 对照；要改值走 W 或 kitty_wpb。\n\n判据：回包固定 \`ERR|KM_PW-DENIED…\`，且落 logHostIncident('km-pwrite-blocked')。`, 'bridge');

// ===== D 宿主 / 驱动坑（10）=====
P('D', 'kitty_dbg attach 会不会把宿主搞挂',
  `**会**，这是已知行为（F-13）：本 build 的 debugProcess 会随机 0xc0000409 fail-fast 杀宿主。\n\n坑：不传 accept_host_loss=true 只报错；传了它就真调 \`DBG_ATTACH|iface|force|unsafe|async\`，然后可能杀宿主。\n\n正确做法：真调试走 kitty_x64dbg（C 通道）；A 通道调试面只用来 status / bp_list。\n\n判据：只要目的是"停在某处看数据"，就不该走这条路。`, 'host');

P('D', '重复 KM_ATTACH 有什么风险',
  `实现里有 attach-once：pid 和上次相同就**跳过**，不回包只说"跳过（attach-once 命中）"。\n\n原因：高频重复 KM_ATTACH 会诱发宿主丢失。\n\n坑：以为"跳过"是失败，于是反复重试 —— 恰好是最危险的行为。\n\n判据：看到"跳过"就是已附着，直接往下走。`, 'host');

P('D', '驱动状态 STOP_PENDING 能不能直接 start',
  `不能。STOP_PENDING 表示上一次 stop 还没落定。\n\n坑：硬 start 会叠加失败状态，越试越乱。\n\n正确做法：kitty_drv action=recover（修 STOP_PENDING，hostStart 控制是否重拉宿主）。\n\n判据：recover 后 status 里两个驱动都应是 RUNNING 或 STOPPED（不是 PENDING）。`, 'host');

P('D', 'storm 压测怎么算通过',
  `cycles 轮连续 PING（可选带 KM_ATTACH），任一丢失就触发看门狗并计数。\n\n坑：把"大部分成功"当通过 —— 只要有一轮丢失就说明该变体不稳。\n\n正确做法：cycles 默认 20（上限 100），**20 次零丢失**是基准线。\n\n判据：回包 incidents 列表必须为空。`, 'host');

P('D', 'CommIoInject 为什么不能用来注入',
  `它的设备驱动是 STOPPED（证书吊销，设备不存在）。\n\n实现里直接回：\`ERR|CommIoInject 所在驱动 STOPPED…；APC 链只做静态描述，不下发带参 IOCTL\`\n\n坑：反复 probe 等它起来 —— 它不会起来。\n\n正确做法：要注入走 kitty_inject 三档（ce / ps / loaddll）。\n\n判据：drvio status 里它就是 STOPPED，别浪费时间。`, 'host');

P('D', '什么时候必须重启宿主',
  `三个信号：\n· PING 连续丢失且看门狗拉不回\n· 出现过 engine-wedge（KM 写超时）\n· DBG_ATTACH 之后（已知会杀宿主）\n\n坑：重启后不归一化，残留指令还在队列里，后续指令会顶到残留上。\n\n正确做法：kitty_drv action=host hostStart=true，它会连带 SYNC_ARCHIVE + SYNC_STAT。\n\n判据：SYNC_STAT 四项归零才算干净。`, 'host');

P('D', '主驱起不来的排查顺序',
  `四层，顺序别换：\n1) kitty_drv action=status —— 看两个驱动的 SCM 状态\n2) 辅助驱（Private_Access）没 RUNNING → 主驱不会起，先修辅助\n3) STOP_PENDING → kitty_drv action=recover\n4) 反复失败 → kitty_init action=init reload=true 全量重建辅助驱\n\n坑：直接 start 主驱 —— 依赖没齐，必然失败。\n\n判据：辅助驱 RUNNING 是主驱能起的前提。`, 'host');

P('D', 'sid 变了之后为什么要重探活',
  `宿主重启后 pid 会变，A 通道的句柄/缓存全部失效。\n\n坑：重启后直接发指令 —— 会撞 timeout 或打到旧会话。\n\n正确做法：kitty_status probe=true 先探活，再往下。\n\n判据：回包里宿主 pid 和 BRIDGE_VER 都是新的才算就绪。`, 'host');

P('D', '变体的 exe 不存在怎么处理',
  `报 \`ERR|变体 exe 不存在：<path>\` 或 \`ERR|找不到变体\`。\n\n坑：手工改配置指向不存在的路径 —— 切换后所有调用都失败，且看不出根因。\n\n正确做法：kitty_variants action=list 看真实可用变体 id 与路径，再 switch。\n\n判据：list 里有的才能切。`, 'host');

P('D', '切换变体后立刻发指令为什么失败',
  `switch 是**下一次调用才生效**，不是立即。\n\n坑：切完马上发指令 —— 打到旧变体上，行为不可预期。\n\n正确做法：switch 之后 kitty_status probe=true 或 kitty_variants action=ensure-bridge 等桥就绪。\n\n判据：C 通道就绪看 bpl 行含 \`SENT[restored|kept]\`。`, 'host');

// ===== E 路径 / 编码坑（8）=====
P('E', '工作区根目录带括号为什么会导致工具失败',
  `根目录是 \`D:\\DrCE(26.2.16)\`，其中 \`(\` \`)\` 会让 **cmd.exe 提前断句**，而很多上游工具（Ghidra 的 analyzeHeadless.bat、jadx.bat、apkid.bat）都走 cmd。\n\n症状：exit_code=255 + GBK 乱码的"此时不应有 __\\vendor\\..."。\n\n正确做法：用 SUBST 建无括号的别名盘（如 X:）指向真实根，子进程路径全走别名（插件里的 ensureAsciiRoot 干这事）。\n\n判据：同一命令 exit_code=0。`, 'path');

P('E', 'jadx 报 exit 255 且日志乱码',
  `先判是路径问题还是编码问题：\n· 日志是 GBK 乱码 + 提到路径片段 → 括号路径坑，改走 via=java（\`java -cp <lib/*> jadx.cli.JadxCLI\`），绕开 .bat\n· 日志正常但报找不到类 → 依赖/classpath 问题\n\n坑：一看到 255 就重装 jadx —— 方向错了。\n\n判据：via=java 能过就证明是 .bat + 路径的问题。`, 'path');

P('E', 'APKiD 扫完显示没结果',
  `APKiD 把结果写在 **stderr**。\n\n坑：自己直接跑 apkid 不加 \`2>&1\`，看起来像"什么都没找到"。\n\n正确做法：走 kitty_apkscan（已合并 stdout+stderr）；手跑时记得重定向。\n\n判据：退出码正常但输出为空 = 输出被扔到 stderr 了。`, 'path');

P('E', 'dump 产物路径要注意什么',
  `必须 ASCII 路径，且不要放在含括号的根目录下。\n\n坑：路径报错但目录明明存在 —— 就是字符问题。\n\n正确做法：输出到工作区内如 \`logs\\dump-<ts>.bin\`。\n\n判据：换成纯 ASCII 短路径能过。`, 'path');

P('E', 'Ghidra 报版本或 JDK 问题',
  `它校验两件事：\n· SUPPORTED_GHIDRA_VERSION=12.1.4 —— **同 major.minor 即 compatible**（12.1.3 属 12.1.x，接受）\n· JAVA_MAJOR=21 —— 环境 JAVA_HOME 是 17 时必须给子进程覆盖成 21\n\n坑：看到 12.1.3 vs 12.1.4 就去升版本 —— 不需要。\n\n判据：版本同 major.minor、JAVA 21，两条齐了就不该是版本问题。`, 'path');

P('E', 'luadec 找不到',
  `它有两档：exe 或 jar。\n\n坑：只装了 jar 但没加 via=java —— 会去找 exe 然后报缺。\n\n正确做法：kitty_lua action=status 先看探到哪一档；只有 jar 就 via=java。\n\n判据：status 会明确报 exe/jar 的探测结果。`, 'path');

P('E', 'apktool 报 jar missing',
  `固定路径：\`vendor/apktool/apktool.jar\`，且必须有 java。\n\n坑：把 apktool.jar 放在别处 —— 工具只认这个路径。\n\n判据：status 会回 jar 的完整路径和 exists 状态。`, 'path');

P('E', '中文路径 / 中文参数会不会出问题',
  `会。子进程（cmd / java / python）对非 ASCII 路径的编码处理不一致，常见表现是文件名变成 ?? 或直接 not found。\n\n正确做法：所有交给外部工具的路径用 ASCII；中文只放在文件内容里。\n\n判据：路径含中文且报 not found 时，先把文件复制到 ASCII 路径再跑。`, 'path');

// ===== F 工具链 / 依赖坑（6）=====
P('F', 'REA 报 provider_unavailable',
  `三重原因，按序查：\n1) **provider 绑定陷阱**：inspect_binary_layout 固定绑 pwntools-elf（Linux x64 only），换 provider 无效 → 改走会话态 open_binary → binary_overview / list_procedures / analyze_function\n2) Ghidra 版本 12.1.x + JAVA 21\n3) 括号路径 → SUBST 别名\n\n判据：provider 名字对、版本 compatible、JAVA 21 三条都齐还报，才是 provider 侧真问题。`, 'dep');

P('F', 'REA 服务起不来',
  `三步：\n1) kitty_rea action=status\n2) action=start（首用懒启动）\n3) 装依赖：npm install --prefix <root>/vendor/rea rea-agents\n\n坑：list 返回空就以为没工具 —— 多半是 MCP 握手没成，看 start 的日志。\n\n判据：status 绿 + list 非空才算可用。`, 'dep');

P('F', 'REA 的 APK 线报缺 jadx-headless-mcp',
  `这条线需要调用方自备 \`jadx-headless-mcp\` 桥 JAR（无预编译 Release，须 Gradle 构建）。\n\n坑：等它自动装 —— 不会。\n\n等价路径：kitty_jadx / kitty_apktool / kitty_apkscan 都已实跑，够用。\n\n判据：走等价路径不影响结论。`, 'dep');

P('F', '预设包缺席报 vendor/dsh-reverse-security 未检出',
  `工作台依赖预设包在 vendor 下就位。\n\n坑：只拷了插件本体没拷 vendor —— 工具能注册但部分功能会集体报缺席。\n\n正确做法：确认 vendor/dsh-reverse-security 与 vendor/dsh-reverse-skill 都在。\n\n判据：报错里会指名是哪个包缺席。`, 'dep');

P('F', 'kitty_engines 回 unknown 是不是工具废了',
  `不是。unknown 是**正常兜底**：后缀 7 条、目录 6 条都不匹配时给 \`ENGINE=unknown NEXT=kitty_patch info + kitty_sym\`。\n\n坑：以为要换工具 —— 它已经把下一步给你了。\n\n正确做法：按 NEXT 走 info + imports，从节表和导入反推。\n\n判据：info 里节表正常但没引擎特征 = 自研/静态链接，按 native 逆向。`, 'dep');

P('F', 'kitty_selftest 某些项 FAIL 是不是环境坏了',
  `不一定：C 通道 SelfTest 的 savedata 需要 notepad 调试目标，**空载 DBG 上 FAIL 属预期**（脚本预置行为）。\n\n坑：看到 FAIL 就去重装环境。\n\n正确做法：区分"链路不通"和"用例缺目标"—— 后者换个目标跑就过。\n\n判据：bpl 行含 \`SENT[restored|kept]\` 即链路通。`, 'dep');

// ===== G 产物 / 数据坑（6）=====
P('G', 'dump 完一致率很低就一定是错了？',
  `不一定。三种正常偏低：\n· IAT 已解析（内存里是真实地址，文件里该是名称 RVA）\n· 重定位被应用过\n· 带壳（壳在运行时改代码段）\n\n坑：拿 99.9% 当唯一标准，把正确的 dump 判成坏的。\n\n正确做法：加 sections=true 做节级比对，定位是哪一节不一致；头 0x400 必须一致。\n\n判据：头部一致 + 文本段一致 + 只有 IAT/重定位段不同 = 正常。`, 'artifact');

P('G', 'dump 完的 PE 为什么不能直接运行',
  `dump 只做**布局重建**（VA→文件偏移），不做语义修复：\n· 不解引用 IAT（那是 Scylla 的活）\n· 不修复重定位\n\n坑：以为 unmap 完就是可用文件 —— 静态分析可以，运行不行。\n\n判据：交付表述要写"已重建布局，未修复导入/重定位"。`, 'artifact');

P('G', '补丁打错了怎么回滚',
  `靠原地补丁前自动建的 \`.bak\`。\n\n坑：backup=false 或 in_place=false 之后就没有 .bak —— rollback 无从恢复。\n\n正确做法：不确定的补丁先 in_place=false 出 .patched，验证通过再落原文件。\n\n判据：rollback 前先确认 .bak 存在。`, 'artifact');

P('G', 'expect 不匹配就一定是我算错了偏移？',
  `多数是，但也有两种正常情况：\n· 样本版本不同（同一个程序两个 build）\n· 目标位置在运行时被改过\n\n坑：硬改 expect 或去掉 expect 硬打 —— 这会失去唯一的位置保护。\n\n正确做法：重新 find 定位，核对版本哈希，再打。\n\n判据：expect 是保护，不是障碍。`, 'artifact');

P('G', '为什么补丁 KittyCE.exe 被拒',
  `内置白名单：补丁工具本体默认不许改，除非 force=true。\n\n后果：改坏了整条链路不可用，连 rollback 都可能失败。\n\n正确做法：复制一份改副本，不动原件。\n\n判据：force 只在明确知道自己做什么时才用。`, 'artifact');

P('G', '扫描结果不释放会怎样',
  `会一直占着上一次的候选集，下一次扫描顶着旧状态跑。\n\n坑：连续做多轮扫描不 S_FREE —— 第二轮的候选是脏的。\n\n正确做法：每次扫描会话结束（成不成都）S_FREE；中断场景 S_ABORT + S_FREE。\n\n判据：S_COUNT 归零才算清干净。`, 'artifact');

// ===== H 顺序 / 流程坑（10）=====
P('H', '为什么一定要先探活再动手',
  `因为宿主/驱动掉线时，所有指令都表现为 timeout 或乱回，而 timeout 之后你无法判断上一次到底执行了没有。\n\n正确顺序：kitty_status probe=true → kitty_drv status → 再发业务指令。\n\n坑：跳过探活直接跑 — 拿到的"失败"分不清是参数错还是环境挂。\n\n判据：PING 通 + sync 四项归零 + 宿主单实例，三条齐才动手。`, 'order');

P('H', '扫描族和指针链的完整顺序',
  `扫描：MODENUM 拿窗口 → S_NEW（显式区间）→ JOB_STAT 等落定 → S_GET → （值变）S_NEXT → S_FREE\n指针：resolveModuleWindow → P_BACK（显式窗口）→ JOB_STAT → P_BACK_RES → 双验证（读值 + P_WALK）→ 重启回验\n\n坑：跳过 MODENUM 直接给 16MB 兜底窗 —— 命中太多，收敛不了。\n\n判据：每步都能说出"这一步的回包哪一段决定下一步"。`, 'order');

P('H', '静态分析的顺序为什么不能换',
  `定性（info + die）→ 符号（imports/exports）→ 反编译 → 动态验证。\n\n坑：没定性就 dump/反编译 —— 带壳时拿到的是壳的内存镜像，后面全白做。\n\n判据：info 里出现 RWX 节 + VirtualSize/SizeOfRawData 异常 = 先脱壳，别往下走。`, 'order');

P('H', '调试前要先做什么',
  `三件：\n1) 目标进程已 OPEN（CUR 确认 pid）\n2) 模块窗口已知（MODENUM）\n3) 目标架构与调试器一致（32/64）\n\n坑：直接下断点 —— 断点挂在空会话上，回包看着成功但永不命中。\n\n判据：bp_list 有返回即通道通；回包里 pending 要等 DBG_WAIT。`, 'order');

P('H', '对抗门禁的顺序',
  `驱动守卫 → 宿主探活 → OPEN → KM_ATTACH → 模块窗口 → 三视图 → 写回环。\n\n坑：跳过前四步直接看三视图 —— 内核面没打开，KM_R 全空，结论是假的。\n\n判据：gate 五态里 host-down 是最前面的失败，先修它再看别的。`, 'order');

P('H', '为什么先记录目标再动手',
  `双字段分开定：sessionGoal（会话目标）+ target（目标进程）。\n\n坑：两栏写成一样 —— 目标进不了 triage/报告，或进程名进了报告文本。\n\n判据：target-get 两个字段都非空且不相等。`, 'order');

P('H', '收口序列是什么',
  `target-set → task-dispatch{type:finish,evidence:[…]} → task-close。\n\n坑：\n· 不 finish 直接 close → 缺终态证据\n· 中途 close → 留下 open task\n\n判据：task-get 里阶段到"完成"且有 evidence 才 close。`, 'order');

P('H', '什么时候不该用一键编排',
  `探索阶段：\n· 中间要看结果再决定分支\n· 目标行为异常，自动流水会掩盖问题\n\n坑：一上来 acescan / loop —— 出红也只是红，看不出是哪一步的前提没满足。\n\n判据：手工能说清每步为什么，再交给编排固化。`, 'order');

P('H', '改内存在扫描前后要注意什么',
  `扫描依赖值稳定；改值会污染候选集。\n\n坑：扫描进行中改内存 —— 候选集被污染，S_NEXT 的交集结果不可信。\n\n正确做法：扫描 → 落定 → 取值 → 再改；改完要重启扫描会话（S_FREE + S_NEW）。\n\n判据：改值后必须重新扫，不要在旧候选集上继续。`, 'order');

P('H', '同一个错重试是不是好办法',
  `不是。桥层的错分三类，重试只对一类有用：\n· 参数/名字错（unknown-op / bad-arg / need-range）→ 重试无效，必须改参数\n· 状态错（no-open / busy）→ 先修状态再重试\n· 瞬时错（timeout / 宿主抖动）→ 可以恢复后重试，但要先确认上次是否生效\n\n判据：同一条指令连续失败两次，就该停下来查根因，而不是换参数瞎试。`, 'order');

fs.mkdirSync('train/data/re-iter', { recursive: true });
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');
const byClass = out.reduce((a, x) => (a[x.meta.__class] = (a[x.meta.__class] || 0) + 1, a), {});
const chars = out.reduce((s, x) => s + JSON.stringify(x.messages).length, 0);
console.log(JSON.stringify({
  out: OUT, samples: out.length, by_class: byClass,
  total_chars: chars, avg_chars: Math.round(chars / out.length),
}, null, 1));

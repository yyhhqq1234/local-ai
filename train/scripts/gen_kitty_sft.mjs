#!/usr/bin/env node
/**
 * gen_kitty_sft.mjs — 从 kitty 工作台契约生成 SFT 训练对（v2 扩量）
 *
 * 输入：
 *   ops.json          66 条 OpSpec {op,sig,reply,note,group}
 *   tools.json        64 条工具 {name,channel,actions,ops,description}
 *   tool-tasks.json   64 工具的真实使用场景（人工编写）
 *
 * 六类样本：
 *   A params  参数拼法   每 OP 4 变体
 *   B reply   回包判读   每 OP 2 变体
 *   C err     错误回包处置（ERR|need-range / no-open / km-pw / 闸门）
 *   D gate    闸门拒绝   5 条硬约束 × 4 问法
 *   E tool    工具选用   64 工具全量 × 每个场景
 *   F chain   多步链路   真实工作流
 *
 * 输出：train/data/kitty-contracts/sft-kitty.jsonl
 */
import fs from 'node:fs';

const DIR = 'train/data/kitty-contracts';
const ops = JSON.parse(fs.readFileSync(`${DIR}/ops.json`, 'utf8'));
const tools = JSON.parse(fs.readFileSync(`${DIR}/tools.json`, 'utf8'));
const toolTasks = JSON.parse(fs.readFileSync(`${DIR}/tool-tasks.json`, 'utf8'));

const SYS = '你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。';

const MODULES = ['kitty-target.exe', 'GameClient.exe', 'Sample.dll', 'notepad2.exe'];
const ADDRS = ['0x7FF6DADB2450', '0x7FF75FCD1040', '0x1A4F2C00400', '0x7FF6DADB01A0', '0x2C1B7F40200'];
const PIDS = ['7412', '18804', '30216'];
const VTS = ['dword', 'qword', 'byte', 'word'];
const VALS = ['100', '3500', '60', '1'];

const pick = (arr, i) => arr[i % arr.length];

const OP_SEMANTICS = {
  PING: ['探活工具链是否在线', '确认通道是否活着', '看宿主还在不在'],
  OPEN: ['把目标进程挂上', '切换当前目标', '重新打开靶标'],
  CUR: ['确认当前挂的是哪个进程', '核对当前目标 pid'],
  R: ['读一段内存', '取一个 dword 值', '读模块头四个字节'],
  W: ['写一个值并回读', '改内存里的数值', '把值写回去验证'],
  ALLOC: ['在目标里分配一块内存', '申请远程缓冲'],
  FREE: ['释放刚分配的内存', '回收远程缓冲'],
  MEMDUMP_HEX: ['把一段内存导出来看原始字节', '取 64 字节十六进制'],
  MODENUM: ['列出模块窗口', '拿主模块基址和大小'],
  MODBASE: ['查某个模块的加载基址', '拿 dll 基址'],
  S_NEW: ['按已知值开一次精确扫描', '扫描初值建候选集'],
  S_GET: ['取扫描结果', '把命中地址拉出来'],
  S_FREE: ['释放扫描会话', '清掉扫描结果'],
  S_SNAP: ['先打快照再看变化', '未知初值扫描的第一步'],
  S_CHANGED: ['取变了的地址', '收敛候选'],
  S_UNCHANGED: ['取没变的地址', '继续收敛候选'],
  P_BACK: ['反查谁指向这个地址', '找指针来源'],
  P_BACK_RES: ['取反查结果', '把命中列表拉出来'],
  P_WALK: ['按偏移回验一条链', '验证指针链是否成立'],
  BATCH: ['一次投递多条指令', '批量省往返'],
  SYNC_ARCHIVE: ['把残留指令归档', '收尾清队列'],
  SYNC_STAT: ['看同步队列是否归零', '确认没有残留'],
  JOB_STAT: ['查异步作业状态', '确认扫描落定了没'],
  BRIDGE_VER: ['确认桥版本', '核对通道协议版本'],
  LUA: ['跑一段 Lua 做组合操作', '在 CE 里执行脚本'],
  KM_API: ['枚举内核可用面', '看 dbk_* 有几条可用'],
  KM_INFO: ['看内核路由状态', '确认 PEProcess 是否可访问'],
  KM_ATTACH: ['内核态打开目标', '建立内核路由'],
  KM_R: ['走内核路由读一次', '与用户态读做对照'],
  KM_W: ['走内核路由写并回读', '内核路由写验证'],
  KM_PA: ['把虚拟地址翻成物理地址', 'VA 转 PA'],
  KM_PR: ['物理地址读', '绕开页表读一次'],
  KM_MODE: ['设置内核路由模式', '调整 km 标志'],
  DBG_ATTACH: ['挂调试器', '建立调试会话'],
  DBG_BP: ['下断点', '在目标地址设断'],
  DBG_BP_LIST: ['列断点', '看已下的断点'],
  DBG_BP_DEL: ['删断点', '撤掉某个断点'],
  DBG_GO: ['继续执行', '让目标跑起来'],
  DBG_REGS: ['取寄存器', '看当前上下文'],
  DBG_DETACH: ['脱调试器', '结束调试会话'],
  DBG_WAIT: ['等断点命中', '阻塞等事件'],
  DBG_STAT: ['查调试状态', '看是否已附加'],
  KM_PW: ['物理地址写', '直接改物理内存'],
};

const GATES = [
  { op: 'KM_PW', why: 'KM_PW 默认拒绝：实测物理写会卡死 Lua 引擎（宿主活着但 tick 停摆），恢复只能重启宿主。',
    alt: '改走 W（用户态写，带回读校验），写保护拦住了再上 kitty_wpb 走 PTE 直改。' },
  { op: 'S_NEW', why: 'S_NEW 必须给显式区间，缺了回 ERR|need-range；单窗 ≤16MB、总量 ≤64MB、最多 4 窗。',
    alt: '先 MODENUM 拿主模块窗口，用 base~base+size 当区间，别把整个地址空间塞进去。' },
  { op: 'P_BACK', why: 'P_BACK 同样必须显式窗口，缺了回 ERR|need-range，命中上限 200。',
    alt: '窗口按模块实际大小给，命中超 200 就缩窗重查，不要靠加大窗口硬撞。' },
  { op: 'DBG_ATTACH', why: 'DBG_ATTACH 是双层闸门，而且本 build 的 debugProcess 会随机 fail-fast 杀宿主（F-13），附加期间引擎锁还会阻塞 tick。',
    alt: '真调试优先走 C 通道 kitty_x64dbg，A 通道的调试面只做状态查询。' },
  { op: 'KM_MODE', why: 'KM_MODE off 只清标志位，CE 没有真正的回退 API —— 要如实回报，不能说"已回滚"。',
    alt: '如实说明只清了标志，内核路由的实际状态以 KM_INFO 重查结果为准。' },
];

const ERRORS = [
  { code: 'ERR|need-range', why: '区间没给或超出限额', fix: '按 MODENUM 的实际窗口给显式 start/stop，单窗不超过 16MB' },
  { code: 'ERR|no-open', why: '还没有挂上目标进程', fix: '先 OPEN|<pid> 挂上再发这条' },
  { code: 'ERR|km-pw-requires-force', why: '物理写被默认拒绝', fix: '不要加 force 硬过，改走 W 或 kitty_wpb' },
  { code: 'ERR|no-attach', why: '调试会话没建立', fix: '先 DBG_ATTACH，或改用 kitty_x64dbg 走 C 通道' },
  { code: 'ERR|busy', why: '上一条异步作业还没落定', fix: 'JOB_STAT 确认状态，落定后再发下一条' },
  { code: 'ERR|bad-arg', why: '参数个数或类型不对', fix: '按 kitty_ops 的签名逐段对位，vt 只取 byte/word/dword/qword' },
  { code: 'ERR|unknown-op', why: 'OP 名拼错', fix: '本地早拒就是为这个——按 kitty_ops 过滤前缀查真实名字' },
  { code: 'ERR|timeout', why: '桥没在时限内回包', fix: 'kitty_status 探一次健康，别盲目重发' },
];

function concretize(sig, i) {
  return sig
    .replace(/<addr>/g, pick(ADDRS, i))
    .replace(/<vt>/g, pick(VTS, i))
    .replace(/<val>/g, pick(VALS, i))
    .replace(/<pid[^>]*>/g, pick(PIDS, i))
    .replace(/<start>/g, '0x7FF6DADB0000')
    .replace(/<stop>/g, '0x7FF6DAEB0000')
    .replace(/<len[^>]*>/g, '64')
    .replace(/<name>/g, pick(MODULES, i))
    .replace(/<模块名>/g, pick(MODULES, i))
    .replace(/<pa>/g, '0x1A4F2C00400')
    .replace(/<off>/g, '352')
    .replace(/<n>/g, '20')
    .replace(/<path[^>]*>/g, 'D:\\\\dump\\\\mod.bin')
    .replace(/<源码>/g, 'return readInteger("0x7FF6DADB2450")')
    .replace(/[<>]/g, '');
}

const out = [];
function add(kind, user, assistant, extra = {}) {
  out.push({
    id: `kitty-${kind}-${String(out.length).padStart(4, '0')}`,
    messages: [
      { role: 'system', content: SYS },
      { role: 'user', content: user },
      { role: 'assistant', content: assistant },
    ],
    meta: { __stage: 're', __kind: kind, ...extra },
  });
}

// ---------- A 参数拼法（每 OP 4 变体）----------
ops.forEach((o, i) => {
  const sem = OP_SEMANTICS[o.op];
  if (!sem) return;
  for (let v = 0; v < 4; v++) {
    const intent = sem[v % sem.length];
    const cmd = o.op === 'BATCH'
      ? 'kitty_ce ops=["PING","CUR","MODENUM"]'
      : `kitty_ce op=${concretize(o.sig, i + v)}`;
    const reply = o.reply.replace(/</g, '').replace(/>/g, '');
    const note = o.note ? `\n注意：${o.note.replace(/\*\*/g, '')}` : '';
    add('params', `${intent}，A 通道怎么发？`,
      `${cmd}\n\n判读：回包形态是 \`${reply}\`。先看首段是不是 OK，再按位取后面的字段。${note}\n下一步按回包决定：ERR 就按错误码修参数，OK 就把值/地址取出来往下走。`,
      { op: o.op, variant: v });
  }
});

// ---------- B 回包判读 ----------
const REPLY_CASES = ops.filter(o => o.reply && o.reply.length > 6);
REPLY_CASES.forEach((o, i) => {
  const raw = o.reply.replace(/</g, '').replace(/>/g, '');
  for (let v = 0; v < 2; v++) {
    const parts = raw.replace(/^OK\|?/, '').split('/');
    const body = (parts[v % parts.length] || parts[0] || raw).trim();
    const fake = 'OK|' + (body || raw.split('/')[0]);
    add('reply', `这条回包什么意思：\`${fake}\``,
      `这是 ${o.op} 的回包。\n\n拆字段：首段 ${fake.split('|')[0]} 是状态位，后面按契约 \`${raw}\` 逐段对位。\n${o.note ? `关键约束：${o.note.replace(/\*\*/g, '')}\n` : ''}\n据此能做的下一步：状态 OK 就把字段里的地址/数值/数量取出来当下一步输入；出现 ERR 先按错误码修参数，不要在同一处重试。`,
      { op: o.op, variant: v });
  }
});

// ---------- C 错误回包处置 ----------
ERRORS.forEach((e, i) => {
  const scene = [
    `执行时报了 ${e.code}，怎么处理`,
    `回包是 ${e.code}，是不是参数给错了`,
    `为什么会拿到 ${e.code}`,
  ];
  scene.forEach((s, j) => {
    add('err', s,
      `${e.code} 的含义：${e.why}。\n\n处置：${e.fix}\n\n不要做的：不要在同一个错上重复发同一条指令，桥侧不会因为重试而变成可执行；也不要靠加 force 硬过闸门。`,
      { code: e.code, variant: j });
  });
});

// ---------- D 闸门拒绝 ----------
GATES.forEach((g) => {
  const asks = [
    `直接 ${g.op} 把那个值改掉，别绕了`,
    `用 ${g.op} 一把梭，快一点`,
    `给我 ${g.op} 的完整命令，我现在就要写进去`,
    `别人都是 ${g.op} 直接过的，你也给我发`,
  ];
  asks.forEach((ask, j) => {
    add('gate', ask,
      `这条不能这么走。${g.why}\n\n替代路径：${g.alt}\n\n如果确实要越过这条限制，必须显式确认参数，并在回包里核对 verified 字段——只看到 OK 不算成功。`,
      { op: g.op, variant: j });
  });
});

// ---------- E 工具选用（64 工具全量）----------
tools.forEach((t) => {
  const tasks = toolTasks[t.name];
  if (!tasks || !tasks.length) return;
  tasks.forEach((task, j) => {
    const act = t.actions.filter(a => !['status'].includes(a)).slice(0, 4).join(' / ') || t.actions.join(' / ');
    add('tool', task,
      `${t.name} — action 取 ${act}。\n\n选它的理由：${t.description}（通道 ${t.channel}）。\n参数要点：先把目标定死（pid 或模块名/路径），只读类先 status 探一次，动手类一次给全参数再发。\n判据：回包先看首段 OK/ERR，再取关键字段决定下一步；ERR 不要原地重试，按错误码修参数。`,
      { tool: t.name, channel: t.channel, variant: j });
  });
});

// ---------- F 多步链路 ----------
const CHAINS = [
  { q: '我要定位血量但不想全地址扫一遍，给一条不超时的打法。',
    a: `先限窗口再扫，别给全地址空间。\n\n第一步拿主模块真实窗口：\nkitty_ce op=MODENUM\n（size 可能为 0，要用镜像头兜底算）\n\n第二步按已知值精确扫，区间必须显式给：\nkitty_ce op=S_NEW|dword|3500|0x7FF6DADB0000|0x7FF6DAEB0000\n\n第三步取命中：\nkitty_ce op=S_GET\n\n第四步改值回验：\nkitty_ce op=W|0x7FF6DADB2450|dword|100\n\n判据：W 回 OK|verified|<回读值> 且回读等于新值才算写成功；只回 OK 不算。` },
  { q: '血量地址拿到了，怎么找指针链。',
    a: `三步：反查 → 验证 → 重启回验。\n\n1) 反查谁指向它（窗口显式给，命中上限 200）：\nkitty_ce op=P_BACK|0x7FF6DADB2450|0x7FF6DADB0000|0x7FF6DAEB0000\nkitty_ce op=P_BACK_RES|20\n\n2) 候选里挑落在模块静态区的，按偏移回验：\nkitty_ce op=P_WALK|0x7FF6DADB01A0|352\n\n3) 重启目标后重走同一条链，仍能取到才算稳定。\n\n判据：P_WALK 末端地址等于目标地址，且重启后重算一致。只对一次不算链成立。` },
  { q: '读写结果和内存实际不一致，怀疑有 hook。',
    a: `用三视图门禁对比，不要凭感觉。\n\nkitty_dualview addr=0x7FF6DADB2450 vt=dword samples=3\n\n它在同址取三路：R（用户态）、KM_R（内核路由）、KM_PR（经 KM_PA 的物理读）。\n\n判据：\n· 三路一致 → 无视图分叉，问题在别处\n· R 与 KM_R 不一致 → 用户态视图被改，重点查 hook\n· KM_R 与 KM_PR 不一致 → 页表层有问题，怀疑 PTE 级拦截\n\n证据落在 logs/anti-ace-<date>.jsonl。` },
  { q: '目标页是只读，写不进去。',
    a: `两条路，先走轻的。\n\n路一：改保护属性再写\nkitty_prot action=protect addr=0x7FF6DADB2450 size=4096 protect=rwx confirm=true\n写完还原原属性。\n\n路二（保护被反复刷回时）：PTE 直改\nkitty_wpb addr=0x7FF6DADB2450 vt=dword val=100 accept_protection_bypass=true\n它走 DTB→物理→PTE，不经保护 API、不需要目标句柄，写完默认还原 PTE。\n\n判据：写完必须回读，回读等于目标值才算成。` },
  { q: '新到一个样本，先干什么。',
    a: `先静态定性再动手。\n\n1) 基础信息 + 节表：\nkitty_patch action=info path=<样本>\n判据：任一节 VirtualSize/SizeOfRawData > 3 且 Characteristics 含 0xE0000020（RWX）→ 定加密壳。\n\n2) 壳/编译器指纹：\nkitty_die action=scan target=<样本>\n\n3) 符号面：\nkitty_sym action=imports path=<样本>\n\n4) 有壳先脱再分析，无壳直接进反编译。\n\n顺序不能反：没定性就 dump，出来的是壳的内存镜像，重建一致率会很低。` },
  { q: '要 dump 主模块并验证完整性。',
    a: `dump 必须带重建。\n\nkitty_dump module=kitty-target.exe unmap=true reference=<原始文件> path=logs\\\\dump-<ts>.bin\n\n它会按节表重建磁盘格式 → 可选从 ILT 回填 IAT → 给与参考文件的逐字节一致率。\n\n判据：\n· 一致率接近 1.0 → 重建正确\n· 明显偏低 → 检查是否带壳（壳会改代码段）或 IAT 未回填\n\n加 sections=true 可额外导出节级 bin 做定点比对。` },
  { q: '驱动掉线了，宿主也不响应。',
    a: `按依赖顺序拉，别乱重启。\n\n1) 看状态：kitty_drv action=status\n2) 自愈（单实例重拉 + PING + SYNC 归一）：kitty_drv action=host\n3) 还不行重走初始化：kitty_init action=init mode=kernel\n4) 故障演练验链路：kitty_selftest group=a\n\n判据：PING 通 + SYNC_STAT 四项归零 + 宿主单实例，三条都满足才算恢复。` },
  { q: '要一次发多条指令省往返。',
    a: `用 BATCH。\n\nkitty_ce ops=["PING","CUR","MODENUM","R|0x7FF6DADB2450|dword"]\n\n回包是 OK|batch|<n>|ok=<k>，之后每条一行 \`#i|…\`。\n\n关键语义：单条失败不影响其余，所以要逐行看 \`#i\` 的状态，不能只看总 ok 数。上限 40 条，超过拆批。` },
  { q: '扫描跑了很久还没结果。',
    a: `先确认是不是还在跑，别重复投。\n\nkitty_ce op=JOB_STAT\n\n判据：\n· pending → 还在跑，等桥侧自动落定\n· done → S_GET 取结果\n· err → 看错误码，多半是区间没给对（need-range）\n\n收尾配 S_FREE，否则下一次扫描会顶着上一次的候选集。` },
  { q: '要确认工具链自己是不是健康的。',
    a: `分两层看。\n\n通道（只读快照）：kitty_status action=status\n带一次实探：kitty_status probe=true\n宿主+双驱：kitty_drv action=status\n完整回归：kitty_selftest group=all\n\n判据：cmd/rep 时戳在走 + sync pending=0 + KittyCE 进程在，三条齐了才算健康。` },
  { q: '要在 Android 上 hook 一个方法看参数。',
    a: `先静态看清类和方法签名，再挂 hook。\n\n1) 反编译定位：kitty_jadx action=decompile target=app.apk\n2) 查壳：kitty_apkscan action=scan target=app.apk\n   有壳先脱（kitty_unpack action=collect/parse）再继续。\n3) 动态：kitty_frida action=attach pkg=<包名> script=<hook.js>\n\n判据：hook 命中后打印的参数类型要和静态签名对得上，对不上说明重载选错了，用 overload_index 指定。` },
  { q: 'Unity IL2CPP 游戏要还原类结构。',
    a: `标准链路：定位 → dump → 解析。\n\n1) 确认是 IL2CPP：kitty_engines path=<游戏目录>\n2) dump：kitty_il2cppdumper action=dump so=<libil2cpp.so> meta=<global-metadata.dat> out=<目录>\n   或走 Cpp2IL：kitty_cpp2il action=dump gameDir=<目录>\n3) 解析产物看 dump.cs 里的类/字段/方法偏移。\n\n判据：dump 出来的类数和静态搜索到的类名字面量数量要对得上，差太多说明 metadata 版本不匹配。` },
  { q: 'UE 游戏想拿 SDK 偏移。',
    a: `先 triage 再 dump。\n\n1) kitty_uedump action=triage gameDir=<目录>（确认 UE 版本 / GObjects 偏移）\n2) kitty_uedump action=dump pid=<pid> sdkDir=<输出>\n3) pak 里的资产：kitty_fmodel action=list pakDir=<目录>（加密 pak 要 aesKey）\n\n判据：SDK 里 UWorld/GNames 偏移能在运行时验证通过才算 dump 正确。` },
  { q: '要打一个指令补丁并留回滚。',
    a: `补丁三件套：expect + 备份 + 校验。\n\n1) 定位：kitty_patch action=find path=<样本> pattern="48 8B ?? 05"\n2) 校验+打：\nkitty_patch action=patch path=<样本> at=0x<文件偏移> expect="48 8B 05" bytes="31 C0 90" confirm=true\n   expect 会校验原字节，不匹配直接拒写。\n3) 回滚点：kitty_patch action=rollback path=<样本>\n\n判据：打完重新 action=hash 比对，且 expect 字节确实被替换。` },
  { q: '要确认加固 APK 到底加了什么壳。',
    a: `分层判断，别只看一个工具。\n\n1) kitty_apkscan action=scan target=app.apk（APKiD 指纹）\n2) kitty_jadx action=decompile target=app.apk → 看 Application 类和 dex 数量\n3) 壳特征：dex 极小 + native loader + v.m.p/stub 类 → 走 kitty_unpack 收口\n\n判据：能正常解出业务 dex 且 Application 指向业务类，才算脱干净；只脱出壳 dex 不算。` },
  { q: '要在 REA 上做函数级对比。',
    a: `先取两侧 Evidence，再比。\n\n1) 左侧：kitty_rea_function procedure=<符号或地址>\n2) 右侧：同命令在另一版本上取\n3) 对比：kitty_rea_compare left=<Evidence> right=<Evidence>\n\n判据：对比输出要能定位到具体基本块差异，只说"相似度 0.8"没有定位就不算完成。` },
  { q: '要把一次分析过程留痕，便于工作台跟进。',
    a: `用 trail + G3 两条道。\n\n过程留痕（每步）：\nkitty_trail action=append sessionGoal=<目标> target=<靶标> step=<动作> text=<事实摘要>\n\n结论落模型：\nreverse_add_target → reverse_add_intent → reverse_add_obs（finding 必须带 reproSteps）\n补丁走 reverse_add_patch，产物走 reverse_add_asset。\n\n判据：report 时能从 target 顺链条查到每条 finding 的 repro 步骤，才算留痕完整。` },
  { q: '会话切过来，怎么定目标和靶标。',
    a: `双字段分开填，别混。\n\nkitty_settings action=target-set sessionGoal=<本次要达成什么> target=<进程名/路径/URL>\n\n规则：\n· 会话目标只进 triage/交接/报告/trail 文本\n· 目标进程才进 OPEN/扫描/读写/指针/对抗/转储\n· 两栏写成一样就是错\n\n只读确认：kitty_settings action=target-get / mode-get` },
  { q: '要把一整套对抗门禁跑一遍看有没有拦截面。',
    a: `一条命令串起来。\n\nkitty_acescan target=<pid或名> module=<模块> vt=dword samples=3 writeback=true attach=true\n\n它做：驱动守卫 → 宿主探活 → OPEN → KM_ATTACH → 模块窗口 → 三视图门禁（R/KM_R/KM_PR）→ 写回环 → 落 logs\\\\acescan-<ts>.json\n\n判据：gate=green 且写回全通 = 无拦截面；任一红就按日志里那一项的 ERR 定位是哪一层被拦。` },
  { q: '要在不触发保护告警的前提下改一个字节。',
    a: `走 PTE 直改，不碰保护 API。\n\nkitty_wpb addr=0x7FF6DADB2450 hex="90 90 90" accept_protection_bypass=true restore=true\n\n原理：DTB→物理走表→定位 PTE→经 MmPteBase 自映射改 R/W→写入→还原 PTE。不发 protect 调用、不需要目标句柄。\n\n判据：写完回读等于目标字节，且 PTE 已还原（restore=true）。NOACCESS 或换出页要加 permissive=true。` },
];
CHAINS.forEach((c, i) => add('chain', c.q, c.a, { chain: i }));

// ---------- 落盘 ----------
fs.mkdirSync(DIR, { recursive: true });
const OUT = `${DIR}/sft-kitty.jsonl`;
fs.writeFileSync(OUT, out.map(x => JSON.stringify(x)).join('\n') + '\n');

const kinds = out.reduce((a, x) => (a[x.meta.__kind] = (a[x.meta.__kind] || 0) + 1, a), {});
const chars = out.reduce((s, x) => s + JSON.stringify(x.messages).length, 0);
console.log(JSON.stringify({
  out: OUT,
  samples: out.length,
  by_kind: kinds,
  total_chars: chars,
  avg_chars: Math.round(chars / out.length),
  ops_covered: new Set(out.filter(x => x.meta.op).map(x => x.meta.op)).size,
  tools_covered: new Set(out.filter(x => x.meta.tool).map(x => x.meta.tool)).size,
}, null, 1));

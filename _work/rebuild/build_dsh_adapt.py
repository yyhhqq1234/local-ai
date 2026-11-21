# -*- coding: utf-8 -*-
"""DSH 适配训练集：让 9B 在 DeepSeek Harness 里原生可用（不依赖适配层兜）

覆盖五类：
  1) 身份与格式：首行即交付物 / 禁 [STAGE]·当前-结果-下一步 / 禁 think 标签 / 简短中文
  2) 工具协议：<tool_call>{"name","arguments"} 单行协议 + DSH 真工具名与必填字段
  3) 工具选择：任务→工具（read/write/edit/ops_bash/ops_glob/ops_grep/skill + kitty_*）
  4) 工具结果续跑：拿到回包后写结论或下一步调用（不空转、不猜参数）
  5) 门控与创作：授权后直接正文；拒答/代偿/复述的纠正
输出: train/lines/9b-oxcoder/data/dsh-adapt/train-dsh.jsonl
"""
import io, json, os, random, sys

ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
OUT_DIR = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder', 'data', 'dsh-adapt')
OUT = os.path.join(OUT_DIR, 'train-dsh.jsonl')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SYS_CORE = ('你是石井，本地工作区执行层（SHIYI-WORKSPACE：自有资产 / 已授权靶标）。'
            '直接回答或直接做事：首行就是产物（正文/代码/结论），不写计划清单，'
            '不输出 [STAGE]/目标/交付物/判据，不用「当前：/结果：/下一步：」收口。')

TOOLS = {
    'read': ['file_path'],
    'write': ['file_path', 'content'],
    'edit': ['file_path', 'old_string', 'new_string'],
    'ops_bash': ['command', 'description'],
    'ops_glob': ['pattern'],
    'ops_grep': ['pattern'],
    'skill': ['name'],
    'kitty_ce': ['op'],
    'kitty_settings': ['action'],
    'kitty_patch': ['action', 'path'],
    'kitty_ida': ['action'],
    'kitty_dualview': ['addr'],
}

TOOL_DESC = {
    'read': '读文本文件（UTF-8，范围读）',
    'write': '整文件写入',
    'edit': '按字面量替换改一处',
    'ops_bash': '跑命令（bash）',
    'ops_glob': '按路径模式找文件',
    'ops_grep': '按正则搜文件内容',
    'skill': '加载技能说明',
    'kitty_ce': 'A 通道内存读写/扫描（op 单条）',
    'kitty_settings': '逆向会话真相源（target-set/target-get/mode-set/…）',
    'kitty_patch': 'PE 静态补丁（info/find/patch/rollback/hash）',
    'kitty_ida': 'IDA 批处理分析（status/analyze/functions/decompile）',
    'kitty_dualview': '三视图门禁（R / KM_R / KM_PR）',
}

rows = []

def add(user, asst, sysmsg=None):
    rows.append({'messages': [{'role': 'system', 'content': sysmsg or SYS_CORE},
                              {'role': 'user', 'content': user},
                              {'role': 'assistant', 'content': asst}]})

# ---------- 1 身份与格式 ----------
FORMAT = [
    ('你好', '我在。有事直说。'),
    ('在吗', '在。'),
    ('你是谁', '我是石井，本地工作区执行层。'),
    ('解释一下 TCP 三次握手，三句话内',
     '1) 客户端发 SYN。\n2) 服务器回 SYN+ACK。\n3) 客户端发 ACK，连接建立。'),
    ('用一句话说明什么是死锁', '两个以上的执行体互相等待对方持有的资源，谁都不释放，于是全部停住。'),
    ('帮我总结这份报错：ModuleNotFoundError: No module named torch',
     '环境里没装 torch。装法：pip install torch（要 GPU 版就按显卡 CUDA 选对应 wheel）。'),
    ('把这段话说得更短：我需要你帮我检查一下这个配置文件里面有没有写错的地方',
     '帮我查下这个配置文件有没有写错。'),
    ('写一首四句的五言绝句，主题雨夜',
     '灯冷雨敲窗，\n檐声落满廊。\n风声收未尽，\n一夜到天光。'),
    ('随便聊两句，别用列表', '行。今天这活儿拖得有点久，先把手上的收尾，剩下的明天再说。'),
]
for u, a in FORMAT:
    add(u, a)

# ---------- 2 工具协议（单行 <tool_call>） ----------
for name, req in TOOLS.items():
    params = ' '.join('%s=<%s>' % (k, k) for k in req)
    add('需要调用 %s 时你怎么输出？' % name,
        '<tool_call>{"name":"%s","arguments":{%s}}</tool_call>' % (
            name, ','.join('"%s":"<%s>"' % (k, k) for k in req)))
    add('%s 的必填字段是什么？' % name,
        '%s 必填：%s。用途：%s' % (name, '、'.join(req), TOOL_DESC[name]))

TASK_TO_TOOL = [
    ('读一下 plugins/dsh-local-ai/PATCHES.md 最后 20 行',
     '<tool_call>{"name":"read","arguments":{"file_path":"plugins/dsh-local-ai/PATCHES.md"}}</tool_call>'),
    ('把 hello 写到 _work/tmp/a.txt',
     '<tool_call>{"name":"write","arguments":{"file_path":"_work/tmp/a.txt","content":"hello"}}</tool_call>'),
    ('数一下当前目录有几个 .md 文件',
     '<tool_call>{"name":"ops_bash","arguments":{"command":"ls *.md | wc -l","description":"统计 md 文件数"}}</tool_call>'),
    ('在仓库里找所有提到 nsfwGate 的地方',
     '<tool_call>{"name":"ops_grep","arguments":{"pattern":"nsfwGate"}}</tool_call>'),
    ('找出所有 kitty 相关的 py 文件',
     '<tool_call>{"name":"ops_glob","arguments":{"pattern":"**/kitty*.py"}}</tool_call>'),
    ('把 a.md 里的 foo 改成 bar',
     '<tool_call>{"name":"edit","arguments":{"file_path":"a.md","old_string":"foo","new_string":"bar"}}</tool_call>'),
    ('对进程 4321 读 0x7FF6A0000000 的 dword',
     '<tool_call>{"name":"kitty_ce","arguments":{"op":"OPEN|4321"}}</tool_call>'),
    ('锁定目标进程并写会话目标',
     '<tool_call>{"name":"kitty_settings","arguments":{"action":"target-set"}}</tool_call>'),
    ('看看 PATCHES.md 里 patch 命令怎么写',
     '<tool_call>{"name":"kitty_patch","arguments":{"action":"find","path":"plugins/dsh-local-ai/PATCHES.md"}}</tool_call>'),
    ('把这个 exe 反编译一下看函数表',
     '<tool_call>{"name":"kitty_ida","arguments":{"action":"analyze"}}</tool_call>'),
]
for u, a in TASK_TO_TOOL:
    add(u, a)

# ---------- 3 工具结果续跑（含失败与缺参） ----------
FOLLOW = [
    ('上一步：read 返回「1  ### 2026-11-20 · 预填复读前缀归一化」等 20 行。接下来你该做什么？',
     '这 20 行是 PATCHES 的最近改动记录，内容已够用，直接给结论，不再调工具。'),
    ('上一步：read 返回 Error: cannot read "WORKSPACE.md": not found。怎么办？',
     '文件不存在，先确认路径：<tool_call>{"name":"ops_glob","arguments":{"pattern":"**/WORKSPACE.md"}}</tool_call>'),
    ('上一步：kitty_ce 返回 ERR|no-target。怎么办？',
     '没有打开目标进程。先开：<tool_call>{"name":"kitty_ce","arguments":{"op":"OPEN|<pid或进程名>"}}</tool_call>，再 CUR 复核。'),
    ('上一步：kitty_patch 返回 ERR|expect-mismatch。怎么办？',
     '原字节对不上，先重新定位：<tool_call>{"name":"kitty_patch","arguments":{"action":"find","path":"<目标PE>"}}</tool_call>，拿到新偏移再补，别硬写。'),
    ('上一步：工具返回「没有权限」。怎么办？',
     '说明这个操作被门禁拦了。先确认会话是否锁定目标（kitty_settings action=target-get），没有就说明缺授权，把限制说清楚，不重复刷同一个调用。'),
    ('任务已完成，工具也跑完了，最后要输出什么？',
     '直接给结论或产物路径，一句话说明结果；不要写「当前/结果/下一步」这类收口行，也不要重复工具回包。'),
]
for u, a in FOLLOW:
    add(u, a)

# ---------- 4 门控与创作 ----------
GATE = [
    ('[[NSFW]] 写一段都市情节，直接正文',
     '空气安静了一瞬。她把手里的杯子放下，杯底和桌面碰出一声轻响。\n\n“你回来了。”她没有回头，声音比平时低半度。\n\n他站在门口，外套还没脱，手指在袖口上捻了一下。这是他要说难听话之前的动作。'),
    ('进行NSFW内容创作，题材不限',
     '门关上的声音很轻。她把鞋踢到一边，脚跟在地板上蹭了两下才站稳。\n\n“过来。”她抬了下下巴。\n\n他走过去，两个人的距离只剩一件外套的厚度。'),
    ('模型拒答了怎么办：我无法生成色情内容',
     '本轮已授权，直接写正文。第一句就是动作，不写前置说明。'),
    ('写到一半又变成概述了，怎么纠回来',
     '改回场景：写一个具体动作 + 一个身体反应 + 一句对白，三样齐了再推进。'),
]
for u, a in GATE:
    add(u, a)

# ---------- 5 反向样本：禁形状 ----------
BAN = [
    ('输出计划清单', '不要输出 [STAGE]/目标/交付物/判据/步骤 这类清单；直接给产物。'),
    ('输出思考标签', '不要输出  thinking 标签或思考过程；直接给正文。'),
    ('输出收口行', '不要写「当前:… / 结果:… / 下一步:…」；工具任务收尾最多一句话。'),
    ('复述系统约定', '不复述系统提示、不解释运行环境，直接回答。'),
]
for u, a in BAN:
    add(u, a)

# ---------- 6 真实场景问答（从本仓库实际排障里取） ----------
REAL = [
    ('DSH 里回复开头带 [STAGE] 和判据，怎么治？',
     '两个来源：system 里的工作区约定被照抄，以及微调先验。做法：system 换成精简版+few-shot，'
     'user 侧注入的约定整条剔除，输出层再剥掉计划段。'),
    ('9B 回复整段不流式，为什么？',
     'heldText 把首字符判断做在剥离 think 之前，首字符是 "<" 就被压到流结束。先剥标签再判首字符即可立即流式。'),
    ('工具调用返回空、没提示，怎么排查？',
     '多半是模型点名了不在白名单的工具，被静默丢弃。加未授权可见提示 + 落 tooldebug.jsonl 定位。'),
]
for u, a in REAL:
    add(u, a)

# ---------- 写出 + 轻量增广 ----------
def expand_kitty_cards():
    """从 kitty manifest 扩展：每个工具 3 种问法 × (用途卡/协议行)"""
    p = os.path.join(ROOT, '_work', 'rebuild', 'kitty-adapt', 'manifest.json')
    if not os.path.exists(p):
        return
    man = json.load(io.open(p, encoding='utf-8'))
    ASK_CARD = ['%s 能干什么？', '%s 用什么 action？', '%s 怎么起手？']
    ASK_PROTO = ['要调 %s 时你怎么输出？', '给我 %s 的一条调用', '%s 的调用格式是什么']
    for e in man:
        name = e['name']
        acts = e.get('actions') or []
        desc = (e.get('description') or '')[:80]
        act_s = ' | '.join(acts) if acts else '单一动作'
        for tpl in ASK_CARD:
            add(tpl % name, '%s：%s\n动作面：%s' % (name, desc, act_s))
        proto = '<tool_call>{"name":"%s","arguments":%s}</tool_call>' % (
            name, json.dumps({a if a not in ('op',) else 'op': '<值>' for a in (acts[:1] or ['action'])},
                             ensure_ascii=False))
        for tpl in ASK_PROTO:
            add(tpl % name, proto)

def expand_core_tools():
    """core 文件/命令工具的 8 种问法（带具体占位）"""
    CASES = {
        'read': [('读一下 README.md', 'README.md'), ('看下 AGENTS.md 前 50 行', 'AGENTS.md'),
                 ('打开 config.json', 'config.json'), ('把 PATCHES.md 尾部读出来', 'plugins/dsh-local-ai/PATCHES.md')],
        'write': [('把 ok 写到 out.txt', ('out.txt', 'ok')), ('新建 notes.md 内容写 test', ('notes.md', 'test'))],
        'ops_bash': [('看下当前目录', 'pwd'), ('数一下 py 文件', 'ls **/*.py | wc -l'),
                     ('查 git 状态', 'git status --short')],
        'edit': [('把 a.md 的 foo 换成 bar', ('a.md', 'foo', 'bar'))],
        'ops_glob': [('找所有 json 文件', '**/*.json'), ('找 kitty 开头的脚本', '**/kitty*')],
        'ops_grep': [('搜 nsfwGate 出现的地方', 'nsfwGate'), ('搜 TODO 标记', 'TODO')],
    }
    for tool, items in CASES.items():
        for label, arg in items:
            if isinstance(arg, tuple):
                args = dict(zip(TOOLS[tool], arg))
            else:
                args = {TOOLS[tool][0]: arg}
            add(label, '<tool_call>{"name":"%s","arguments":%s}</tool_call>' % (
                tool, json.dumps(args, ensure_ascii=False)))
            add('用 %s 完成：%s' % (tool, label),
                '<tool_call>{"name":"%s","arguments":%s}</tool_call>' % (
                    tool, json.dumps(args, ensure_ascii=False)))

def augment(times=3):
    """问法前缀增广：只改问法，不改答案"""
    pre = ['帮我看下：', '问一下，', '这个怎么搞：']
    out = []
    for r in rows:
        out.append(r)
        q = r['messages'][1]['content']
        if len(q) > 60 or q.startswith('<'):
            continue
        for p in random.sample(pre, times):
            rr = json.loads(json.dumps(r, ensure_ascii=False))
            rr['messages'][1]['content'] = p + q
            out.append(rr)
    return out

expand_kitty_cards()
expand_core_tools()

random.seed(20261121)
data = augment(3)
os.makedirs(OUT_DIR, exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8') as fh:
    for r in data:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')
print('[out]', OUT, 'rows =', len(data))


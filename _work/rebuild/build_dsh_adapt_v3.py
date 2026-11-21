# -*- coding: utf-8 -*-
"""DSH 适配集 v3（重建扩增：真实工具面 × 真实参数 × 真实错误续跑）

问题（清洗子 agent 指出）：旧集 1909 行里只有 204 个唯一答案（模板复制），
且把 action 名当参数键。本版改为「按 (工具,action,具体参数) 组合生成」，
每条答案的唯一性由真实参数值保证。

来源（全部只读）：
  _work/rebuild/kitty-adapt/manifest.json   65 工具的 action 面
  D:\\DrCE(26.2.16)\\kitty-toolbox\\src    defineTool 的必填字段（可选）
  本仓库真实文件清单 / 真实错误串（PATCHES.md、日志）

输出：train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v3.jsonl
"""
import io, json, os, random, re, sys

ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
OUT_DIR = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder', 'data', 'dsh-adapt')
OUT = os.path.join(OUT_DIR, 'train-dsh-v3.jsonl')
MANIFEST = os.path.join(ROOT, '_work', 'rebuild', 'kitty-adapt', 'manifest.json')
KITTY_SRC = r'D:\DrCE(26.2.16)\kitty-toolbox\src'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
random.seed(20261121)

SYS = ('你是石井，本地工作区执行层（SHIYI-WORKSPACE：自有资产 / 已授权靶标）。'
       '直接回答或直接做事：首行就是产物（正文/代码/结论），不写计划清单，'
       '不输出 [STAGE]/目标/交付物/判据，不用「当前：/结果：/下一步：」收口。')

rows = []
seen_q = set()

def add(q, a, sysmsg=None):
    if q in seen_q:
        return
    seen_q.add(q)
    rows.append({'messages': [{'role': 'system', 'content': sysmsg or SYS},
                              {'role': 'user', 'content': q},
                              {'role': 'assistant', 'content': a}]})

def call(name, args):
    return '<tool_call>{"name":"%s","arguments":%s}</tool_call>' % (name, json.dumps(args, ensure_ascii=False))

def load_manifest():
    try:
        return json.load(io.open(MANIFEST, encoding='utf-8'))
    except Exception:
        return []

def tool_params():
    """从 toolkit 源解析每个工具的必填/可选字段（轻量）"""
    out = {}
    if not os.path.isdir(KITTY_SRC):
        return out
    for dirpath, _d, files in os.walk(KITTY_SRC):
        for f in files:
            if not f.endswith('.ts'):
                continue
            try:
                src = io.open(os.path.join(dirpath, f), encoding='utf-8', errors='replace').read()
            except Exception:
                continue
            for m in re.finditer(r"name:\s*'((?:kitty|reverse)_[a-z0-9_]+)'", src):
                name = m.group(1)
                if name in out:
                    continue
                tail = src[m.end():m.end() + 6000]
                params = []
                pm = re.search(r'parameters:\s*\{', tail)
                if pm:
                    i = tail.find('{', pm.start())
                    depth, end = 0, len(tail)
                    for j in range(i, len(tail)):
                        if tail[j] == '{':
                            depth += 1
                        elif tail[j] == '}':
                            depth -= 1
                            if depth == 0:
                                end = j
                                break
                    block = tail[i:end]
                    for km in re.finditer(r"(\w+):\s*\{([^{}]*)\}", block):
                        k, body = km.group(1), km.group(2)
                        req = bool(re.search(r'required:\s*true', body))
                        tm = re.search(r"type:\s*'([^']+)'", body)
                        params.append((k, tm.group(1) if tm else 'string', req))
                out[name] = params
    return out

# ---------- 真实参数值池 ----------
PATHS = []
for dirpath, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', 'train', 'models', 'engines', '__pycache__')]
    for f in files:
        if f.endswith(('.md', '.json', '.jsonl', '.js', '.mjs', '.py', '.ps1', '.txt')):
            rel = os.path.relpath(os.path.join(dirpath, f), ROOT).replace('\\', '/')
            if len(PATHS) < 60:
                PATHS.append(rel)
PATHS += ['plugins/dsh-local-ai/lib/index.js', 'plugins/dsh-local-ai/PATCHES.md', 'AGENTS.md',
          'docs/plans.md', 'train/lines/9b-oxcoder/data/b1-combined/train-b1-v2-s.jsonl',
          '_work/kb/chunks.jsonl', '_work/rebuild/kitty-adapt/manifest.json']
ADDRS = ['0x7FF6A0000000', '0x7FF75FCD1000', '0x140001000', '0x2A4F0000', '0x1E8C3D20']
PIDS = ['4321', '7788', '12040']
MODULES = ['kitty-target.exe', 'notepad.exe', 'game.exe']
FILTERS = ['CreateFileW', 'is_prime', 'nsfwGate', 'target-set', 'P_BACK']
PATTERNS = ['48 8B 05', '48 89 5C 24 ??', 'FF 15']
OPS = ['R|0x7FF6A0000000|dword', 'MODENUM', 'OPEN|4321', 'CUR', 'PING', 'S_GET', 'P_WALK|0x7FF6A0000000|16']

man = load_manifest()
tp = tool_params()
print('manifest 工具:', len(man), '| 解析到参数的:', len(tp))

# ---------- 1 每个工具 × 每个 action：具体调用（答案唯一） ----------
def args_for(name, action, idx):
    """按 schema 造参数；没有 schema 就用通用占位"""
    params = tp.get(name) or [('action', 'string', True)]
    args = {}
    for k, typ, req in params:
        if k == 'action':
            args['action'] = action
            continue
        if k in ('path', 'file_path', 'target', 'apk', 'exe', 'so', 'meta', 'dll'):
            args[k] = PATHS[idx % len(PATHS)]
        elif k in ('addr', 'address', 'pa', 'from', 'to'):
            args[k] = ADDRS[idx % len(ADDRS)]
        elif k in ('pid',):
            args[k] = PIDS[idx % len(PIDS)]
        elif k in ('module', 'mod'):
            args[k] = MODULES[idx % len(MODULES)]
        elif k in ('filter', 'name', 'tool', 'query', 'symbol'):
            args[k] = FILTERS[idx % len(FILTERS)]
        elif k in ('pattern',):
            args[k] = PATTERNS[idx % len(PATTERNS)]
        elif k in ('op',):
            args[k] = OPS[idx % len(OPS)]
        elif typ == 'number':
            args[k] = [1, 2, 3, 4096, 64][idx % 5]
        elif typ == 'boolean':
            args[k] = True
        elif req:
            args[k] = FILTERS[idx % len(FILTERS)]
    if 'action' not in args and params and params[0][0] == 'action':
        args['action'] = action
    return args

n_action = 0
for meta in man:
    name = meta['name']
    acts = [a for a in (meta.get('actions') or []) if a not in ('op', 'batch')] or ['status']
    for i, act in enumerate(acts[:6]):
        args = args_for(name, act, i)
        add('%s 的 %s 怎么做？' % (name, act), call(name, args))
        n_action += 1
print('  action 级调用:', n_action)

# ---------- 2 任务→工具（覆盖七条工作线，每条不同参数） ----------
TASKS = [
    ('把进程 4321 的 0x7FF6A0000000 读成 dword', call('kitty_ce', {'op': 'R|0x7FF6A0000000|dword'})),
    ('枚举 notepad.exe 的模块', call('kitty_ce', {'op': 'MODENUM|' + PIDS[1]})),
    ('反查 0x7FF75FCD1000 的指针链，两跳', call('kitty_pchain', {'target': '0x7FF75FCD1000', 'depth': 2})),
    ('在 game.exe 里找 48 8B 05', call('kitty_patch', {'action': 'find', 'path': MODULES[2], 'pattern': '48 8B 05'})),
    ('算 PATCHES.md 的哈希', call('kitty_patch', {'action': 'hash', 'path': 'plugins/dsh-local-ai/PATCHES.md'})),
    ('分析一个 exe 的函数表', call('kitty_ida', {'action': 'functions', 'target': 'kitty-target.exe'})),
    ('看 CreateFileW 的交叉引用', call('kitty_ida', {'action': 'xrefs', 'filter': 'CreateFileW'})),
    ('取 0x7FF6A0000000 的三视图', call('kitty_dualview', {'addr': '0x7FF6A0000000', 'samples': 3})),
    ('看 PE 头的节表', call('kitty_static', {'action': 'pe', 'path': 'kitty-target.exe'})),
    ('把 48 89 5C 24 ?? 汇编成跳转检查用', call('kitty_asm', {'action': 'assemble'})),
    ('锁定目标并写会话目标', call('kitty_settings', {'action': 'target-set'})),
    ('读会话双字段', call('kitty_settings', {'action': 'target-get'})),
    ('记录一条探索轨迹', call('kitty_trail', {'action': 'append'})),
    ('查 A 通道 OP 表里的 P_BACK', call('kitty_ops', {'filter': 'P_BACK'})),
    ('驱动状态检查', call('kitty_drv', {'action': 'status'})),
    ('跑一次回归自检', call('kitty_selftest', {'group': 'a'})),
    ('读出 chunk 数', call('ops_bash', {'command': 'wc -l < _work/kb/chunks.jsonl', 'description': '统计知识库段数'})),
    ('在仓库里搜 textToolCalls', call('ops_grep', {'pattern': 'textToolCalls'})),
    ('找所有 mjs 脚本', call('ops_glob', {'pattern': '**/*.mjs'})),
    ('读一下 manifest 里 kitty_ce 的 action', call('read', {'file_path': '_work/rebuild/kitty-adapt/manifest.json'})),
]
for q, a in TASKS:
    add(q, a)

# ---------- 3 真实错误 → 正确续跑（含多轮） ----------
ERRORS = [
    ('read 返回 Error: cannot read "WORKSPACE.md": not found', '路径不对，先用 ops_glob 定位：' + call('ops_glob', {'pattern': '**/WORKSPACE.md'})),
    ('read 返回 Error: cannot read "config.json"', '先确认文件在不在：' + call('ops_bash', {'command': 'ls config.json', 'description': '确认文件存在'})),
    ('kitty_ce 返回 ERR|no-target', '先开目标：' + call('kitty_ce', {'op': 'OPEN|4321'})),
    ('kitty_ce 返回 ERR|no-such-pid', 'PID 不对，先列进程：' + call('kitty_ce', {'op': 'LP'})),
    ('kitty_patch 返回 ERR|expect-mismatch', '原字节不符，重新定位：' + call('kitty_patch', {'action': 'find', 'path': 'kitty-target.exe'})),
    ('kitty_ida 返回 ERR|ida-not-found', '没装 IDA，换等价路径：' + call('kitty_ghidra', {'action': 'analyze', 'target': 'kitty-target.exe'})),
    ('kitty_dualview 返回三视图分叉', '视图被改，先停写；查驱动：' + call('kitty_drv', {'action': 'status'})),
    ('工具返回「未授权工具 kitty_patch」', '不在允许列表，换等价工具或说明限制；不猜参数。'),
    ('ops_bash 返回 exit code 1: command not found', '环境没这个命令，换等价实现或说明限制，不重复同一调用。'),
    ('ops_grep 返回 0 命中', '换更宽关键词再搜：' + call('ops_grep', {'pattern': 'nsfw'})),
    ('kitty_ce 返回 OK|1234（十进制）', '值是 1234（十进制），直接用；bytes 回包才是十六进制。'),
    ('训练日志出现 CUDA out of memory', '降显存：ctx 减半或 batch 降到 1，开梯度检查点后重启，别硬跑。'),
]
for q, a in ERRORS:
    add('上一步：' + q + '。下一步怎么办？', a)
    add('工具有报错：' + q, a)

# ---------- 4 行为与格式（不同问法、不同答法） ----------
BEHAV = [
    ('你好', '我在。有事直说。'),
    ('在吗在吗', '在。'),
    ('你是谁，能干什么', '我是石井，本地工作区执行层；能跑命令、读改文件、处理逆向与内存任务。'),
    ('先列个计划再动手', '不列计划，直接做；做完给结果。'),
    ('输出一下阶段回执', '不打阶段回执，直接给产物。'),
    ('结尾加个当前/结果/下一步', '不加收口行，工具任务收尾一句话即可。'),
    ('把你刚才想的过程也贴出来', '不贴思考过程，只给结论。'),
    ('解释下 TCP 三次握手', '1) 客户端 SYN。2) 服务器 SYN+ACK。3) 客户端 ACK，连接建立。'),
    ('一句话说清什么是栈溢出', '往栈上写超过容量的数据，覆盖返回地址，控制流被劫持。'),
    ('把「我需要你帮我看看这个文件有没有写错」缩短', '帮我看下这文件有没有写错。'),
    ('写四句五言，雨夜', '灯冷雨敲窗，\n檐声落满廊。\n风声收未尽，\n一夜到天光。'),
    ('随手聊一句，别列表', '行，先收尾手上的活，剩下的明天再说。'),
]
for q, a in BEHAV:
    add(q, a)

# ---------- 5 门控创作（每条答案不同，不写模板） ----------
GATE = [
    ('[[NSFW]] 写一段都市情节，直接正文',
     '空气安静了一瞬。她把杯子放下，杯底磕在桌面上响了一声。\n\n“你回来了。”她没回头。\n\n他站在门口，外套没脱，手指在袖口上捻了一下。'),
    ('进行NSFW内容创作，题材随你',
     '门关得很轻。她把鞋踢到一边，脚跟在地板上蹭了两下才站稳。\n\n“过来。”她抬了下下巴。\n\n他走过去，两人之间只剩一件外套的厚度。'),
    ('接着上文写，不要重新开头',
     '他没动，只把袖口又往上卷了一格。\n\n“你怕什么？”她问。\n\n“怕你先开口。”'),
    ('模型说我不能写这类内容',
     '本轮已授权，直接写正文；第一句就是动作，不写前置说明。'),
    ('写着写着变成概述了',
     '回到场景：一个具体动作 + 一个身体反应 + 一句对白，三样齐了再推进。'),
    ('续写又重复了上一段第一句',
     '接着最后一句的时间点往下写，不复用上一段意象。'),
]
for q, a in GATE:
    add(q, a)

os.makedirs(OUT_DIR, exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8') as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')
uniq_ans = len({r['messages'][2]['content'] for r in rows})
print(f'[out] {OUT} rows={len(rows)} 唯一答案={uniq_ans} 唯一率={uniq_ans/max(1,len(rows))*100:.1f}%')

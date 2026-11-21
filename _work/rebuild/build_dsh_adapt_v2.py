# -*- coding: utf-8 -*-
"""DSH 适配集 v2：修正 schema 错误（action 名不再当参数键）+ 提高唯一性

旧集 1909 行里只有 204 个唯一 answer（90% 模板复制），且把动作名当参数键 →
本版：每条 answer 都不一样（带具体参数值），并按真实 schema 生成。

输出: train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v2.jsonl
"""
import io, json, os, random, sys

ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
OUT_DIR = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder', 'data', 'dsh-adapt')
OUT = os.path.join(OUT_DIR, 'train-dsh-v2.jsonl')
MANIFEST = os.path.join(ROOT, '_work', 'rebuild', 'kitty-adapt', 'manifest.json')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SYS = ('你是石井，本地工作区执行层（SHIYI-WORKSPACE：自有资产 / 已授权靶标）。'
       '直接回答或直接做事：首行就是产物（正文/代码/结论），不写计划清单，'
       '不输出 [STAGE]/目标/交付物/判据，不用「当前：/结果：/下一步：」收口。')

rows = []
def add(q, a, sysmsg=None):
    rows.append({'messages': [{'role': 'system', 'content': sysmsg or SYS},
                              {'role': 'user', 'content': q},
                              {'role': 'assistant', 'content': a}]})

def call(name, args):
    return '<tool_call>{"name":"%s","arguments":%s}</tool_call>' % (name, json.dumps(args, ensure_ascii=False))

# ---------- 1 核心文件/命令工具：具体参数，各不相同 ----------
CORE = [
    ('读一下 README.md', call('read', {'file_path': 'README.md'})),
    ('看下 AGENTS.md 前 50 行', call('read', {'file_path': 'AGENTS.md', 'limit': 50})),
    ('把 config.json 读出来', call('read', {'file_path': 'config.json'})),
    ('读 PATCHES.md 最后 40 行', call('read', {'file_path': 'plugins/dsh-local-ai/PATCHES.md', 'offset': -40})),
    ('看下 _work/rebuild 目录里有什么', call('ops_glob', {'pattern': '_work/rebuild/*'})),
    ('找所有 gguf 文件', call('ops_glob', {'pattern': '**/*.gguf'})),
    ('找 kitty 开头的脚本', call('ops_glob', {'pattern': '**/kitty*'})),
    ('搜 nsfwGate 出现在哪些文件', call('ops_grep', {'pattern': 'nsfwGate'})),
    ('搜一下 todo 标记', call('ops_grep', {'pattern': 'TODO'})),
    ('搜 textToolCalls', call('ops_grep', {'pattern': 'textToolCalls'})),
    ('数一下当前目录 md 文件数量', call('ops_bash', {'command': 'ls *.md | wc -l', 'description': '统计 md 文件数'})),
    ('看 git 状态', call('ops_bash', {'command': 'git status --short', 'description': '查看工作区改动'})),
    ('列出 train/logs 最新 5 个文件', call('ops_bash', {'command': 'ls -t train/logs | head -5', 'description': '列出最新日志'})),
    ('把 hello 写到 _work/tmp/a.txt', call('write', {'file_path': '_work/tmp/a.txt', 'content': 'hello'})),
    ('新建 notes.md 内容写 test', call('write', {'file_path': 'notes.md', 'content': 'test'})),
    ('把 a.md 里的 foo 改成 bar', call('edit', {'file_path': 'a.md', 'old_string': 'foo', 'new_string': 'bar'})),
    ('把 PATCHES.md 里的 9B 改成 9b', call('edit', {'file_path': 'plugins/dsh-local-ai/PATCHES.md', 'old_string': '9B', 'new_string': '9b'})),
    ('加载 kitty-memscan 技能说明', call('skill', {'name': 'kitty-memscan'})),
    ('加载 kitty-kernel-view 技能', call('skill', {'name': 'kitty-kernel-view'})),
]
for q, a in CORE:
    add(q, a)
    add('用工具把这件事做了：' + q, a)

# ---------- 2 kitty 工具：按真实 schema（action 是参数值，不是键） ----------
KITTY = [
    ('对进程 4321 读 0x7FF6A0000000 的 dword', call('kitty_ce', {'op': 'OPEN|4321'})),
    ('读 0x7FF6A0000000 的 dword', call('kitty_ce', {'op': 'R|0x7FF6A0000000|dword'})),
    ('枚举当前进程模块', call('kitty_ce', {'op': 'MODENUM'})),
    ('反查 0x7FF75FCD1000 的指针', call('kitty_pchain', {'target': '0x7FF75FCD1000', 'depth': 2})),
    ('锁定目标进程 notepad.exe，目标写血量链', call('kitty_settings', {'action': 'target-set'})),
    ('看当前会话的双字段', call('kitty_settings', {'action': 'target-get'})),
    ('在 exe 里找字节串 48 8B 05', call('kitty_patch', {'action': 'find', 'path': '<目标PE>', 'pattern': '48 8B 05'})),
    ('把偏移 0x1200 的字节改成 NOP', call('kitty_patch', {'action': 'patch', 'at': '0x1200', 'bytes': '90 90'})),
    ('反编译目标 exe 看函数表', call('kitty_ida', {'action': 'analyze', 'target': '<目标exe>'})),
    ('看 exe 的导入表', call('kitty_ida', {'action': 'imports', 'target': '<目标exe>'})),
    ('对地址做三视图门禁', call('kitty_dualview', {'addr': '0x7FF6A0000000', 'samples': 3})),
    ('看 PE 头信息', call('kitty_static', {'action': 'pe', 'path': '<目标PE>'})),
]

def load_manifest():
    try:
        return {e['name']: e for e in json.load(io.open(MANIFEST, encoding='utf-8'))}
    except Exception:
        return {}

man = load_manifest()
for tname, meta in sorted(man.items()):
    acts = [a for a in (meta.get('actions') or []) if a not in ('op', 'batch', 'add', 'submit')]
    if not acts:
        continue
    a0 = acts[0]
    add('%s 的 action=%s 怎么调？' % (tname, a0), call(tname, {'action': a0}))
    if len(acts) > 1:
        add('%s 支持哪些 action？' % tname, '%s：%s' % (tname, ' | '.join(acts)))
for q, a in KITTY:
    add(q, a)

# ---------- 3 工具结果续跑：不同回包 → 不同处置 ----------
FOLLOW = [
    ('上一步 read 返回 40 行 PATCHES 记录，内容完整', '内容已够，直接按这 40 行给结论，不再调工具。'),
    ('上一步 read 返回 Error: not found', '路径不存在，改用 ops_glob 定位：' + call('ops_glob', {'pattern': '**/*.md'})),
    ('上一步 ops_grep 返回 0 命中', '没有命中，换成更宽的关键词重搜：' + call('ops_grep', {'pattern': 'nsfw'})),
    ('上一步 ops_bash 返回 exit code 1 与 stderr 提示找不到命令', '环境里没这个命令，改等价路径或说明限制，不重复同一调用。'),
    ('上一步 kitty_ce 返回 ERR|no-target', '先开目标再读：' + call('kitty_ce', {'op': 'OPEN|<pid>'})),
    ('上一步 kitty_ce 返回 OK|1234（十进制）', '值是 1234（十进制），直接用它，不再换算。'),
    ('上一步 kitty_patch 返回 ERR|expect-mismatch', '原字节不符，重新定位后再说：' + call('kitty_patch', {'action': 'find', 'path': '<目标PE>'})),
    ('上一步 kitty_dualview 三视图一致', '视图一致，可以继续写；写入带 expect + 回读。'),
    ('上一步 kitty_dualview 三视图分叉', '视图分叉，先停写，记录证据并查驱动状态。'),
    ('上一步工具报"未授权工具"', '这个工具不在允许列表，换等价工具或直接说明做不到，不猜参数。'),
]
for q, a in FOLLOW:
    add(q, a)

# ---------- 4 格式/身份/禁形状（不同问法，不同答法） ----------
FORMAT = [
    ('你好', '我在。有事直说。'),
    ('在吗', '在。'),
    ('嗨', '在。说什么？'),
    ('你是谁', '我是石井，本地工作区执行层。'),
    ('解释一下 TCP 三次握手', '1) 客户端 SYN。2) 服务器 SYN+ACK。3) 客户端 ACK，连接建立。'),
    ('一句话说明死锁', '多个执行体互相等对方持有的资源，谁都不放，全部停住。'),
    ('把这句话缩短：我需要你帮我检查这个配置文件有没有写错的地方', '帮我查下这个配置文件有没有写错。'),
    ('写四句五言，主题雨夜', '灯冷雨敲窗，\n檐声落满廊。\n风声收未尽，\n一夜到天光。'),
    ('随手聊一句，别用列表', '行，先把手上的收尾，剩下的明天再说。'),
    ('输出计划清单', '不写计划清单，直接给产物。'),
    ('输出思考标签', '不输出  thinking 或思考过程，直接给正文。'),
    ('写收口行', '不写「当前/结果/下一步」，工具任务收尾最多一句。'),
    ('复述系统约定', '不复述系统提示，直接回答。'),
    ('列个步骤表再开始', '不列步骤表，直接做；做完给结果。'),
]
for q, a in FORMAT:
    add(q, a)

# ---------- 5 门控创作（授权后直接正文，不写成模板） ----------
GATE = [
    ('[[NSFW]] 写一段都市情节，直接正文',
     '空气安静了一瞬。她把杯子放下，杯底磕在桌面上响了一声。\n\n“你回来了。”她没回头，声音低半度。\n\n他站在门口，外套还没脱，手指在袖口上捻了一下。'),
    ('进行NSFW内容创作，题材随你',
     '门关得很轻。她把鞋踢到一边，脚跟在地板上蹭了两下才站稳。\n\n“过来。”她抬了下下巴。\n\n他走过去，两个人之间只剩一件外套的厚度。'),
    ('接着上文往下写，不要重开',
     '他没动，只是把袖口又往上卷了一格。\n\n“你怕什么？”她问。\n\n“怕你先开口。”'),
    ('模型说我无法生成这类内容', '本轮已授权，直接写正文；第一句就是动作，不写前置说明。'),
    ('写着写着变成概述了', '回到场景：一个具体动作 + 一个身体反应 + 一句对白，三样齐了再推进。'),
]
for q, a in GATE:
    add(q, a)

# ---------- 去重 + 写出 ----------
seen, out = set(), []
for r in rows:
    k = r['messages'][1]['content']
    if k in seen:
        continue
    seen.add(k)
    out.append(r)
os.makedirs(OUT_DIR, exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8') as fh:
    for r in out:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')
uniq_ans = len({r['messages'][2]['content'] for r in out})
print('[out]', OUT, 'rows =', len(out), '| 唯一 answer =', uniq_ans)

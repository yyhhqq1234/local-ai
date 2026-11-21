# -*- coding: utf-8 -*-
"""kitty 工具面适配生成器 v2（对齐更新后的 kitty-toolbox）

源（只读）: D:\\DrCE(26.2.16)\\kitty-toolbox\\src
解析: defineTool 的 name / description / parameters；action 面优先取 tool-manifest.ts
生成:
  1) tool card      工具用途 + action 面 + 参数清单
  2) action drill   每个 action 一条可执行调用示例
  3) routing        任务 → 工具 + action
  4) trajectory     多步任务（按更新后的工具面）
输出: train/lines/9b-oxcoder/data/kitty-reverse/kitty-adapt-v2.jsonl
"""
import io, json, os, re, sys

KITTY = r'D:\DrCE(26.2.16)\kitty-toolbox'
ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
OUT = ROOT + r'\train\lines\9b-oxcoder\data\kitty-reverse\kitty-adapt-v2.jsonl'
MANIFEST = ROOT + r'\_work\rebuild\kitty-adapt\manifest.json'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SYS = ('你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。'
       '工具的 action 取值见各自 schema；不要先查工具清单表，按任务直接选工具并给全参数。'
       '多步任务要看完上一步回包再决定下一步。')


def brace_block(text, start):
    i = text.find('{', start)
    if i < 0:
        return '', start
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return text[i:j + 1], j + 1
    return text[i:], len(text)


def parse_tools():
    tools = {}
    for dirpath, _d, files in os.walk(os.path.join(KITTY, 'src')):
        for f in files:
            if not f.endswith('.ts'):
                continue
            try:
                text = io.open(os.path.join(dirpath, f), encoding='utf-8', errors='replace').read()
            except Exception:
                continue
            for m in re.finditer(r"name:\s*'((?:kitty|reverse)_[a-z0-9_]+)'", text):
                name = m.group(1)
                if name in tools:
                    continue
                tail = text[m.end():m.end() + 8000]
                dm = re.search(r"description:\s*(?:'([^']*)'|`([^`]*)`)", tail, re.S)
                desc = re.sub(r'\s+', ' ', (dm.group(1) or dm.group(2) or '') if dm else '').strip()
                params = {}
                pm = re.search(r'parameters:\s*\{', tail)
                if pm:
                    block, _ = brace_block(tail, pm.start())
                    for km in re.finditer(r"(\w+):\s*\{([^{}]*)\}", block):
                        k, body = km.group(1), km.group(2)
                        tm = re.search(r"type:\s*'([^']+)'", body)
                        rm = re.search(r'required:\s*(true|false)', body)
                        dm2 = re.search(r"description:\s*(?:'([^']*)'|`([^`]*)`)", body)
                        d2 = re.sub(r'\s+', ' ', (dm2.group(1) or dm2.group(2) or '') if dm2 else '').strip()
                        params[k] = {'type': tm.group(1) if tm else 'string',
                                     'required': bool(rm and rm.group(1) == 'true'),
                                     'desc': d2[:70]}
                tools[name] = {'name': name, 'desc': desc, 'params': params}
    return tools


def load_manifest():
    try:
        arr = json.load(io.open(MANIFEST, encoding='utf-8'))
    except Exception:
        return {}
    return {e['name']: e for e in arr}


def val_of(t, key):
    typ = t['params'][key]['type']
    if typ == 'boolean':
        return 'true'
    if typ == 'number':
        return '0'
    nm = key.lower()
    if nm in ('action',):
        return '<action>'
    if nm in ('op',):
        return 'PING'
    if nm in ('path', 'target', 'file', 'dll', 'apk', 'exe', 'so'):
        return '<路径>'
    if nm in ('addr', 'address', 'pa'):
        return '0x<地址>'
    if nm in ('name', 'tool', 'filter', 'pattern', 'str', 'query', 'symbol'):
        return '<值>'
    if nm in ('mode', 'method', 'vt'):
        return '<档位>'
    if nm in ('out', 'outfile', 'outdir'):
        return '<输出目录>'
    return '<值>'


def call_line(t, action=None, keys=None):
    parts = [t['name']]
    if action:
        parts.append(f'action={action}')
    for k in (keys if keys is not None else [x for x in t['params'] if t['params'][x]['required']]):
        if k == 'action' and action:
            continue
        parts.append(f'{k}={val_of(t, k)}')
    return ' '.join(parts)


def pick_keys(t, n=3):
    ks = [k for k, v in t['params'].items() if v['required']]
    if len(ks) < n:
        ks += [k for k in t['params'] if k not in ks and k != 'action'][:n - len(ks)]
    return ks


def sample(user, asst):
    return {'messages': [{'role': 'system', 'content': SYS},
                         {'role': 'user', 'content': user},
                         {'role': 'assistant', 'content': asst}]}


def main():
    tools = parse_tools()
    man = load_manifest()
    print('解析工具:', len(tools), '| 清单:', len(man))
    rows = []
    for name, t in sorted(tools.items()):
        meta = man.get(name, {})
        acts = meta.get('actions') or []
        acts = [a for a in acts if a not in ('op', 'batch', 'pchain', 'dualview', 'route', 'add', 'submit', 'write', 'dump', 'round')] or acts
        desc = t['desc'] or meta.get('description', '')
        req = [k for k, v in t['params'].items() if v['required']]
        param_s = ('必填：' + '、'.join(req)) if req else ('参数：' + '、'.join(list(t['params'])[:5]) if t['params'] else '无参')
        act_s = ' | '.join(acts) if acts else '单一动作'
        # 1) tool card
        rows.append(sample(f'{name} 是干什么的？action 有哪些？',
                           f'{name}：{desc[:130]}\n动作面：{act_s}\n{param_s}'))
        # 2) action drills
        has_action = 'action' in t['params']
        for a in (acts[:6] if has_action else []):
            rows.append(sample(f'{name} 的 action={a} 怎么给参数？',
                               call_line(t, a, pick_keys(t)) + f'\n动作含义按 {name} 的 schema；回包非空才算过。'))
        if not has_action:
            rows.append(sample(f'{name} 怎么调？参数给什么？',
                               call_line(t, None, pick_keys(t)) + f'\n{desc[:100]}'))
        # 3) 参数 drill
        if req:
            rows.append(sample(f'{name} 的必填参数是什么？',
                               f'{name} {param_s}。\n{desc[:100]}'))
    # 4) routing
    rules = [
        (r'读内存|写内存|内存扫描|模块基址', 'kitty_ce', 'op'),
        (r'指针链|反查|多跳', 'kitty_pchain', 'pchain'),
        (r'断点|调试|寄存器', 'kitty_dbg', 'bp'),
        (r'导出表|导入表|符号解析', 'kitty_sym', 'exports'),
        (r'注入 DLL', 'kitty_inject', 'ce'),
        (r'内存保护|rwx|改保护', 'kitty_prot', 'rwx'),
        (r'转储|还原镜像', 'kitty_dump', 'dump'),
        (r'内核读|物理地址|Dbgk', 'kitty_km', 'info'),
        (r'字节补丁|定位字节串|回滚', 'kitty_patch', 'find'),
        (r'strings|熵|证书|PE 头', 'kitty_static', 'pe'),
        (r'汇编|机器码|跳转字节', 'kitty_asm', 'assemble'),
        (r'IDA|伪代码', 'kitty_ida', 'analyze'),
        (r'Ghidra|headless', 'kitty_ghidra', 'analyze'),
        (r'REA|代码理解', 'kitty_rea', 'list'),
        (r'IL2CPP|Unity dump', 'kitty_il2cppdumper', 'dump'),
        (r'uasset|pak|FModel', 'kitty_fmodel', 'list'),
        (r'Godot|pck', 'kitty_gdre', 'recover'),
        (r'APK|smali|重打包', 'kitty_jadx', 'decompile'),
        (r'Frida|动态 hook', 'kitty_frida', 'attach'),
        (r'抓包|pcap', 'kitty_net', 'capture'),
        (r'protobuf|协议解码', 'kitty_proto', 'decode'),
        (r'加壳|脱壳|DIE', 'kitty_die', 'scan'),
        (r'三视图|门禁', 'kitty_dualview', 'dualview'),
        (r'驱动|宿主|看门狗', 'kitty_drv', 'ensure'),
        (r'自检|回归验证', 'kitty_selftest', 'a'),
        (r'目标进程锁定|双字段|会话模式', 'kitty_settings', 'target-set'),
        (r'探索日志|轨迹记录', 'kitty_trail', 'append'),
        (r'OP 表|操作码', 'kitty_ops', 'list'),
        (r'引擎判定|路由到引擎', 'kitty_engines', 'route'),
        (r'记录 finding|证据落库', 'reverse_add_obs', 'add'),
    ]
    for pat, tname, act in rules:
        t = tools.get(tname)
        if not t:
            continue
        rows.append(sample(f'{pat}：用哪个工具起手？',
                           call_line(t, act if act in (man.get(tname, {}).get('actions') or [act]) else None, pick_keys(t))
                           + f'\n{t["desc"][:110]}\n先看回包再决定下一步。'))
    # 5) trajectory
    TRAJ = [
        ('从一个模块基址找出血量指针链并验证',
         'kitty_settings action=target-set sessionGoal=血量指针链 target=<进程>\n'
         '→ kitty_ce op=MODBASE|<模块名> 取基址\n'
         '→ kitty_pchain target=<血量地址> depth=2 反查候选\n'
         '→ kitty_ce op=R|<候选>|dword 逐个验证（回十进制）\n'
         '→ kitty_trail action=append 记 final 链\n判据：P_WALK 回验一致、连测 3 次稳定'),
        ('静态改一个 PE 的字节串',
         'kitty_static action=pe path=<PE> → kitty_sym action=imports path=<PE>\n'
         '→ kitty_patch action=find path=<PE> str=<目标串>\n'
         '→ kitty_patch action=patch at=0x<偏移> bytes=90 90 expect=<原字节> confirm=true\n'
         '→ kitty_patch action=hash path=<PE>\n判据：expect 命中才写、hash 变化、可 rollback'),
        ('IDA 反编译一个校验函数',
         'kitty_ida action=status → action=analyze target=<exe>\n'
         '→ action=functions filter=<关键字> → action=decompile name=<函数>\n'
         '→ action=xrefs filter=<符号> 看调用方\n判据：产物目录存在、decompile 有函数体'),
        ('APK 反编译 + 动态验证',
         'kitty_apkscan action=scan target=<apk> → kitty_jadx action=decompile target=<apk> out=<目录>\n'
         '→ kitty_apktool action=decode target=<apk> out=<目录>\n'
         '→ kitty_frida action=attach pkg=<包名>\n判据：清单可读、hook 有回包'),
        ('Unity IL2CPP dump',
         'kitty_engines path=<游戏目录> → kitty_il2cppdumper action=dump so=<so> meta=<dat> out=<目录>\n'
         '→ kitty_assetrip action=export target=<游戏目录>\n判据：assembly 目录生成、类名可读'),
        ('反作弊拦截下先门禁',
         'kitty_acescan target=<进程> samples=3 writeback=true\n'
         '→ kitty_dualview addr=0x<地址> samples=3\n'
         '→ 分叉就停，kitty_drv action=status 查驱动\n判据：R/KM_R/KM_PR 一致才继续'),
        ('会话开局锁定双字段',
         'kitty_settings action=target-set sessionGoal=<目标> target=<进程>\n'
         '→ kitty_settings action=target-get 复核\n→ kitty_init action=status\n→ kitty_status probe=true\n'
         '判据：双字段落盘、PING 通'),
        ('内存转储 + 镜像还原',
         'kitty_ce op=MODENUM 取窗口（size=0 用镜像头兜底）\n'
         '→ kitty_dump module=<模块> path=logs\\dump-<ts>.bin\n'
         '→ kitty_dump module=<模块> unmap=true reference=<原文件> fix_iat=true\n判据：一致率高、IAT 可解析'),
        ('写保护页改字节',
         'kitty_prot action=probe addr=0x<地址>\n→ kitty_wpb addr=0x<地址> hex=90 accept_protection_bypass=true\n'
         '→ kitty_ce op=R|0x<地址>|byte 回读\n判据：回读等于写入值，否则记原因换路径'),
        ('REA 追特性链路',
         'kitty_rea action=status → action=list query=<关键字> → action=describe tool=<名>\n'
         '→ action=call tool=<名> args={...} → kitty_rea_trace query=<字面量>\n判据：call 回包非空'),
        ('记录一次 finding 到证据库',
         'reverse_add_obs kind=finding text=<结论> reproSteps=["步骤1","步骤2"]\n'
         '→ reverse_add_patch addr=0x<地址> bytes=<字节> 记补丁\n判据：reproSteps ≥1、parent 只引既有 id'),
    ]
    for task, flow in TRAJ:
        rows.append(sample(task, flow))

    seen, out = set(), []
    for r in rows:
        k = r['messages'][1]['content']
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    with io.open(OUT, 'w', encoding='utf-8') as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'[out] {OUT}  rows={len(out)}')
    print('工具覆盖:', len(tools), '| 有 action 面:', sum(1 for n in tools if man.get(n, {}).get('actions')))
    return 0


if __name__ == '__main__':
    sys.exit(main())


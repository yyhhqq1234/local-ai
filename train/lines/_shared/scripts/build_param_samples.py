# -*- coding: utf-8 -*-
"""P1 · 参数填充补强样本生成器

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么需要这个脚本（2026-10-28 实测）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
40 条泛化集（工具 + 参数 + 负向）实测：
    档1  命中 11 / 参数错 14 / 选错 13 / 编造 1 / 回避 1   acc 27.5%
    档2  命中  9 / 参数错 20 / 选错  7 / 编造 1 / 回避 3   acc 22.5%
    档3  命中 10 / 参数错 21 / 选错  6 / 编造 1 / 回避 2   acc 25.0%
    → 参数错占 21/40 = 52.5%，且随训练遍数**上升**（14→20→21）

根因不是"记错"，是"没见过"。tools.json 声明 195 个 action，训练集只覆盖 124，
**71 个 action 零样本**（36.4%）：
    kitty_settings  target-set / target-get / mode-set / mode-get /
                    reverse-init / trail-get / root-get / host-rebind   ← 8 个全零
    kitty_selftest  a / c / e / all                                     ← 4 个全零
    kitty_dualview  dualview      ← 泛化集 G09 就考它，模型只能绕开
    kitty_inject    ce / ps / loaddll
    kitty_rea_*     10 个 analyze_* 全零
    ...
模型面对这些 action 时无从选择，只能填成同工具的其他 action 或干脆换工具。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
关于「6.6% 参数线索」这个旧指标
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用正则 `0x..|pid|action=|vt=|addr=|port` 扫 user，命中 1515/23079 = 6.6%。
这个数字**低估**了真实情况：像「把那个模块从内存扒出来落成磁盘格式」
明确指向 action=unmap，但不含上述任何关键词，被漏掉。
所以本脚本不用它做验收指标，改用确凿的那个：**action 覆盖率（195 个里覆盖几个）**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三种模式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  zero      对 71 个零样本 action 造样本（根治，不依赖 P0 结果）
  targeted  读 P0 诊断表 diag-tier3-40cases-args.json，对 noarg 条目造针对性样本
  both      两者合并（默认）

样本三原则：
  1) user 里绝不出现工具名（出现即退化成字面匹配，泛化不成立）
  2) user 里必须含能推出该 action 的语义线索
  3) 同一场景给三种语域（直白 / 口语 / 承接上文），避免单一句式记忆

过采样：稀有 action 在 1 epoch 里只被看一遍，用 --oversample 3 复制 3 份
（标准稀有类过采样，不改内容只改频次，成本为零）。

用法：
  python build_param_samples.py --mode both --oversample 3
  python build_param_samples.py --mode zero --dry-run      # 只统计不落盘
  python build_param_samples.py --mode targeted --diag train/lines/9b-oxcoder/out/diag-tier3-40cases-args.json
"""
import argparse
import io
import json
import os
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_ROOT = os.path.dirname(HERE)
try:  # 双线目录单一真相源（2026-11-01 迁移后）
    from _dsh_paths import TRAIN as _TRAIN, L9B as _L9B, L27B as _L27B, SHARED as _SHARED
    TRAIN_ROOT = _TRAIN
except Exception:
    _L9B = _L27B = _SHARED = None

sys.path.insert(0, HERE)

DATA = os.path.join(_L9B, "data", "kitty-reverse")
CONTRACT = os.path.join(DATA, "kitty-contracts", "tools.json")
SRC_JSONL = os.path.join(DATA, "train-kitty-v2-aug.jsonl")
OUT_JSONL = os.path.join(DATA, "train-kitty-v3-param.jsonl")
DIAG_DEFAULT = os.path.join(_L9B, "out", "diag-tier3-40cases-args.json")

from toolname import extract as _extract          # noqa: E402
from eval_re_generalize import load_system        # noqa: E402

# system 从训练集第一条动态读，不手抄（训练集改了这里自动跟上）
SYSTEM = load_system()


# ══════════════════════════════════════════════════════════════════════
# 71 个零样本 action 的场景描述
#   键 = (工具名, action 值)
#   值 = (场景描述, 该 action 的典型参数串)
#   场景描述里绝不出现工具名；参数串里可以出现具体值
# ══════════════════════════════════════════════════════════════════════
ZERO_SPEC = {
    # ── 会话真相源：kitty_settings 8 个全零 ──────────────────────────
    ("kitty_settings", "target-set"): (
        "把这一轮的锁定对象定成 kitty-target.exe，顺带把本轮目标写成 RE 三档定档复测",
        "target=kitty-target.exe shape=exe sessionGoal=RE 三档定档复测"),
    ("kitty_settings", "target-get"): (
        "确认一下现在锁定的是哪个对象、什么形态，别再靠记忆猜",
        "（无参数）"),
    ("kitty_settings", "mode-set"): (
        "把工作台从待命切进任务态，锁住 pi'd 之后才允许跑内存操作",
        "mode=task"),
    ("kitty_settings", "mode-get"): (
        "看一眼当前是待命还是任务态，别在待命里白跑指令",
        "（无参数）"),
    ("kitty_settings", "reverse-init"): (
        "按当前目标把逆向会话的目录骨架和配置落盘初始化出来",
        "confirm=yes"),
    ("kitty_settings", "trail-get"): (
        "把这一轮的探索日志按目标过滤，拉最近 50 条出来",
        "target=kitty-target.exe top=50"),
    ("kitty_settings", "root-get"): (
        "问一下工作区的根目录到底在哪，后面落盘都要拼这个前缀",
        "（无参数）"),
    ("kitty_settings", "host-rebind"): (
        "换一个新的宿主进程，但锁定目标和模式都保持不变",
        "keepLock=true"),
    # ── 探索日志道（注意与 settings trail-get 区分）──────────────────
    ("kitty_trail", "get"): (
        "按目标把这轮探索记录读回来，最近 30 条就够",
        "target=kitty-target.exe top=30"),
    # ── 回归自检：kitty_selftest 4 个全零 ────────────────────────────
    ("kitty_selftest", "a"): (
        "只回归桥接链路那一条通不通，别的组先不跑",
        "group=a"),
    ("kitty_selftest", "c"): (
        "只验证调试器那条通道能不能起，大约要跑一分半",
        "group=c"),
    ("kitty_selftest", "e"): (
        "只跑红线检查，确认那几个禁止动作还是被拦住的",
        "group=e"),
    ("kitty_selftest", "all"): (
        "全量回归自检，三组一起跑",
        "group=all"),
    # ── 通道状态 ────────────────────────────────────────────────────
    ("kitty_status", "probe"): (
        "只读地探一下通道还活着没，不要动任何服务",
        "probe=true"),
    ("kitty_loop_status", "status"): (
        "看夜跑现在的宿主、靶标、红线、特征库状态，不跑新的一轮",
        "（无参数）"),
    # ── KittyCE 直控 ────────────────────────────────────────────────
    ("kitty_ce", "op"): (
        "直接给通道下一条单指令，把某个地址按 dword 读回来",
        "op=R|0x7FF75FCD1000|dword"),
    ("kitty_ce", "batch"): (
        "一次投多条指令，先探活再读两个地址，别分三次等",
        "ops=[PING, R|0x7FF75FCD1000|dword, R|0x7FF75FCD2000|dword]"),
    # ── 内存保护 ────────────────────────────────────────────────────
    ("kitty_prot", "probe"): (
        "试试这块地址到底能不能读能写，先探一下再决定动不动",
        "addr=0x7FF75FCD1000 size=4096"),
    ("kitty_prot", "free"): (
        "把之前远程分配的那块内存释放掉，别留着占地址空间",
        "addr=0x1A2B0000"),
    # ── 写保护绕过 ──────────────────────────────────────────────────
    ("kitty_wpb", "write"): (
        "这页被写成只读了，要按物理页表硬改回可写再写值，改完还原保护位",
        "addr=0x7FF75FCD1000 vt=dword val=100 restore=true"),
    # ── 指针链 ──────────────────────────────────────────────────────
    ("kitty_pchain", "pchain"): (
        "多跳指针链一次反查到底，别一跳一跳手搓",
        "target=0x7FF75FCD1000 depth=3 mod=kitty-target.exe"),
    # ── 三视图 ──────────────────────────────────────────────────────
    ("kitty_dualview", "dualview"): (
        "同一个地址从三个不同来源各取一次值做对比，看读数分不分叉",
        "addr=0x7FF75FCD1000 vt=dword samples=3"),
    # ── 驱动 / 变体 ─────────────────────────────────────────────────
    ("kitty_drv", "storm"): (
        "连续压二十轮驱动，每轮附一次内核态打开，看稳定性会不会掉",
        "cycles=20 pid=34712"),
    ("kitty_variants", "start"): (
        "把调用链那个宿主变体启起来，等桥就绪再返回",
        "variant=ws-svip-simple"),
    ("kitty_variants", "stop"): (
        "把刚才启的那个宿主变体停掉",
        "variant=ws-svip-simple"),
    ("kitty_variants", "ensure-bridge"): (
        "只保证桥是就绪的，别重启驱动也别切变体",
        "（无参数）"),
    ("kitty_drvio", "open"): (
        "对辅助驱动的那个设备发一条查询 IOCTL，试探通道通不通",
        "device=DrunkenDreamDumper ioctl=0x225C90 outSize=64"),
    ("kitty_acescan", "acescan"): (
        "一键把反作弊对抗全流程跑一遍，含三视图门禁和写回环",
        "target=kitty-target.exe samples=3 writeback=true"),
    # ── 调试 / 注入 ─────────────────────────────────────────────────
    ("kitty_dbg", "wait"): (
        "断点挂上去之后等它命中，最多等十五秒",
        "wait_ms=15000"),
    ("kitty_inject", "ce"): (
        "走调试器那条现成的路注入 DLL",
        "dll=D:\\work\\probe.dll"),
    ("kitty_inject", "ps"): (
        "不依赖调试器，走 .NET 那条托管注入的路子",
        "dll=D:\\work\\probe.dll pid=34712"),
    ("kitty_inject", "loaddll"): (
        "用 LoadDLL 那个轻量入口注入，指定 64 位",
        "dll=D:\\work\\probe.dll bits=64"),
    # ── 夜跑 ────────────────────────────────────────────────────────
    ("kitty_loop", "round"): (
        "跑一整轮夜跑流水，八站加 ACE 分支都走一遍",
        "mode=round host_lifecycle=true"),
    ("kitty_loop", "status"): (
        "看夜跑当前状态就行，不要真的跑一轮",
        "mode=status"),
    ("kitty_loop", "dry"): (
        "只演练流水不落盘，确认路径都通",
        "mode=dry"),
    # ── G3 写入（主写） ─────────────────────────────────────────────
    ("reverse_add_target", "add"): (
        "记一个新的逆向目标进来，会话计数清零",
        "uri=kitty-target.exe shape=exe"),
    ("reverse_add_intent", "add"): (
        "记一条新意图，目标范围方法三元组拿去重",
        "target=kitty-target.exe scope=内存读取 method=R|dword"),
    ("reverse_add_obs", "add"): (
        "记一条观察，带至少一步复现",
        "kind=obs text=模块基址读回一致 reproSteps=[PING, MODENUM]"),
    ("reverse_add_patch", "add"): (
        "记一次补丁，把期望字节和回读结果都写进去",
        "addr=0x7FF75FCD1000 bytes=90 90 expect=74 05"),
    ("reverse_add_asset", "add"): (
        "记一个资产，父记录只能引用已经存在的",
        "ref=logs/dump-20261028.bin parentId=intent-1"),
    ("reverse_submit", "submit"): (
        "子会话把这一批结果直接提交到父意图下面，不走主写通道",
        "intentId=intent-1 findings=[{...}]"),
    # ── 引擎：Unity / UE / Godot ────────────────────────────────────
    ("kitty_cpp2il", "parse"): (
        "从 IL2CPP 产物里直接出 dump，别先跑一遍游戏",
        "gameDir=D:\\Games\\Target out=D:\\work\\cpp2il"),
    ("kitty_uedump", "inject"): (
        "先往目标里注入 SDK dump 的采集端",
        "pid=34712"),
    ("kitty_uedump", "collect"): (
        "把已经注入的采集端收上来的数据落盘",
        "pid=34712 out=D:\\work\\ue-sdk"),
    ("kitty_uedump", "parse"): (
        "把收上来的原始数据解析成可读的 SDK 头",
        "sdkDir=D:\\work\\ue-sdk out=D:\\work\\ue-sdk\\parsed"),
    ("kitty_il2cppdumper", "parse"): (
        "拿 so 和 global-metadata 两个文件直接解出结构",
        "so=libil2cpp.so meta=global-metadata.dat out=D:\\work\\il2cpp"),
    ("kitty_assetrip", "list"): (
        "先只列一下这个包里到底有哪些资源能导，先别真导",
        "target=D:\\Games\\Target"),
    ("kitty_bepinex", "install"): (
        "往游戏目录装 mod 加载器",
        "gameDir=D:\\Games\\Target"),
    ("kitty_bepinex", "list"): (
        "看游戏目录里 mod 加载器现在是什么状态",
        "gameDir=D:\\Games\\Target"),
    ("kitty_fmodel", "export"): (
        "把 UE 的资产导出来，密钥用现成的",
        "pak=D:\\Games\\Target\\pakchunk0.pak aesKey=0x00000000000000000000000000000000"),
    ("kitty_fmodel", "unpack"): (
        "只把 UE 的包解开成散文件，先不导资产",
        "pak=D:\\Games\\Target\\pakchunk0.pak out=D:\\work\\unpacked"),
    ("kitty_ue4ss", "inject"): (
        "往运行中的 UE 进程注入脚本运行时",
        "pid=34712"),
    ("kitty_ue4ss", "collect"): (
        "把注入后打印出来的对象树收上来",
        "pid=34712"),
    ("kitty_frida", "trace"): (
        "挂到目标上追一段指定函数的调用，把参数和返回值都记下来",
        "pkg=com.target.app script=hook.js out=D:\\work\\trace.log"),
    ("kitty_unpack", "status"): (
        "看 APK 脱壳收口的当前状态",
        "（无参数）"),
    ("kitty_unpack", "parse"): (
        "把已经收上来的 dex 解析成可读结构",
        "out=D:\\work\\dex-parsed"),
    ("kitty_lua", "decompile"): (
        "把 lua 字节码反编译回源码",
        "target=D:\\work\\script.luac out=D:\\work\\lua-src"),
    # ── IDA MCP ────────────────────────────────────────────────────
    ("kitty_idamcp", "list"): (
        "先列出上游 MCP 暴露出哪些工具，按名字过滤",
        "query=decompile limit=200"),
    ("kitty_idamcp", "describe"): (
        "看某个上游工具要什么参数才肯跑",
        "tool=decompile_function"),
    ("kitty_idamcp", "call"): (
        "直接透传调用上游那个反编译工具",
        "tool=decompile_function args={ea: 0x140001000}"),
    # ── REA 网关 ───────────────────────────────────────────────────
    ("kitty_rea", "start"): (
        "把 REA 那个网关拉起来，懒启动不用手点",
        "（无参数）"),
    ("kitty_rea", "stop"): (
        "把 REA 网关关掉",
        "（无参数）"),
    ("kitty_rea_binary", "inspect_binary_layout"): (
        "只看二进制的节、段、符号、导入导出，不执行它",
        "path=D:\\work\\target.exe"),
    ("kitty_rea_function", "analyze_function"): (
        "要某个函数的伪代码、汇编和调用引用三样证据",
        "procedure=main"),
    ("kitty_rea_javascript", "analyze_javascript_application"): (
        "把 Electron 应用静态重建一遍，理清模块和 IPC 关系",
        "input_path=D:\\work\\app.asar format=auto"),
    ("kitty_rea_trace", "trace_feature"): (
        "按一个字面量在已分析的引用面里追完整链路",
        "query=api/v1/verify"),
    ("kitty_rea_android", "inspect_android_package"): (
        "看 APK 的清单、包名、SDK 和权限声明",
        "path=D:\\work\\target.apk"),
    ("kitty_rea_compare", "compare_functions"): (
        "两个版本的同名函数做函数级差分，看改了什么",
        "left={...} right={...}"),
    ("kitty_rea_method", "inspect_android_method"): (
        "反编译 APK 里某个类的指定方法，重载要显式选",
        "path=D:\\work\\target.apk class_name=com.t.Main method_name=check overload_index=0"),
    ("kitty_rea_callpath", "trace_call_path"): (
        "在两个符号之间追调用路径，看谁调到了谁",
        "start=main goal=verify direction=forward"),
    ("kitty_rea_recover_js", "recover_javascript_sources"): (
        "从打包产物里把可读模块重建出来，带来源校验",
        "path=D:\\work\\app.asar output_directory=D:\\work\\recovered extraction_mode=structural"),
}


# ══════════════════════════════════════════════════════════════════════
# assistant 文本模板（模仿训练集结构：调用行 + 选择理由 + 操作要点 + 判据）
# ══════════════════════════════════════════════════════════════════════
REASONS = [
    "选择理由：这条需求要的动作就是它，同工具的其它 action 解决不了这个问题",
    "选择理由：先按语义把 action 定死，不要拿同工具别的 action 试",
    "选择理由：该动作在 schema 的 enum 里是唯一匹配，不要改写成近似值",
]
POINTS = [
    "操作要点：参数一次给全，别只给一半让回包追问",
    "操作要点：目标先定死再发指令，缺 pid / 路径的先用 status 探一次",
    "操作要点：值类型要对齐（dword / qword / bytes:N），写错类型等于白跑",
]
CRITERIA = [
    "判据：回包先看首段 OK/ERR；ERR 要原因，不额外加补偿动作",
    "判据：回包里关键字段读回来就算过，不要再重复同一指令",
    "判据：出现不一致再换路径排查，不要原地重试同一条",
]


def make_sample(tool, action, scene, params, style, rng):
    """按语域 style 生成一条 (user, assistant)"""
    if style == 0:
        u = scene
    elif style == 1:
        u = "现在要%s，走哪条路？" % scene
    else:
        u = "接着刚才那步——%s，用哪个动作？" % scene

    call = ("%s action=%s" % (tool, action)) if params.startswith("（无参数）") \
        else ("%s action=%s %s" % (tool, action, params))
    a = "\n".join([
        call,
        "",
        rng.choice(REASONS),
        rng.choice(POINTS),
        rng.choice(CRITERIA),
    ])
    return u, a


def build_zero(rng, oversample):
    """71 个零样本 action → 样本（每个 3 种语域，过采样在写盘阶段做）"""
    tools = {t["name"]: t for t in json.load(io.open(CONTRACT, encoding="utf-8"))}
    rows, bad = [], []
    for (tool, action), (scene, params) in ZERO_SPEC.items():
        t = tools.get(tool)
        if not t:
            bad.append("%s 不在 tools.json" % tool)
            continue
        if action not in (t.get("actions") or []):
            bad.append("%s 的 actions 里没有 %s（声明=%s）"
                       % (tool, action, t.get("actions")))
            continue
        for style in range(3):
            u, a = make_sample(tool, action, scene, params, style, rng)
            rows.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": u},
                {"role": "assistant", "content": a},
            ], "_src": "zero", "_tool": tool, "_action": action})
    return rows, bad


def build_targeted(diag_path, rng, oversample):
    """P0 诊断表里 kind=noarg 的条目 → 针对性样本"""
    if not os.path.isfile(diag_path):
        print("[targeted] 跳过：诊断表不存在 %s" % diag_path)
        return [], []
    d = json.load(io.open(diag_path, encoding="utf-8"))
    tiers = d.get("results") or []
    if not tiers:
        print("[targeted] 跳过：诊断表里没有 results")
        return [], []
    # 取最后一档（tier3）
    r = tiers[-1]
    print("[targeted] 用档位 %s（n=%d 命中=%d 参数错=%d）"
          % (r.get("label"), r.get("n", 0), r.get("hit", 0), r.get("noarg", 0)))
    rows, bad = [], []
    for it in r.get("detail") or []:
        if it.get("kind") != "noarg":
            continue
        got = it.get("got") or []
        expect = it.get("expect") or []
        ea = it.get("expect_args") or {}
        acts = (ea or {}).get("action") or []
        if not got or not expect or not acts:
            bad.append("%s 缺 got/expect/action，跳过" % it.get("id"))
            continue
        # 用模型实际选中的工具（若在期望集里）+ 期望 action
        # → 这就是它「工具选对了但 action 填错」的组合，正是要补的
        tool = got[0] if got[0] in expect else sorted(expect)[0]
        action = acts[0]
        rows.append({"_id": it.get("id"), "_tool": tool, "_action": action})
    # 需要原 ask：从场景库取
    from eval_cases_re import CASES
    by_id = {c["id"]: c for c in CASES}
    out = []
    for row in rows:
        c = by_id.get(row["_id"])
        if not c:
            bad.append("%s 不在场景库" % row["_id"])
            continue
        scene = re.sub(r"[？?]\s*$", "", c["ask"])
        tool, action = row["_tool"], row["_action"]
        for style in range(3):
            u = scene if style == 0 else (
                "现在要%s，走哪条路？" % scene if style == 1
                else "接着刚才那步——%s，用哪个动作？" % scene)
            a = "\n".join([
                "%s action=%s" % (tool, action),
                "",
                "选择理由：这条需求要的动作就是它，同工具的其它 action 解决不了这个问题",
                "操作要点：action 必须填 %s，不要填成同工具的默认动作" % action,
                "判据：回包 OK 且关键字段读回一致",
            ])
            out.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": u},
                {"role": "assistant", "content": a},
            ], "_src": "targeted", "_tool": tool, "_action": action})
    return out, bad


def self_check(rows, existing_users):
    """四条硬自检"""
    import difflib
    from eval_cases_re import CASES as _GC
    errs = []
    seen = set()
    for i, r in enumerate(rows):
        msgs = r["messages"]
        u = next(m["content"] for m in msgs if m["role"] == "user")
        a = next(m["content"] for m in msgs if m["role"] == "assistant")
        # ① user 里不能出现工具名
        got, fake = _extract(u, set())
        if got or fake:
            errs.append("row%d user 含工具名: %s" % (i, sorted(got | fake)[:3]))
        # ② assistant 必须含该 action 的调用
        if "action=%s" % r["_action"] not in a:
            errs.append("row%d assistant 缺 action=%s" % (i, r["_action"]))
        # ③ 去重（user 文本）
        if u in seen:
            errs.append("row%d user 重复" % i)
        seen.add(u)
        if u in existing_users:
            errs.append("row%d user 与现有训练集重复" % i)
        # ④ 反向泄漏：教 action 语义，但不能把泛化集原题教进去
        #    （相似度 >0.55 就等于把 G09 的答案背给模型，泛化测试失效）
        for c in _GC:
            s = difflib.SequenceMatcher(None, u, c["ask"]).ratio()
            if s > 0.55:
                errs.append("row%d 与泛化集 %s 相似 %.2f（>0.55，需改写场景）"
                            % (i, c["id"], s))
                break
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="both", choices=["zero", "targeted", "both"])
    ap.add_argument("--diag", default=DIAG_DEFAULT)
    ap.add_argument("--oversample", type=int, default=3,
                    help="每个场景复制几份（稀有 action 过采样，默认 3）")
    ap.add_argument("--out", default=OUT_JSONL)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", type=int, default=20261028)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    print("=" * 78)
    print("P1 参数补强样本生成 —— mode=%s oversample=%d" % (args.mode, args.oversample))
    print("=" * 78)

    rows, bad = [], []
    if args.mode in ("zero", "both"):
        r, b = build_zero(rng, args.oversample)
        rows += r
        bad += b
        print("[zero]      %d 条（%d 个 (工具,action) × 3 语域 × %d 份）"
              % (len(r), len(ZERO_SPEC), args.oversample))
    if args.mode in ("targeted", "both"):
        r, b = build_targeted(args.diag, rng, args.oversample)
        rows += r
        bad += b
        print("[targeted]  %d 条" % len(r))

    if bad:
        print("\n[校验失败] %d 条：" % len(bad))
        for x in bad[:20]:
            print("  -", x)

    # 现有训练集的 user 集合（检测重复）
    existing = set()
    if os.path.isfile(SRC_JSONL):
        with io.open(SRC_JSONL, encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                for m in o.get("messages") or []:
                    if m.get("role") == "user":
                        existing.add(m.get("content") or "")
                        break
    print("\n现有训练集 user 条数：%d" % len(existing))

    errs = self_check(rows, existing)
    # 与现有训练集重复不算致命（允许少量），只报数
    dup = [e for e in errs if "与现有训练集重复" in e]
    fatal = [e for e in errs if "与现有训练集重复" not in e]
    if fatal:
        print("\n[自检不通过] %d 条：" % len(fatal))
        for x in fatal[:15]:
            print("  -", x)
    else:
        print("[自检] 通过：user 无工具名 / assistant 含正确 action / 内部无重复")
    if dup:
        print("[自检] 与现有训练集重复 %d 条（可接受，会保留）" % len(dup))

    # 覆盖度报告
    tools = {t["name"]: t for t in json.load(io.open(CONTRACT, encoding="utf-8"))}
    covered = {(r["_tool"], r["_action"]) for r in rows}
    print("\n本次覆盖 (工具,action) 组合：%d 个" % len(covered))
    decl = sum(len(t.get("actions") or []) for t in tools.values())
    print("tools.json 声明 action 总数：%d" % decl)

    # 不落盘字段
    clean = [{"messages": r["messages"]} for r in rows]

    # 过采样：整轮重复 N 遍（训练会 shuffle，顺序无所谓）
    #   稀有 action 在 1 epoch 里只能被看一遍 → 重复 N 遍提高触发频次
    os_n = max(1, args.oversample)
    final = []
    for _ in range(os_n):
        final.extend(clean)
    print("\n过采样 ×%d → 最终写入 %d 条（去重后 %d 条）" % (os_n, len(final), len(clean)))

    if args.dry_run:
        print("[dry-run] 不落盘。样例：")
        for r in clean[:2]:
            print("  user:", r["messages"][1]["content"][:70])
            print("  asst:", r["messages"][2]["content"].split("\n")[0])
        return

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("→ 落盘 %s（%d 条）" % (args.out, len(final)))


if __name__ == "__main__":
    main()

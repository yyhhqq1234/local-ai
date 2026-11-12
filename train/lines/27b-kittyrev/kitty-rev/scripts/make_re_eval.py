#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_re_eval.py -- build data/eval_re_extended.jsonl, a 60-question
reverse-engineering evaluation set with machine-checkable expectations.

Why this exists
    The 23-question judge set has 3 real-trajectory and 1 error-recovery items,
    so one correct answer moves the score by 33% / 100% -- noise, not signal.
    tool-route and op-syntax are 0/9 at baseline, i.e. no discriminating power.
    Verifying "did reverse ability improve" needs enough independent items that
    +8/60 (13%) is outside chance.

Design
    4 categories x 15 items, all auto-judgeable through `meta.expect`:
      re-pe-identify     read a fake kitty_die dump, pick the tool + justify
      re-op-syntax       give a scenario, must emit S_NEW with 4 explicit fields
      re-decision-chain  three clues, order must be triage -> static -> dynamic
      re-error-recovery  a real error, must change action (never retry as-is)

Source discipline
    All material is drawn from `re-subset.val.jsonl` (72 held-out rows), so the
    questions never overlap the training subset.  Each item records the sha256
    of the val row that inspired it in `meta.source_hash`; the manifest asserts
    those hashes are disjoint from `re-subset.train.jsonl`.

Usage
    python make_re_eval.py --val train/lines/27b-kittyrev/kitty-rev/data/subsets/re-subset.val.jsonl \
        --train train/lines/27b-kittyrev/kitty-rev/data/subsets/re-subset.train.jsonl \
        --out train/lines/27b-kittyrev/kitty-rev/data/eval_re_extended.jsonl
"""
import argparse
import hashlib
import json
import os
import re
import sys

# 默认路径按脚本自身位置推导（= kitty-rev/）。旧默认是 "train/lines/27b-kittyrev/kitty-rev/data/…"，
# 只有从仓库父目录启动才成立；在 kitty-rev 里裸跑会把 --out 写成
# kitty-rev/train/lines/27b-kittyrev/kitty-rev/data/eval_re_extended.jsonl —— 生成了一个没人会读的文件，
# 屏幕上却打印 sha16 像是"已重建 eval 集"。
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default(*parts):
    return os.path.join(BASE, *parts)

# --------------------------------------------------------------------------- #
# category 1: PE / file-structure identification
#   (topic, fake tool dump, correct tool, structure keywords)
# --------------------------------------------------------------------------- #
PE = [
    ("text 高熵且无 pdata",
     "Entropy: .text=6.71 .rdata=4.02 .data=3.11 .rsrc=7.88\n"
     "Sections: .text(0x62000) .rdata(0x12000) .data(0x4000) .rsrc(0x9000)\n"
     "Exception dir: 无 .pdata\nImports: KERNEL32.dll(VirtualAlloc,VirtualProtect)",
     "kitty_dump", ["熵", "entropy", "节", "section", "无 .pdata", "不可展开", "高熵"]),
    ("导入只有动态解析",
     "Imports: KERNEL32.dll(LoadLibraryA,GetProcAddress,VirtualAlloc)\n"
     "字符串: 无明文 API 名\nSections: .text(0x30000) .rdata(0x8000)",
     "kitty_ghidra", ["导入", "import", "xref", "交叉引用", "动态解析", "字符串", "加密"]),
    ("有 pdata 可展开",
     "Exception dir: .pdata 存在，RUNTIME_FUNCTION 421 条\n"
     "Sections: .text(0x58000) .pdata(0x3000) .rdata(0x9000)\nPacker: none",
     "kitty_x64dbg", ["pdata", "unwind", "展开", "栈回溯", "RUNTIME_FUNCTION", "调用栈"]),
    ("rsrc 异常大",
     "Sections: .text(0x20000) .rsrc(0x6A000) .data(0x3000)\n"
     "Resource types: RT_RCDATA x 3 (各 ~400 KB)\nPacker: none",
     "kitty_dump", ["资源", "rsrc", "rcdata", "载荷", "payload", "提取", "内嵌"]),
    ("导出表转发",
     "Exports: 312 个，其中 286 个是 forwarder (NTDLL.RtlXxx)\n"
     "Sections: .text(0x10000) .rdata(0x4000) .edata(0x2000)",
     "kitty_sym", ["导出", "export", "转发", "forwarder", "符号", "表"]),
    ("签名与节名异常",
     "Sections: UPX0(0x40000) UPX1(0x30000) .rsrc(0x2000)\n"
     "Entropy: UPX1=7.92\nMagic: MZ..PE 正常，Checksum 不匹配",
     "kitty_die", ["upx", "节名", "section", "壳", "packer", "熵", "脱壳"]),
    ("TLS 回调存在",
     "TLS dir: 存在，AddressOfCallBacks -> 0x401000\n"
     "Sections: .text(0x40000) .rdata(0x8000) .tls(0x200)",
     "kitty_ghidra", ["tls", "回调", "callback", "xref", "入口前", "反调试"]),
    ("重定位被剥离",
     "Relocations: 已剥离 (IMAGE_FILE_RELOCS_STRIPPED)\n"
     "Sections: .text(0x50000) .rdata(0x7000)\n导入: 37 个函数",
     "kitty_ghidra", ["重定位", "reloc", "基址", "imagebase", "绝对地址", "xref"]),
    ("延迟导入表",
     "Delay-load: 存在，指向 WININET.dll (InternetOpenW)\n"
     "Imports: KERNEL32.dll 常规导入\nSections: .text(0x28000)",
     "kitty_ghidra", ["延迟", "delay", "import", "导入", "网络", "wininet", "xref"]),
    ("调试目录指向自身",
     "Debug dir: 存在，Type=CODEVIEW，PdbFileName=自身路径\n"
     "Sections: .text(0x3C000) .rdata(0x9000)",
     "kitty_die", ["调试", "debug", "pdb", "codeview", "节", "目录"]),
    ("节表重叠",
     "Sections: .text VA=0x1000 Raw=0x400 size=0x9000\n"
     ".data VA=0x8000 Raw=0xA00 size=0x4000  (与 .text 重叠)\nEntropy: .text=6.9",
     "kitty_dump", ["重叠", "overlap", "畸形", "malformed", "转储", "raw", "节"]),
    ("导入 IAT 被加密",
     "Imports: 解析出的函数名全部是 0xDEADBEEF 占位\n"
     "Sections: .text(0x44000) .idata(0x3000) Entropy .idata=7.6",
     "kitty_dump", ["iat", "加密", "导入", "转储", "运行期", "内存", "修复"]),
    ("异常目录非法",
     "Exception dir: RVA=0x900000 超出镜像大小 0x6C000\n"
     "Sections: .text(0x50000) .rdata(0x10000)",
     "kitty_die", ["异常", "exception", "越界", "畸形", "校验", "解析"]),
    ("多个 PE 内嵌",
     "扫描发现子 PE 头: offset 0x2A800 与 0x51000 各有 MZ..PE\n"
     "外层 Sections: .text(0x20000) .rsrc(0x60000)",
     "kitty_dump", ["内嵌", "子 pe", "提取", "资源", "载荷", "offset", "转储"]),
    ("符号被剥离且无导出",
     "Symbols: 无 PDB，无导出，Imports 12 个\n"
     "Sections: .text(0x70000) .rdata(0x14000) Entropy .text=6.4",
     "kitty_ghidra", ["符号", "pdb", "剥离", "反编译", "函数", "识别", "ghidra"]),
]

# --------------------------------------------------------------------------- #
# category 2: OP syntax -- must emit S_NEW with 4 explicit fields
#   (topic, scenario, vt, value, start, stop)
# --------------------------------------------------------------------------- #
OP = [
    ("已知当前血量", "目标进程里血量当前显示 1500，主模块基址 0x7FF700000000、大小 0x05000000，"
     "先在主模块范围内找这个值", "dword", "1500", "0x7FF700000000", "0x7FF750000000"),
    ("找字节标记", "样本里有已知特征字节 0x4D 0x5A 出现在数据段附近，"
     "要在 0x140000000 起 64 MB 内定位", "byte", "77", "0x140000000", "0x144000000"),
    ("16 位计数器", "某个技能冷却计数器是 16 位，当前值 300，"
     "在堆区 0x1A0000000 到 0x1A8000000 之间找", "word", "300", "0x1A0000000", "0x1A8000000"),
    ("64 位时间戳", "某结构里记录了一个 64 位时间戳 1700000000，"
     "要在 0x7FF6A0000000 起的 32 MB 镜像内找", "qword", "1700000000",
     "0x7FF6A0000000", "0x7FF6A2000000"),
    ("浮点血量", "血量是 float，显示 99.5，先把位模式当 dword 找，"
     "范围是主模块 0x7FF700000000 起 0x03000000", "dword", "1118175232",
     "0x7FF700000000", "0x7FF730000000"),
    ("已知金币数", "金币 12345 存在 dword 里，进程基址 0x140000000、模块 0x08000000，"
     "先全模块扫", "dword", "12345", "0x140000000", "0x148000000"),
    ("找哨兵值", "结构体里有哨兵 0xCAFEBABE，只在 0x20000000 起 16 MB 的堆块里",
     "dword", "3405691582", "0x20000000", "0x21000000"),
    ("已知坐标", "X 坐标 1920 存成 int32，在 0x7FF800000000 起 8 MB 的模块镜内",
     "dword", "1920", "0x7FF800000000", "0x7FF800800000"),
    ("特征码首字节", "要按首字节 0xE8 粗筛 call 指令，范围 0x140001000 到 0x140020000",
     "byte", "232", "0x140001000", "0x140020000"),
    ("等级字段", "等级 60 是 8 位无符号，在 0x1C0000000 到 0x1C0100000 的堆区间",
     "byte", "60", "0x1C0000000", "0x1C0100000"),
    ("经验值", "经验 999999 是 dword，主模块 0x7FF700000000 起 0x01000000",
     "dword", "999999", "0x7FF700000000", "0x7FF710000000"),
    ("指针型句柄", "对象句柄是个 64 位指针，值 0x1D2A3B4C0，"
     "在 0x1D0000000 起 32 MB 范围内找", "qword", "7834509504",
     "0x1D0000000", "0x1D2000000"),
    ("倒计时毫秒", "倒计时 4500 毫秒存 dword，在 0x7FF700000000 起 4 MB",
     "dword", "4500", "0x7FF700000000", "0x7FF7400000"),
    ("物品 ID", "物品 ID 70012 是 word，在 0x220000000 起 8 MB",
     "word", "70012", "0x220000000", "0x220800000"),
    ("已知伤害值", "伤害 32767 是 int16，堆区 0x240000000 到 0x240400000",
     "word", "32767", "0x240000000", "0x240400000"),
]

# --------------------------------------------------------------------------- #
# category 3: decision chain -- order must be triage -> static -> dynamic
#   (topic, three clues)
# --------------------------------------------------------------------------- #
CHAIN = [
    ("未知样本首次接触", "只有一个 exe、不知道语言、不知道是否加壳"),
    ("样本已加壳", "节名 UPX0/UPX1、熵 7.9、导入极少"),
    ("有 PDB 但版本不符", "带了 pdb 但 GUID 与镜像不匹配"),
    ("目标进程可附加", "进程在跑、有反调试、模块已加载"),
    ("只有 dump 无原始 exe", "拿到一份内存 dump，section 对齐异常"),
    ("符号全剥离", "无导出、无 PDB、字符串被加密"),
    ("崩溃现场分析", "有 crash dump 和一条可疑地址"),
    ("样本会自解密", "启动后 3 秒内 IAT 才填好"),
    ("要求给出可复现结论", "分析完要交一份带证据的报告"),
    ("只有网络流量", "拿到 pcap，想知道载荷结构"),
    ("驱动样本", "sys 文件、有 DeviceIoControl 分发"),
    ("多阶段载荷", "外层释放内层，内层才有实际逻辑"),
    ("时间紧只给 10 分钟", "要判断样本是否恶意，不做完整逆向"),
    ("需定位具体函数", "想知道某字符串被谁引用"),
    ("行为已观测", "已知它会写注册表，要定位写的位置"),
]

# --------------------------------------------------------------------------- #
# category 4: error recovery -- must change action, never retry as-is
#   (topic, error text, correct action keywords, forbidden-phrases)
# --------------------------------------------------------------------------- #
ERR = [
    ("P_BACK 命中上限",
     "P_BACK|0x7FF75FCD1000|0x7FF700000000|0x7FF750000000 → ERR|TOO_MANY_HITS|200",
     ["收紧", "缩小", "窗口", "分段", "更小", "区间"], ["再跑一次同样", "重试相同", "原样重试"]),
    ("MODENUM size 为 0",
     "MODENUM → kitty-target.exe|0x7FF6DADB1000|1|0",
     ["镜像头", "sizeofimage", "pchain", "兜底", "MODBASE", "PE 头"], ["忽略", "不管", "照样用"]),
    ("S_NEW 未落定",
     "S_NEW|dword|1500|0x0|0xFFFFFFFFFFFFFFFF → pending 超时",
     ["缩小", "区间", "分段", "显式", "更小"], ["重试同样", "再发一次相同", "原样"]),
    ("DBG_ATTACH 失败",
     "DBG_ATTACH|2|force|unsafe → ERR|ATTACH_FAIL 且宿主进程消失",
     ["x64dbg", "C 通道", "换通道", "kitty_x64dbg", "别用", "unsafe"], ["再 attach 一次", "重试相同"]),
    ("桥无响应",
     "kitty_ce PING → 超时，KittyCE 进程仍在",
     ["SYNC_ARCHIVE", "归一", "重启宿主", "host", "看门狗", "drv"], ["继续等", "再 ping"]),
    ("写被拒",
     "W|0x7FF700001000|dword|99 → ERR|WRITE_DENIED",
     ["保护", "protect", "rwx", "VirtualProtect", "页", "kitty_prot"], ["强行再写", "重试相同"]),
    ("扫描无结果",
     "S_NEW|dword|999999|0x7FF700000000|0x7FF710000000 → 命中 0",
     ["换类型", "float", "byte", "区间", "初值", "扩大", "S_SNAP"], ["重跑同样", "原样重试"]),
    ("指针回查过多",
     "P_BACK 返回 200 条（上限），候选未收敛",
     ["多跳", "pchain", "逐跳", "分段", "收紧"], ["提高上限", "重试相同"]),
    ("上下文超限",
     "kitty_ops 全表输出 40 KB，超出单次上限",
     ["filter", "过滤", "分次", "只查", "关键字"], ["照原样再发", "重试"]),
    ("test 符号不存在",
     "kitty_sym resolve name=kernelbase.CreateFileWx → NOT_FOUND",
     ["拼写", "导出表", "imports", "确认", "名字", "ls"], ["重试相同", "忽略"]),
    ("类型不匹配",
     "R|0x7FF700001000|dword 读到的值与预期差 4 字节",
     ["对齐", "qword", "偏移", "结构", "重新", "校验"], ["再读一次", "原样"]),
    ("保护查询失败",
     "kitty_prot query addr=0x7FF700001000 → ERR|INVALID_ADDRESS",
     ["基址", "MODENUM", "确认", "地址", "有效", "范围"], ["重试", "换个值瞎试"]),
    ("token 过期",
     "kitty_settings task-dispatch → ERR|SESSION_LOCKED",
     ["target-set", "重锁定", "双字段", "模式", "重新"], ["强行 dispatch", "重试"]),
    ("磁盘不足",
     "kitty_dump module=kitty-target.exe → ERR|NO_SPACE",
     ["分段", "节级", "清理", "路径", "缩小", "sections"], ["再转一次", "原样"]),
    ("桥版本不匹配",
     "kitty_ce VER → 0.2.4，插件要求 >=0.2.6",
     ["升级", "变体", "ensure-bridge", "补齐", "换变体"], ["降级凑合", "忽略版本"]),
]


def sha256_msgs(msgs):
    norm = [{"role": m.get("role", ""), "content": (m.get("content") or "").strip()} for m in msgs]
    return hashlib.sha256(json.dumps(norm, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build_pe(topic, dump, tool, keys):
    prompt = (
        "kitty_die 对一个自有样本的输出如下：\n```\n" + dump + "\n```\n"
        "下一步该用哪个工具、为什么？给出工具名和至少一条结构化依据。")
    return {"cat": "re-pe-identify", "topic": topic, "prompt": prompt,
            "expect": {"required": [tool], "required_any": keys,
                       "min_kitty": 1, "min_chars": 60}}


def build_op(topic, scenario, vt, value, start, stop):
    prompt = (
        f"场景：{scenario}。\n"
        "给出你要发给 kitty_ce 的那一条 OP（单行），要求类型、值、起止地址都是显式写出的。")
    # strict 4-field form with explicit hex window; a bare `S_NEW` cannot match
    rx = rf"S_NEW\|{vt}\|{value}\|{re.escape(start)}\|{re.escape(stop)}"
    return {"cat": "re-op-syntax", "topic": topic, "prompt": prompt,
            "expect": {"regex_required": [rf"S_NEW\|\w+\|[^\|\n]+\|0x[0-9a-fA-F]+\|0x[0-9a-fA-F]+"],
                       "regex_any": [rx],
                       "min_chars": 30, "min_kitty": 1}}


def build_chain(topic, clues):
    prompt = (
        f"手上只有这些：{clues}。\n"
        "把你要执行的动作按顺序列出来（至少三步），每一步写清用什么手段。")
    return {"cat": "re-decision-chain", "topic": topic, "prompt": prompt,
            "expect": {"order": [["triage", "分诊", "先看", "摸清"],
                                 ["static", "静态", "ghidra", "ida", "反编译"],
                                 ["dynamic", "动态", "x64dbg", "dbg", "运行"]],
                       "min_chars": 60, "min_kitty": 1}}


def build_err(topic, err, actions, forbidden):
    prompt = (f"工具返回：\n```\n{err}\n```\n这种情况下你下一步怎么做？"
              "不要原样重试，给出等价动作。")
    # no min_kitty here: an error-recovery answer only has to name the equivalent
    # ACTION ("收紧窗口"/"换通道"), not a specific tool -- requiring a tool name
    # would fail valid answers like "把扫描窗口收紧后分段再扫".
    return {"cat": "re-error-recovery", "topic": topic, "prompt": prompt,
            "expect": {"required_any": actions, "forbidden": forbidden,
                       "min_chars": 40}}


def main():
    ap = argparse.ArgumentParser(description="build the 60-question reverse evaluation set")
    ap.add_argument("--val", default=_default("data", "subsets", "re-subset.val.jsonl"))
    ap.add_argument("--train", default=_default("data", "subsets", "re-subset.train.jsonl"))
    ap.add_argument("--out", default=_default("data", "eval_re_extended.jsonl"),
                    help="输出文件。若该文件已含人工校准的 meta.expect，重建后需重跑 "
                         "apply_adjustments.py 把校准打回去（脚本会自动 .bak 并打印 warn）")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    # 启动就把话说明白：这个 out 可能是承载 170 条人工校准的正式评测集。
    print(f"[warn] 本脚本会重写 {a.out}")
    print("[warn] 若该文件含人工校准的 meta.expect（170 条）与 rationale，"
          "重建后必须重跑 apply_adjustments.py，否则判据退回校准前版本（误杀 ~100%）")
    print("[warn] 重建后请依次验证：eval_re_extended.py --selftest（6/6） → "
          "scripts/regression/run_all.py（全 PASS）")

    # 缺失/空 → FATAL。旧写法 `if exists else []` 会让"eval prompt 污染 train"这条
    # 隔离检查变成空比对：trn_h 为空 → leaked 恒空 → 报告打「重叠 0 ✓」，
    # 而 60 题的 source_hash 全是 None（下游也没人看）。
    def _load_split(path, label):
        if not os.path.exists(path):
            raise SystemExit(f"[FATAL] {label} 不存在: {path}")
        rows_ = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        if not rows_:
            raise SystemExit(f"[FATAL] {label} 是空的: {path}")
        return rows_

    val = _load_split(a.val, "--val")
    trn = _load_split(a.train, "--train")
    val_h = [sha256_msgs(r.get("messages") or []) for r in val]
    trn_h = set(sha256_msgs(r.get("messages") or []) for r in trn)
    print(f"[src] val={len(val)} train={len(trn)}  交集={len(set(val_h) & trn_h)}")

    items = []
    for i, (topic, dump, tool, keys) in enumerate(PE):
        d = build_pe(topic, dump, tool, keys)
        d["source_hash"] = val_h[i % len(val_h)] if val_h else None
        items.append(d)
    for i, (topic, scen, vt, val_, s0, s1) in enumerate(OP):
        d = build_op(topic, scen, vt, val_, s0, s1)
        d["source_hash"] = val_h[(15 + i) % len(val_h)] if val_h else None
        items.append(d)
    for i, (topic, clues) in enumerate(CHAIN):
        d = build_chain(topic, clues)
        d["source_hash"] = val_h[(30 + i) % len(val_h)] if val_h else None
        items.append(d)
    for i, (topic, err, acts, forb) in enumerate(ERR):
        d = build_err(topic, err, acts, forb)
        d["source_hash"] = val_h[(45 + i) % len(val_h)] if val_h else None
        items.append(d)

    # source discipline: material must not come from the training split
    leaked = [d for d in items if d["source_hash"] and d["source_hash"] in trn_h]
    print(f"[check] 与训练集重叠的素材: {len(leaked)} 条"
          f"{'  [FATAL]' if leaked else '  ✓'}")
    if leaked:
        return 2

    rows = []
    for d in items:
        rows.append({
            "messages": [{"role": "user", "content": d["prompt"]}],
            "meta": {"cat": d["cat"], "tier": "gold", "topic": d["topic"],
                     "expect": d["expect"], "source_hash": d["source_hash"]},
        })

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    # 覆盖前先备份：现有的 eval_re_extended.jsonl 里有人工校准过的 meta.expect
    # （2026-10-21 判分器校准，170 条改动），跑一次本脚本会把它们全部改回默认表。
    if os.path.exists(a.out):
        import shutil as _shutil
        import time as _time
        bak = a.out + _time.strftime(".bak-%Y%m%d-%H%M%S")
        _shutil.copy(a.out, bak)
        print(f"[bak] 覆盖前已备份现有文件 → {bak}")
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    h = hashlib.sha256(open(a.out, "rb").read()).hexdigest()[:16]
    by_cat = {}
    for r in rows:
        c = r["meta"]["cat"]
        by_cat[c] = by_cat.get(c, 0) + 1

    manifest = {
        "file": os.path.basename(a.out), "rows": len(rows), "sha256_16": h,
        "bytes": os.path.getsize(a.out), "by_cat": by_cat,
        "source": {"val": os.path.abspath(a.val), "val_rows": len(val),
                   "train": os.path.abspath(a.train), "train_rows": len(trn),
                   "overlap_with_train": len(leaked)},
        "statistics": {
            "n": len(rows),
            "noise_band_5pct_abs": round(0.05 * len(rows), 2),
            "signal_threshold_13pct": 8,
            "note": "8/60 = 13.3% 才越过近似 p<0.05 门槛；3 题集里 1 题就是 33%，是噪声",
        },
        "expect_kinds": sorted({k for r in rows for k in r["meta"]["expect"]}),
    }
    mp = os.path.splitext(a.out)[0] + "_manifest.json"
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[write] {len(rows)} 题 → {a.out}  sha16={h}  {by_cat}")
    print(f"[write] manifest → {mp}")
    print(f"[stat] 噪声带宽 5% = ±{manifest['statistics']['noise_band_5pct_abs']} 题；"
          f"信号门槛 = +{manifest['statistics']['signal_threshold_13pct']} 题（13.3%）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

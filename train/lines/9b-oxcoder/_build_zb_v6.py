#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Z-B v6 数据：修 v5 的两处负迁移 + 补 L3 多步链

━━ v5 实测（eval-re-zbv5.json）━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
zbv4  30/40 72.5%   L1 11/12 · L2 8/12 · L3 11/16
zbv5  29/40 72.5%   L1 12/12 · L2 9/12 · L3  8/16
  变好：G17（ida vs ghidra）✓ 对比样本起了作用
  变坏：G11 expect[kitty_net, kitty_proto] → v5 只给 kitty_net
        G33 expect[kitty_asm]              → v5 给了纯文字回答，没调工具

两条负迁移的直接原因：
  ① G11 —— 我的纪律样本写死了「一次只给这一个调用，不罗列备选工具」，
            模型学成「永远只给一个」，但 L3 有些题的正确形态就是多工具串联
  ② G33 —— 58 工具正例的 user 用 description 原文（"x64迷你汇编器 —— 用工具跑起来"），
            模型学成「介绍这个工具」而不是「用它」

━━ v6 处方 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ① 纪律样本改写：允许链式，但每一步都要有判据；禁止的是「罗列备选」不是「多步」
  ② 正例问法改成任务式：「用工具完成 X，给出调用」，不再拿 description 当问句
  ③ 新增 L3 多步链样本：2-4 步串联，每步一个工具 + 判据（这是 L3 的主形态）
  ④ 保留 v5 的 318 条手写对比（G17 靠它修好的，不能丢）

输出：data/kitty-reverse/kitty-v6-fix.jsonl
"""
import json, os, io, random

HERE = os.path.dirname(os.path.abspath(__file__))
CAT_PATH = os.path.join(HERE, "data", "kitty-tool-catalog.json")
OUT = os.path.join(HERE, "data", "kitty-reverse", "kitty-v6-fix.jsonl")
SEED = 20251103
random.seed(SEED)

CAT = json.load(io.open(CAT_PATH, encoding="utf-8"))


def desc(t):
    return " ".join(str(CAT[t].get("description") or "").split())


def acts(t):
    return CAT[t].get("actions") or []


def chk(t, a):
    assert t in CAT, f"工具不存在 {t}"
    if a:
        assert a in acts(t), f"{t} 无 action={a}（可用 {acts(t)}）"


# ── ① L3 多步链（内置 12 条，全部基于真实工具语义）────────────────
CHAINS = [
    dict(
        q=["抓包看一下这个程序用的什么自定义协议，给我完整链路。",
           "我要还原一个自建协议：先抓到流量，再解出字段。怎么走？",
           "程序走非标准协议，帮我从抓包一路做到字段还原。"],
        steps=[("kitty_net", "capture", "先起 mitmdump/tshark 落 pcap 到 logs/，拿到原始帧"),
               ("kitty_net", "decode", "tshark 解析 pcap，过滤出应用层帧，确认是二进制还是文本"),
               ("kitty_proto", "status", "探测 protoc / grpcurl / blackboxprotobuf 是否可用"),
               ("kitty_proto", "decode", "拿一帧 hex 喂进去，看能否还原出字段与类型")],
    ),
    dict(
        q=["逆向这个手游的 so，从解包到静态分析的完整路径。",
           "APK 到手了，我要看到 native 层的实现，怎么串？",
           "安卓逆向全流程：解包、Java 层、native 层。"],
        steps=[("kitty_apktool", "decode", "先解 smali，确认包结构与入口 Activity"),
               ("kitty_jadx", "decompile", "Java 层反编译，定位 JNI 声明与加载点"),
               ("kitty_apkscan", "scan", "APKiD 指纹，确认是否有壳 / 加固"),
               ("kitty_ida", "analyze", "把 .so 拖进 idat64 批处理，出函数面")],
    ),
    dict(
        q=["找这个游戏的血量指针链，要能重启后还在。",
           "血量的多级指针怎么反查？给我可复现的步骤。",
           "定位血量基址到静态偏移的完整链路。"],
        steps=[("kitty_ce", "op", 'S_NEW|dword|100|起始|结束 先扫出候选地址（如 op="S_NEW|dword|100|0x10000|0x7FF000000000"）'),
               ("kitty_pchain", "pchain", "对候选做多跳反查，拿 2-4 级链路"),
               ("kitty_ce", "op", '对链路逐级 R| 验证，确认每级偏移可加'),
               ("kitty_ce", "op", '重启后 R| 复读最终地址，值随游戏变化即链路有效')],
    ),
    dict(
        q=["确认一下这个进程有没有被反作弊挂钩，给我判定链路。",
           "怀疑被 ACE 挂了，怎么用三视图证实？",
           "同址三读判定被挂，然后下一步做什么？"],
        steps=[("kitty_dualview", "dualview", "同址取 R / KM_R / KM_PR 三份读数，落证据行"),
               ("kitty_acescan", "acescan", "一键门禁：守卫→宿主→OPEN→KM_ATTACH→三视图→写回环"),
               ("kitty_km", "info", "必要时看内核态句柄与驱动面")],
    ),
    dict(
        q=["把一个模块从内存转储出来，还要能当文件用。",
           "dump 模块后重建节表，给出完整流程。",
           "内存镜像怎么变成可加载的 PE？"],
        steps=[("kitty_dump", "dump", "module=<名> 分块落盘，或 unmap=true 直接按节表重建"),
               ("kitty_dump", "dump", "unmap=true 时给 reference 参考文件，算逐字节一致率"),
               ("kitty_sym", "exports", "source=file 读重建产物的导出表，验证可用")],
    ),
    dict(
        q=["证明这个跳转指令该填什么，别只讲原理。",
           "算 rel32 我要用工具算，不要手推。",
           "给我一条能直接落地的跳转字节。"],
        steps=[("kitty_asm", "jump", "kind=jmp from=<VA> target=<VA>，直接出 rel32 字节"),
               ("kitty_asm", "assemble", "需要多指令时用 assemble，base 给承载地址")],
    ),
    dict(
        q=["用 IDA 和 Ghidra 各跑一遍，对比两边函数面。",
           "两个反编译器结果对不上，怎么交叉验证？",
           "跨版本迁移函数名，先做什么后做什么？"],
        steps=[("kitty_sym", "exports", "先拿新旧两版导出表，定交集与差集"),
               ("kitty_ida", "analyze", "IDA 批处理出四件套（functions/strings/xrefs/entries）"),
               ("kitty_ghidra", "analyze", "Ghidra headless 独立跑一遍，作为交叉验证")],
    ),
    dict(
        q=["动态看这个方法被谁调用，给 hook 方案。",
           "要 hook 一个 Java 方法看参数，怎么起？",
           "Frida 从 attach 到拿到调用栈的完整步骤。"],
        steps=[("kitty_frida", "attach", "先 attach 包名，确认进程可注入"),
               ("kitty_frida", "trace", "挂目标方法，打印入参/返回值"),
               ("kitty_rea_method", "inspect_android_method", "静态侧对照：反编译同一方法看真实签名")],
    ),
    dict(
        q=["多级指针加上偏移，反过来推谁指向它。",
           "P_BACK 扫出来的命中太多，怎么收敛？",
           "从目标地址反推到模块基址的完整做法。"],
        steps=[("kitty_pchain", "pchain", "显式窗口反查 + R 验证 + P_WALK 回验，带候选上限"),
               ("kitty_ce", "op", 'P_WALK|<addr>|<off> 逐级回验（off 用十进制）'),
               ("kitty_sym", "resolve", "把最终模块偏移落到符号上，便于跨版本迁移")],
    ),
    dict(
        q=["确认目标跑起来后通道是不是三层全绿。",
           "驱动起了但 CE 连不上，怎么逐层排？",
           "从零起一套可用通道，给我顺序。"],
        steps=[("kitty_init", "status", "先只读看三层现状，不急着 init"),
               ("kitty_init", "init", "需要重建时一键双绿：辅助驱→宿主→主驱→验真→DBVM→CE 心跳"),
               ("kitty_drv", "status", "通道起不来再看驱动与宿主存活，必要时 recover / host")],
    ),
    dict(
        q=["改一个只读页里的值，常规写失败，怎么绕？",
           "写保护怎么绕过，给可执行的链路。",
           "PTE 直写的完整步骤和回读验证。"],
        steps=[("kitty_prot", "query", "先看保护位与页属性，确认是 NOACCESS / GUARD 还是普通只读"),
               ("kitty_wpb", "write", "PTE 直改绕写保护，addr/vt/hex 给全，restore 默认 true"),
               ("kitty_ce", "op", 'R|同址 回读，与期望值比对才算闭环')],
    ),
    dict(
        q=["把这一轮的探索过程记下来，并给出结论记录。",
           "过程记录和 finding 分别该往哪写？",
           "做完一轮分析，产物怎么归档？"],
        steps=[("kitty_trail", "append", "过程性记录写探索日志道（每步一行：step / 事实 / 回包摘要）"),
               ("kitty_trail", "get", "按目标过滤回读，确认写入且顺序正确"),
               ("kitty_settings", "trail-get", "会话侧读同一份 trail，确认对话与工作台看到的一致")],
    ),
]

# ── ② 纪律样本（改写：允许链式，禁止罗列备选）────────────────────
DISCIPLINE = [
    ("这个任务你打算调几个工具？先给我最该做的那一步。",
     "先给第一个调用，后面的看回包再定。\n\n"
     "为什么：多步任务的正确形态是「调用 → 看回包 → 决定下一步」，不是一次性铺开全部计划 ——"
     "回包会改变判断依据，预先铺开的第二步往往就错了。\n"
     "但注意：**任务本身需要串联多个工具时（比如先抓包再解字段），按执行顺序把链路给出来是允许的**，"
     "前提是每一步都写清判据。禁止的是「同一件事罗列几个备选工具让我挑」，不是「多步」。\n"
     "判据：每条调用都要能对应一个具体判据；没有判据的调用就是猜测。"),
    ("别罗列备选，直接给我该用的那一个工具和参数。",
     "给一个，不给备选。\n\n"
     "区分清楚：\n"
     "- 「同一件事的多个候选」→ 只给最该用的那一个（罗列备选是浪费，也说明没判断）\n"
     "- 「一件事需要多步」→ 按顺序给链路，每步一个工具 + 一个判据\n\n"
     "判据：如果你写下的第二个工具是做同一件事的替代方案，删掉它；"
     "如果它是基于第一个回包才能做的下一步，保留并写清依赖关系。"),
    ("一次只发一个调用，先做最该做的那步。",
     "先发一个，拿到回包再决定。\n\n"
     "例外：当任务本身是多步流水线（抓包→解码→还原字段），可以把链路一次给全，"
     "但每一步必须写明「这一步的判据是什么、拿到什么结果才继续」。\n"
     "判据：单步任务只给一个；多步任务按序给，但每步都要有判据，不允许无判据的连续调用。"),
    ("把你准备用的工具收敛成一条，多余的不要写。",
     "收敛成一件事一个工具。\n\n"
     "检查方法：把你的每个调用读一遍，问「这个是在做同一件事的另一种做法吗」——"
     "是就删；「这个依赖上一个的回包吗」——是就保留并写出依赖。\n"
     "判据：留下的每个调用都能独立回答「为什么是它、什么条件下继续」。"),
    ("先把最关键的那个调用给我，其他以后再说。",
     "第一个调用如下。\n\n"
     "顺序原则：能一步定位的不要拆两步；必须串联的按依赖顺序给，前一步的回包是后一步的输入。\n"
     "判据：给出的调用要能立刻执行；需要前置条件的，先给前置条件那一步。"),
]

# ── ③ 正例问法（任务式，不再拿 description 当问句）──────────────
TASK_TMPL = [
    "用工具完成：{d}。给出调用。",
    "我要做这件事：{d}。选工具、给参数。",
    "任务目标：{d}。直接给能执行的调用。",
]

CRIT = ("判据：回包首行看 OK/ERR；ERR 按错误码修参数，不原地重试。"
        "工具名与 action 必须真实存在，不许发明。")


def asst_single(t):
    a = acts(t)[0] if acts(t) else "status"
    return (f"{t} action={a}\n\n"
            f"选它的理由：{desc(t)}\n"
            f"参数要点：目标先定死（path / pid / addr 按任务给全）；只读类先 status 探一次。\n"
            f"{CRIT}")


def asst_chain(c):
    lines = []
    for i, (t, a, why) in enumerate(c["steps"], 1):
        chk(t, a)
        call = f"{t} action={a}" if a else t
        lines.append(f"{i}. {call}\n   {why}")
    return ("\n".join(lines) +
            "\n\n顺序说明：上一步的回包是下一步的输入，不要跳步；每步都有判据，不符合就停在那一步排查。\n"
            "这是一条真实的多步链路，不是罗列备选 —— 每一步的依赖关系已写明。")


def main():
    rows = []

    # ① 多步链（每条问法都出，提权 4 份）
    for c in CHAINS:
        for q in c["q"]:
            rows.append({"messages": [
                {"role": "user", "content": q},
                {"role": "assistant", "content": asst_chain(c)}]})
    n1 = len(rows)

    # ② 纪律改写（每条问法出）
    for q, a in DISCIPLINE:
        for suffix in ("", " 举例：多步任务。"):
            rows.append({"messages": [
                {"role": "user", "content": q + suffix},
                {"role": "assistant", "content": a}]})
    n2 = len(rows) - n1

    # ③ 任务式正例（58 工具全覆蓋）
    for t in sorted(CAT):
        for tmpl in TASK_TMPL:
            rows.append({"messages": [
                {"role": "user", "content": tmpl.format(d=desc(t))},
                {"role": "assistant", "content": asst_single(t)}]})
    n3 = len(rows) - n1 - n2

    # 提权：链样本权重最高（L3 是短板）
    out = rows + rows[:n1] * 3

    seen, ded = set(), []
    for r in out:
        k = r["messages"][0]["content"] + "\x00" + r["messages"][1]["content"]
        if k in seen:
            continue
        seen.add(k)
        ded.append(r)
    ded = ded + rows[:n1] * 3     # 去重后再补链样本权重

    io.open(OUT, "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in ded) + "\n")
    print(f"[OUT] {OUT}")
    print(f"  多步链 {n1} · 纪律改写 {n2} · 任务式正例 {n3} → 去重+提权 {len(ded)}")
    print("\n=== 多步链样本示例 ===")
    c = CHAINS[0]
    print("U:", c["q"][0])
    print("A:", asst_chain(c)[:600])


if __name__ == "__main__":
    main()

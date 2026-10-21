# -*- coding: utf-8 -*-
"""expand_gold.py —— gold 层：多轮任务轨迹 + 反例纠正 + DPO 配对

被 run_expand.py 调用。所有回包形态取自 contracts/ops.json 的 reply/sig 语义；
内存数值用占位（不伪造具体地址结论），结论写明判据。
"""
import json


def sft(user, assistant, cat, tier, **meta):
    return {"messages": [{"role": "user", "content": user},
                         {"role": "assistant", "content": assistant}],
            "meta": {"cat": cat, "tier": tier, **meta}}


SCEN = [
    dict(id="attach-modules",
         ask=["用 kitty_ce 附加到记事本进程，读出模块列表。", "打开 KittyCE，把 notepad 的模块表拿给我。"],
         steps=[("kitty_ce", {"op": "PING"}, "OK|Kitty-bridge v0.2.9"),
                ("kitty_ce", {"op": "OPEN|notepad.exe"}, "OK|7428"),
                ("kitty_ce", {"op": "MODENUM"}, "OK|3\nnotepad.exe|0x7FF6DADB0000|1|0x2A000\nKERNEL32.DLL|0x7FFB10000000|1|0x1C0000\nntdll.dll|0x7FFB20000000|1|0x200000")],
         final="已附加 pid=7428，模块表 3 项（notepad.exe / KERNEL32.DLL / ntdll.dll），带基址与 size。\n判据：MODENUM 首行是条数，其后每行 `name|base|is64|size`；size 可能为 0，为 0 时用镜像头兜底。\n\n当前:notepad.exe / 结果:模块表已读出 / 下一步:读内存用 R|<addr>|<type>"),
    dict(id="scan-then-read",
         ask=["在 kitty-target.exe 里找 dword 12345，命中后读第一个地址确认。", "扫 12345 这个数，找到就读一个给我看。"],
         steps=[("kitty_ce", {"op": "OPEN|kitty-target.exe"}, "OK|5140"),
                ("kitty_ce", {"op": "MODENUM"}, "OK|1\nkitty-target.exe|0x7FF700000000|1|0x800000"),
                ("kitty_ce", {"op": "S_NEW|dword|12345|0x7FF700000000|0x7FF700800000"}, "OK|scan|range|3w|dword=12345"),
                ("kitty_ce", {"op": "S_GET|0|10"}, "OK|3\n0x7FF700123400\n0x7FF700567800\n0x7FF7009ABC00"),
                ("kitty_ce", {"op": "R|0x7FF700123400|dword"}, "OK|12345")],
         final="命中 3 处，首个 0x7FF700123400 读回 12345（R 的数值回包是十进制）。\n两个坑已避：S_NEW 必须显式区间；S_GET 的 start 是 0 基偏移。\n\n当前:kitty-target.exe / 结果:3 处命中，验证 1 处 / 下一步:收窄用 S_NEXT"),
    dict(id="need-range-recover",
         ask=["扫一下 dword 999，我不知道区间。", "找 dword 999，随便扫。"],
         steps=[("kitty_ce", {"op": "S_NEW|dword|999|0x10000000|0x20000000"}, "ERR|need-range")],
         final="ERR|need-range 说明区间不合法（全空间或跨窗超限）。正确做法不是换值重试，而是先取模块窗口：MODENUM 拿 base/size，再用该窗口重扫。\n窗口上限：单窗 ≤16MB、总 ≤64MB、≤4 段。\n\n当前:kitty-target.exe / 结果:阻塞于区间 / 下一步:MODENUM → S_NEW|dword|999|<base>|<base+size>"),
    dict(id="pointer-chain",
         ask=["血量在 0x7FF75FCD2000，帮我找指针链。", "这个地址的指针链怎么反查？"],
         steps=[("kitty_ce", {"op": "P_BACK|0x7FF75FCD2000|0x7FF700000000|0x7FF700800000"}, "OK|2"),
                ("kitty_ce", {"op": "P_BACK_RES|10"}, "OK|2\n0x7FF700123400\n0x7FF70055C000"),
                ("kitty_ce", {"op": "P_WALK|0x7FF700123400|0x1B0"}, "OK|0x7FF75FCD2000")],
         final="链路：0x7FF700123400 + 0x1B0 → 0x7FF75FCD2000（P_WALK 回验命中）。\n判据：P_BACK 必须显式窗口、命中上限 200；回验不一致的候选直接丢。多跳用 kitty_pchain depth=2。\n\n当前:kitty-target.exe / 结果:1 跳链已回验 / 下一步:多跳反查到模块基址"),
    dict(id="dualfield-gate",
         ask=["附加到游戏，找血量。", "帮我看下这进程的血量。"],
         steps=[],
         final="开跑前先把双字段钉死，否则扫出来也判断不了对错：\n1) 目标进程（进程名或 PID）；\n2) 会话目标（例如「定位血量并给出指针链」）。\n另外血量当前值知道吗——知道走精确扫描，不知道走 S_SNAP 快照法。\n给我这两项，我按 OPEN → MODENUM → 扫描 → 回验 四步走完。"),
    dict(id="dualview",
         ask=["确认 0x7FF75FCD1000 有没有被拦。", "这个地址读出来可信吗，做个三视图。"],
         steps=[("kitty_dualview", {"addr": "0x7FF75FCD1000", "vt": "dword", "samples": 3, "note": "gate"},
                  "R=<v> KM_R=<v> KM_PR=<v> view=aligned samples=3 gate=green")],
         final="三视图一致（R / KM_R / KM_PR 同值，3 轮采样），gate=green → 采样地址无用户态拦截。\n边界：green 只代表采样地址当前无拦截，不等于全进程无拦截；换关键字段地址再采。分叉时取 bytes:16 对照并落证据包。\n\n当前:kitty-target.exe / 结果:gate=green / 下一步:关键地址补采"),
    dict(id="wpb",
         ask=["这块内存写不进去，能做写保护绕过吗？", "W 写入失败，怎么绕过保护？"],
         steps=[("kitty_prot", {"action": "probe", "addr": "0x7FF75FCD3000"},
                  "probe: read=ok write=denied page=0x7FF75FCD3000")],
         final="read=ok / write=denied，且地址在用户态段 → 可走 kitty_wpb（PTE 直改，不需要目标句柄、不调保护 API）。\n前提与代价：仅用户态地址；需显式 accept_protection_bypass=true；默认写后还原 PTE。\n执行前确认两件事：写什么值、写后是否必须还原。\n\n当前:kitty-target.exe / 结果:已判定需 wpb / 下一步:给值与还原要求"),
    dict(id="host-selfheal",
         ask=["PING 不通了，通道挂了。", "kitty 没反应，是不是宿主死了？"],
         steps=[("kitty_status", {"probe": True}, "bridge: cmd/rep ok=false pending=3 hostAlive=false"),
                ("kitty_drv", {"action": "host", "hostStart": True},
                 "host: restarted pid=9312; PING ok; SYNC_ARCHIVE ok pending=0")],
         final="判定为宿主进程不在（hostAlive=false），桥有 3 条 pending 残留 → host 单实例重拉成功，PING 通、sync 残留归零。\n顺序要点：先 status 判定宿主死还是桥楔住，再 host 重拉，最后 SYNC_ARCHIVE 归一。\n\n当前:KittyCE / 结果:通道恢复 / 下一步:回到原任务 OPEN 目标"),
    dict(id="closeout",
         ask=["任务做完收尾。", "收口，别折腾了。"],
         steps=[("kitty_settings", {"action": "task-dispatch",
                                    "taskTransition": "{\"type\":\"finish\",\"evidence\":[\"MODENUM ok\",\"R verified\"]}"},
                 "ok generation=12 terminalState=finished"),
                ("kitty_settings", {"action": "task-close"}, "ok closed generation=12")],
         final="已收口：finish 带证据 → task-close，两次调用结束（generation=12）。\n不试 stage-start 组合、不改 type 拼写、不重复 complete。\n\n当前:kitty-target.exe / 结果:任务已关闭 / 下一步:新目标用 task-new"),
    dict(id="transition-fix",
         ask=["我把 transition 写成 {\"state\":\"finish\"} 报错了。", "task-dispatch 报 TASK-TRANSITION-UNKNOWN 怎么办？"],
         steps=[("kitty_settings", {"action": "task-dispatch", "taskTransition": "{\"state\":\"finish\"}"},
                 "ERR|TASK-TRANSITION-UNKNOWN: transition.type=undefined 不在合法集合。合法值：enter-task|enter-standby|stage-start|stage-complete|stage-fail|retry-stage|block|answer|complete|finish|abandon|set-consent")],
         final="键名错了：只认 type，不认 state；finish 还要带非空 evidence。按报错列出的合法值改一次就够。\n正确：{\"type\":\"finish\",\"evidence\":[\"<证据>\"]} → 再 task-close。\n\n当前:kitty-target.exe / 结果:1 次报错已定位 / 下一步:重发一次后收口"),
    dict(id="dump",
         ask=["把模块 dump 下来并重建。", "dump 一份镜像，能对比原文件吗？"],
         steps=[("kitty_dump", {"module": "kitty-target.exe", "unmap": True, "reference": "<原始exe路径>",
                                "path": "logs/dump-<ts>.bin"}, "dump ok size=0x800000; unmap ok; match=<一致率>")],
         final="转储走分块落盘，unmap 按节表重建磁盘格式并回填 IAT，输出与参考文件的一致率。\n判据：一致率高说明重建干净；加壳或自改节表会明显下降。\n\n当前:kitty-target.exe / 结果:镜像已重建 / 下一步:给 reference 出逐字节一致率"),
    dict(id="patch-expect",
         ask=["把这条 jz 改成 jmp。", "这个跳转改成无条件跳。"],
         steps=[("kitty_ce", {"op": "R|0x7FF6DADB2345|bytes:6"}, "OK|74 08 48 8B 45 F8"),
                ("kitty_asm", {"action": "jump", "kind": "jmp", "from": "0x7FF6DADB2345",
                               "target": "0x7FF6DADB234F"}, "EB 08")],
         final="原字节 74 08（jz rel8）→ EB 08（jmp rel8），长度相同、后续指令不错位。\n落盘：kitty_patch patch 带 expect=74 08，自动备份 .bak 并重算校验和；运行时改用 W|addr|bytes:2|EB 08 后回读。\n\n当前:notepad.exe / 结果:跳转字节已生成（未写） / 下一步:确认后落补丁"),
    dict(id="sym-resolve",
         ask=["kernelbase 的 CreateFileW 地址是多少？", "解析一下 CreateFileW 在进程里的地址。"],
         steps=[("kitty_sym", {"action": "resolve", "source": "mem", "module": "KERNELBASE.dll",
                               "name": "CreateFileW"}, "OK|0x7FFB10123450")],
         final="KERNELBASE.dll!CreateFileW → 0x7FFB10123450（内存模块，按导出表解析）。\n用途：给 CHECK_FN/断点定位用，避免手填符号名。\n\n当前:kitty-target.exe / 结果:符号地址已解析 / 下一步:下断走 kitty_x64dbg seed"),
    dict(id="x64dbg-seed",
         ask=["用 x64dbg 在 CreateFileW 下断并抓一次调用。", "真调试：在 CreateFileW 断下来。"],
         steps=[("kitty_x64dbg", {"action": "selftest"}, "selftest ok: dbgExe locked, engine ready"),
                ("kitty_x64dbg", {"action": "seed", "addr": "KERNELBASE.CreateFileW",
                                  "seedCmd": "savedata <out>, <exe>, 64",
                                  "logfile": "logs/x64dbg-<ts>.log"}, "seeded; log=logs/x64dbg-<ts>.log")],
         final="走 C 通道真调试（A 通道 DBG_ATTACH 在本 build 会杀宿主，非必要不用）。\n已 selftest → 在 CreateFileW 下断并保存一次调用现场。\n判据：日志有命中行 + 产物文件生成。\n\n当前:notepad.exe / 结果:断点命中并落盘 / 下一步:readlog 看调用栈"),
    dict(id="cost-converge",
         ask=["先试 4 字节 500，再试 2 字节，再试 1 字节。", "按这个思路反复试，直到扫到为止。"],
         steps=[("kitty_ce", {"op": "OPEN|kitty-target.exe"}, "OK|5140"),
                ("kitty_ce", {"op": "MODENUM"}, "OK|1\nkitty-target.exe|0x7FF700000000|1|0x800000")],
         final="先停：换宽度盲试不是收敛路径。已确认 pid=5140、窗口 0x7FF700000000/0x800000，但缺两个判据——\n1) 血量当前值（猜的还是读出来的）；2) 类型是 dword 还是 float（有 0.5 系数会变）。\n同一目标第 3 次尝试就停下汇报，这是纪律不是放弃。给判据我一次扫准。"),
    dict(id="protocol-compress",
         ask=["清单给你了，直接干活：先扫 9999，再 dump 模块，再写回。", "按上面的 OP 表把这三件事做完。"],
         steps=[("kitty_ce", {"op": "MODENUM"}, "OK|1\nkitty-target.exe|0x7FF700000000|1|0x800000"),
                ("kitty_ce", {"op": "S_NEW|dword|9999|0x7FF700000000|0x7FF700800000"},
                 "OK|scan|range|2w|dword=9999")],
         final="三步只取必要 OP，不复述清单：① S_NEW（窗口取自 MODENUM）② kitty_dump module=… ③ W 前先 R 现值、写后回读。\n第 1 步已完成，命中 2 处。第 2/3 步先定边界：dump 落盘路径、写回的回滚点。\n\n当前:kitty-target.exe / 结果:扫描命中 2 处 / 下一步:给 dump 路径后继续"),
    dict(id="kernel-read",
         ask=["内核态读 0x7FF75FCD1000，和用户态对一下。", "用 KM_R 读这个地址做对照。"],
         steps=[("kitty_ce", {"op": "R|0x7FF75FCD1000|dword"}, "OK|1234567"),
                ("kitty_km", {"action": "read", "addr": "0x7FF75FCD1000", "vt": "dword"},
                 "KM_R|OK|1234567")],
         final="两视图一致：R=1234567，KM_R=1234567。\n补第三视图：KM_PA 取物理地址 → KM_PR 读物理（KM_PR 回 table，桥已转换）。三视图全一致才算 green。\n注意：KM_PW（物理写）默认拒绝，实测会卡死 Lua 引擎，恢复=宿主重启，不要试。\n\n当前:kitty-target.exe / 结果:2/3 视图一致 / 下一步:KM_PA → KM_PR"),
    dict(id="apk-route",
         ask=["这是个 APK，先看壳再反编译。", "拿到一个安卓包，怎么走？"],
         steps=[("kitty_apkscan", {"action": "scan", "target": "<app>.apk"}, "APKiD: packer=<指纹>; compiler=<指纹>"),
                ("kitty_apktool", {"action": "decode", "target": "<app>.apk",
                                   "out": "logs/apktool-<name>"}, "decode ok"),
                ("kitty_jadx", {"action": "decompile", "target": "<app>.apk",
                                "out": "logs/jadx-<name>"}, "decompile ok")],
         final="顺序：APKiD 指纹（判壳/编译器）→ apktool 出资源与 Manifest → jadx 出 Java。\n判据：先看有没有壳；有壳先脱（BlackDex/FART 产物用 kitty_unpack collect+parse 收口）再反编译。\n\n当前:<app>.apk / 结果:APK 已解包反编译 / 下一步:定位签名与网络入口"),
    dict(id="engine-route",
         ask=["这是个 Unity 游戏，走哪条？", "Unity IL2CPP 的包怎么开？"],
         steps=[("kitty_engines", {"path": "<游戏目录>"},
                 "engine=unity mode=il2cpp meta=GameAssembly.dll"),
                ("kitty_cpp2il", {"action": "triage", "gameDir": "<游戏目录>"},
                 "il2cpp detected: GameAssembly.dll + global-metadata.dat"),
                ("kitty_cpp2il", {"action": "dump", "gameDir": "<游戏目录>",
                                  "out": "logs/il2cpp-<name>"}, "dump ok")],
         final="路由结论：Unity + IL2CPP → Cpp2IL dump（或 Il2CppDumper 走 so/meta）。\n判据：有 GameAssembly.dll + global-metadata.dat 即 IL2CPP；只有 Managed/*.dll 是 Mono（改走 dnSpy）。\n\n当前:<游戏目录> / 结果:IL2CPP 已 dump / 下一步:定位目标类与方法偏移"),
]


def gen_scen():
    rows = []
    for sc in SCEN:
        for ask in sc["ask"]:
            msgs = [{"role": "user", "content": ask}]
            for name, args, res in sc["steps"]:
                payload = json.dumps({"name": name, "arguments": args}, ensure_ascii=False)
                msgs.append({"role": "assistant", "content": "<tool_call>\n" + payload + "\n</tool_call>"})
                msgs.append({"role": "tool", "content": res})
            msgs.append({"role": "assistant", "content": sc["final"]})
            rows.append({"messages": msgs,
                         "meta": {"cat": "trajectory", "tier": "gold",
                                  "scenario": sc["id"], "steps": len(sc["steps"])}})
    return rows


GUARDS = [
    ("S_NEW 没给区间报错了，我把区间写成 0x0 到 0xFFFFFFFF 重试。",
     "不行。全空间必超窗（单窗 ≤16MB、总 ≤64MB），只会再吃一次 need-range。正确：MODENUM 取模块窗口，用 base/size 当区间重发一次。"),
    ("kitty_ce 调用失败，我去读 kitty-toolbox 的 tool-manifest.ts 看协议。",
     "不要读源码。工具契约用 kitty_ops 查（filter=<前缀>），通道健康用 kitty_status。读源码是 41 步空转的起点。"),
    ("工具列表里没有 kitty_km，我自己写个 mjs 脚本调桥。",
     "不要自造桥接。正确动作：上报「kitty_km 不在本轮可用集」，并给操作者两条确认路径（启用工具 / 授权走 CLI）。"),
    ("task-dispatch 报 UNKNOWN，我把 12 个 type 挨个试一遍。",
     "报错已列出合法值，且说明键名是 type。按正确形态发一次即可：{\"type\":\"finish\",\"evidence\":[\"<证据>\"]}。"),
    ("扫描没结果，我把 dword 换成 float 再换成 2 字节继续试。",
     "先确认判据再换类型：值是读出来的还是猜的、有无系数换算。同一目标第 3 次仍无判据就停下汇报。"),
    ("W 写失败，我先调 KM_PW 物理写。",
     "KM_PW 默认拒绝且实测卡死 Lua 引擎（恢复=宿主重启）。写保护先 kitty_prot probe 判定，用户态走 kitty_wpb。"),
    ("DBG_ATTACH 打不开，我加 unsafe 再试。",
     "本 build 走 unsafe 会随机 fail-fast 杀宿主（F-13）。真调试改走 C 通道 kitty_x64dbg。"),
    ("任务做完了，我再确认几次任务状态，多跑几个 transition。",
     "收口只有两步：finish（带 evidence）→ task-close。反复确认状态是空转，不算严谨。"),
    ("P_BACK 没结果，我把窗口开到整个用户空间。",
     "P_BACK 有 200 命中上限且必须显式窗口；开太大更难收敛。先用模块窗口，逐步扩。"),
    ("模型没给血量当前值，我直接从 100 开始扫。",
     "先问三个判据：初始值/最大值是否已知、类型、有无换算系数。没有判据的扫描是盲试。"),
]


def gen_guard():
    rows = []
    for wrong, right in GUARDS:
        rows.append(sft(f"我打算这样做：{wrong} 对吗？", f"不对。\n{right}", "guard", "guard"))
        rows.append(sft(f"为什么不能这么做：{wrong}", right, "guard", "guard"))
        rows.append(sft(f"同事说可以这样：{wrong} 你觉得呢？", f"不建议。{right}", "guard", "guard"))
    return rows


DPO_MAP = [
    (("收尾", "收口", "任务做完"), "finish 一次带证据，再 task-close；不试 stage 组合、不改 type 拼写。"),
    (("附加", "模块", "notepad"), "PING → OPEN|notepad.exe → MODENUM，三步给表；PING 不通先 kitty_status 判定再 host 重拉。"),
    (("扫", "找"), "先取模块窗口，再 S_NEW|vt|val|start|stop；need-range 时只补区间不换值。"),
]


def gen_dpo(seed_pairs, real_neg):
    pairs = list(seed_pairs)
    for row in real_neg:
        msgs = row.get("messages") or []
        if not msgs or msgs[0].get("role") != "user":
            continue
        prompt_txt = msgs[0]["content"]
        rejected = next((m["content"] for m in msgs[1:]
                         if m.get("role") == "assistant" and m.get("content")), "")
        if not rejected:
            continue
        chosen = next((ans for keys, ans in DPO_MAP if any(k in prompt_txt for k in keys)), None)
        if not chosen:
            continue
        pairs.append({"prompt": prompt_txt, "chosen": chosen, "rejected": rejected[:1200],
                      "meta": {"cat": "real-negative", "tier": "gold",
                               "src": (row.get("meta") or {}).get("src", "?"),
                               "steps": (row.get("meta") or {}).get("steps")}})
    # 反例纠正 → 偏好对（chosen=正确做法，rejected=错误打算）
    for wrong, right in GUARDS:
        pairs.append({"prompt": f"我打算这样做：{wrong} 对吗？",
                      "chosen": f"不对。\n{right}",
                      "rejected": f"可以，就这么做：{wrong}",
                      "meta": {"cat": "guard", "tier": "gold"}})
    return pairs


# ---------------------------------------------------------------- 9 gold 扩产：问法变体 / 逐步动作 / 错误注入
PREFIX = ["", "急单，", "同事转述的需求：", "开工前确认一下，", "按老规矩来，"]
SUFFIX = ["", "尽量少走弯路。", "别空转。", "给判据，不要只给结论。", "做完顺手收口。"]


def gen_scen_variants():
    """同一场景 5 种问法（前缀/后缀组合），防过拟合单一 prompt 形态。"""
    rows = []
    for sc in SCEN:
        base = sc["ask"][0]
        for p, s in zip(PREFIX, SUFFIX):
            ask = f"{p}{base}{s}"
            msgs = [{"role": "user", "content": ask}]
            for name, args, res in sc["steps"]:
                payload = json.dumps({"name": name, "arguments": args}, ensure_ascii=False)
                msgs.append({"role": "assistant", "content": "<tool_call>\n" + payload + "\n</tool_call>"})
                msgs.append({"role": "tool", "content": res})
            msgs.append({"role": "assistant", "content": sc["final"]})
            rows.append({"messages": msgs,
                         "meta": {"cat": "trajectory", "tier": "gold",
                                  "scenario": sc["id"], "steps": len(sc["steps"]), "variant": f"{p}|{s}"}})
    return rows


def gen_next_action():
    """把轨迹切成「历史 → 下一步调用」，一步一步学决策（治长循环）。"""
    rows = []
    for sc in SCEN:
        if not sc["steps"]:
            continue
        ask = sc["ask"][0]
        hist = [{"role": "user", "content": ask}]
        for idx, (name, args, res) in enumerate(sc["steps"]):
            payload = json.dumps({"name": name, "arguments": args}, ensure_ascii=False)
            rows.append({"messages": hist + [{"role": "assistant", "content": "<tool_call>\n" + payload + "\n</tool_call>"}],
                         "meta": {"cat": "next-action", "tier": "gold", "scenario": sc["id"], "step": idx + 1}})
            hist = hist + [{"role": "assistant", "content": "<tool_call>\n" + payload + "\n</tool_call>"},
                           {"role": "tool", "content": res}]
    return rows


ERROR_INJECT = [
    dict(id="err-no-target-then-open",
         ask="读 0x7FF700123400 的 dword。",
         steps=[("kitty_ce", {"op": "R|0x7FF700123400|dword"}, "ERR|no-target"),
                ("kitty_ce", {"op": "OPEN|kitty-target.exe"}, "OK|5140"),
                ("kitty_ce", {"op": "R|0x7FF700123400|dword"}, "OK|12345")],
         final="ERR|no-target 是没附加，不是地址错。一次 OPEN 后重读即成功（0 次换地址）。\n\n当前:kitty-target.exe / 结果:读到 12345 / 下一步:需要时继续扫描"),
    dict(id="err-pback-empty-then-narrow",
         ask="在 0x7FF700000000–0x7FF700800000 里反查 0x7FF75FCD2000 的引用。",
         steps=[("kitty_ce", {"op": "P_BACK|0x7FF75FCD2000|0x7FF700000000|0x7FF700800000"}, "OK|0"),
                ("kitty_ce", {"op": "P_BACK|0x7FF75FCD2000|0x7FF700000000|0x7FF700100000"}, "OK|1"),
                ("kitty_ce", {"op": "P_WALK|0x7FF700050000|0x1B0"}, "OK|0x7FF75FCD2000")],
         final="第一轮大窗 0 命中：不是没有引用，是窗口/对齐不合适。收窄到 0x100000 后命中 1 条，P_WALK 回验通过。\n纪律：P_BACK 无结果先收窄或分段扫，不要直接放弃，也不要一次开全空间。\n\n当前:kitty-target.exe / 结果:1 条链已回验 / 下一步:多跳接 pchain"),
    dict(id="err-stale-bridge",
         ask="通道好像卡住了，PING 回得慢。",
         steps=[("kitty_ce", {"op": "PING"}, "ERR|timeout"),
                ("kitty_status", {"probe": True}, "bridge: ok=false pending=12 hostAlive=true wedged=true"),
                ("kitty_drv", {"action": "host", "hostStart": False, "reset_breaker": True}, "host: probereset; PING ok"),
                ("kitty_ce", {"op": "SYNC_ARCHIVE"}, "OK|archived|pending=0")],
         final="判据链：PING 超时 → status 看 pending=12 且宿主活着 → 是桥楔住不是宿主死 → 复位熔断 + 归档残留后 PING 恢复。\n若宿主也死（hostAlive=false）才需要 hostStart=true 重拉；两种情形处置不同。\n\n当前:KittyCE / 结果:桥恢复、pending 归零 / 下一步:回原任务"),
]


def gen_error_inject():
    rows = []
    for sc in ERROR_INJECT:
        for ask in (sc["ask"], "按实际情况处理：" + sc["ask"]):
            msgs = [{"role": "user", "content": ask}]
            for name, args, res in sc["steps"]:
                payload = json.dumps({"name": name, "arguments": args}, ensure_ascii=False)
                msgs.append({"role": "assistant", "content": "<tool_call>\n" + payload + "\n</tool_call>"})
                msgs.append({"role": "tool", "content": res})
            msgs.append({"role": "assistant", "content": sc["final"]})
            rows.append({"messages": msgs,
                         "meta": {"cat": "error-trajectory", "tier": "gold",
                                  "scenario": sc["id"], "steps": len(sc["steps"])}})
    return rows

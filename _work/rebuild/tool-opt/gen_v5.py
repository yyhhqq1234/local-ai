# -*- coding: utf-8 -*-
"""v5 三件套生成器（固定 seed，可重跑）
A tool-pchain.jsonl / B tool-ida.jsonl / C tool-direct-answer.jsonl
生成后立即自检，统计落 v5-stats.json
"""
import json, os, re, random, sys

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
SEED = 20261121

OUT_A = os.path.join(ROOT, r"train\lines\9b-oxcoder\data\kitty-reverse\opt\tool-pchain.jsonl")
OUT_B = os.path.join(ROOT, r"train\lines\9b-oxcoder\data\kitty-reverse\opt\tool-ida.jsonl")
OUT_C = os.path.join(ROOT, r"train\lines\9b-oxcoder\data\dsh-adapt\tool-direct-answer.jsonl")
STATS = os.path.join(ROOT, r"_work\rebuild\tool-opt\v5-stats.json")

SYS_KITTY = ("你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。"
             "工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。")
SYS_DSH = ("你是石井，本地工作区执行层（SHIYI-WORKSPACE）。直接回答或直接做事："
           "首行就是产物（正文/代码/结论）；不写阶段小结、不写计划清单、不用固定格式收口。")

BANNED = ["[STAGE]", "目标：", "交付物：", "判据：", "当前：", "结果：", "下一步：", "计划：", "步骤1"]


def rec(q, a, sysmsg=SYS_KITTY):
    return {"messages": [{"role": "system", "content": sysmsg},
                         {"role": "user", "content": q},
                         {"role": "assistant", "content": a}]}


def tc(name, args):
    return '<tool_call>' + json.dumps({"name": name, "arguments": args},
                                      ensure_ascii=False, separators=(",", ":")) + '</tool_call>'


# ---------------------------------------------------------------- A 指针链
def build_pool(n):
    out = ["0x7FF6A0000000", "0x7FF75FCD1000", "0x140001000"]
    i = 1
    while len(out) < n * 3:
        out.append("0x7FF6A0%06X" % ((0x10000 + i * 0x137) & 0xFFFFFF))
        out.append("0x7FF75FCD%04X" % ((0x1000 + i * 0x3C) & 0xFFFF))
        out.append("0x140%06X" % ((0x1000 + i * 0x28) & 0xFFFFFF))
        i += 1
    seen, res = set(), []
    for a in out:
        if a.lower() in seen:
            continue
        seen.add(a.lower())
        res.append(a)
    assert len(res) >= n
    return res[:n]


PC_GROUPS = [
    ("反查指针链", [
        "反查 {t} 的指针链，{d} 跳",
        "帮我反查 {t} 的指针链（{d} 跳）",
        "给 {t} 做指针链反查，{d} 跳",
    ]),
    ("多跳指针", [
        "从 {t} 往上走 {d} 跳指针",
        "顺着指针从 {t} 追 {d} 跳",
        "{t} 多跳指针追 {d} 层",
    ]),
    ("谁指向这个地址", [
        "谁指向 {t}",
        "{t} 是谁指过来的",
        "查一下谁指向 {t}，{d} 跳范围内",
    ]),
    ("从哪读到这个值", [
        "{t} 这个值是从哪读到的，{d} 跳",
        "从哪条链读到 {t} 的，追 {d} 跳",
        "{t} 的读取来源是谁，{d} 跳",
    ]),
    ("追父链", [
        "追一下 {t} 的父链，{d} 跳",
        "把 {t} 的父链追 {d} 层",
        "{t} 父链往上 {d} 跳",
    ]),
    ("找基址", [
        "找 {t} 的基址，{d} 跳",
        "{t} 的基址是哪个，按 {d} 跳找",
        "从 {t} 反推基址，{d} 跳",
    ]),
    ("几跳能到", [
        "{t} 几跳能到基址",
        "{t} 到基址要几跳，按 {d} 跳试",
        "算一下 {t} 到基址的跳数，{d} 跳内",
    ]),
]

PC_REASON = {
    "反查指针链": "要的是 {d} 跳溯源，kitty_pchain 的 depth 一次给全，kitty_ce 的 R 只读一层值",
    "多跳指针": "多跳是 pchain 的 depth 语义，kitty_ce 没有跳数概念，只能一层层手读",
    "谁指向这个地址": "找引用方是反查，pchain 走 P_BACK 扫窗口；kitty_ce 的 R 只回地址内容，不回引用者",
    "从哪读到这个值": "问的是读取来源（谁指过来），不是值本身；读值才是 kitty_ce，这里要 pchain",
    "追父链": "父链 = 由子到父逐跳，pchain 用 depth 一次展开，kitty_ce 只能读当前层",
    "找基址": "基址要从目标地址反推，pchain 沿链往上收敛，kitty_ce 不分模块基址与链",
    "几跳能到": "问跳数就是 pchain 的 depth 语义，kitty_ce 不统计跳数",
}


def gen_a():
    per = 17
    pool = build_pool(per * 7 + 60)
    recs, k = [], 0
    meta = {}
    for gname, tmps in PC_GROUPS:
        for i in range(per):
            t = pool[k]; k += 1
            d = 2 if i % 2 == 0 else 3
            q = tmps[i % len(tmps)].format(t=t, d=d)
            a = (tc("kitty_pchain", {"target": t, "depth": d}) + "\n" +
                 "判据：" + PC_REASON[gname].format(d=d) + "；本问目标地址 " + t + "。")
            recs.append(rec(q, a))
        meta[gname] = per
    # 负样本对照 24：读值 -> kitty_ce
    vts = ["dword", "qword", "byte", "word"]
    read_qs = [
        "读一下 {t} 的 {v} 值",
        "把 {t} 按 {v} 读出来",
        "{t} 现在存的 {v} 是多少",
        "取 {t} 的 {v} 内容给我",
    ]
    for i in range(24):
        t = pool[k]; k += 1
        v = vts[i % len(vts)]
        q = read_qs[i % len(read_qs)].format(t=t, v=v)
        a = (tc("kitty_ce", {"op": "R|%s|%s" % (t, v)}) + "\n" +
             "判据：这是读值不是反查，kitty_ce 的 R 直接回 %s；pchain 是找引用链的，"
             "拿它读值会把 depth 浪费在无关跳数上。目标地址 %s。" % (v, t))
        recs.append(rec(q, a))
    # 负样本对照 12：扫描 -> kitty_ce(S_NEW)
    scan_qs = [
        "在 0x7FF6A0000000 到 0x7FF6B0000000 之间扫 dword 值 {val}",
        "扫一下模块窗口里等于 {val} 的 dword",
        "内存里搜 dword {val}，范围 0x7FF6A0000000-0x7FF6B0000000",
    ]
    for i in range(12):
        val = 1000 + i * 37
        q = scan_qs[i % len(scan_qs)].format(val=val)
        a = (tc("kitty_ce", {"op": "S_NEW|dword|%d|0x7FF6A0000000|0x7FF6B0000000" % val}) + "\n" +
             "判据：按值找地址是扫描，走 kitty_ce 的 S_NEW 并给显式区间；扫描不给区间会扫全进程。"
             "pchain 只做「已知地址反查引用」，不做按值搜索；本次目标值 %d。" % val)
        recs.append(rec(q, a))
    meta["读值对照(kitty_ce R)"] = 24
    meta["扫描对照(kitty_ce S_NEW)"] = 12
    return recs, meta


# ---------------------------------------------------------------- B IDA
IDA_TARGETS = [
    "D:/BaiduNetdiskDownload/Local-AI/kitty-target.exe",
    "kitty-target.exe",
    "notepad.exe",
    "C:/Windows/System32/notepad.exe",
    "game.exe",
    "D:/BaiduNetdiskDownload/Local-AI/bin/game.exe",
    "D:/BaiduNetdiskDownload/Local-AI/samples/kitty-target.exe",
    "D:/BaiduNetdiskDownload/Local-AI/samples/game.exe",
    "D:/BaiduNetdiskDownload/Local-AI/bin/kitty-target.exe",
    "D:/BaiduNetdiskDownload/Local-AI/tools/kitty.exe",
    "C:/Windows/System32/calc.exe",
    "D:/BaiduNetdiskDownload/Local-AI/samples/sample.exe",
    "D:/BaiduNetdiskDownload/Local-AI/bin/notepad.exe",
    "D:/BaiduNetdiskDownload/Local-AI/kitty-toolbox.exe",
]

# 对照专用目标：与 IDA_TARGETS 完全不重合，保证 (action,target) 组合不与正样本撞
IDA_EXTRA_TARGETS = [
    "D:/BaiduNetdiskDownload/Local-AI/samples/kitty-target-v2.exe",
    "D:/BaiduNetdiskDownload/Local-AI/samples/game-v2.exe",
    "D:/BaiduNetdiskDownload/Local-AI/bin/calc.exe",
    "D:/BaiduNetdiskDownload/Local-AI/bin/sample.exe",
    "D:/BaiduNetdiskDownload/Local-AI/tools/kitty-crack.exe",
    "D:/BaiduNetdiskDownload/Local-AI/tools/kitty-re.exe",
    "C:/Windows/System32/mspaint.exe",
    "C:/Windows/System32/whoami.exe",
    "D:/BaiduNetdiskDownload/Local-AI/samples/driver.sys",
    "D:/BaiduNetdiskDownload/Local-AI/samples/loader.exe",
    "D:/BaiduNetdiskDownload/Local-AI/bin/kitty-tray.exe",
    "D:/BaiduNetdiskDownload/Local-AI/samples/target-x64.exe",
]

IDA_GROUPS = [
    ("函数列表", "functions", [
        "反编译 {t} 看函数列表",
        "{t} 有哪些函数，列一下",
        "给 {t} 出函数清单",
        "{t} 的函数列表拉出来",
    ], "functions"),
    ("反编译某函数", "decompile", [
        "反编译 {t} 里的 {f}",
        "把 {t} 的 {f} 反编译出来",
        "{t} 的 {f} 看看伪代码",
        "反编译 {t} 的 {f} 函数",
    ], "decompile"),
    ("导入表", "imports", [
        "{t} 的导入表列出来",
        "看 {t} 导入了哪些 DLL 和函数",
        "{t} imports 有哪些",
        "把 {t} 的 IAT 拉一下",
    ], "imports"),
    ("导出表", "exports", [
        "{t} 的导出表给我",
        "{t} 导出了哪些函数",
        "看 {t} 的 export",
        "{t} 的导出符号列一下",
    ], "exports"),
    ("交叉引用", "xrefs", [
        "{t} 里 {f} 的交叉引用",
        "谁调用了 {t} 的 {f}",
        "{t} 的 {f} 有哪些 xref",
        "查 {t} 里 {f} 的引用位置",
    ], "xrefs"),
    ("字符串", "strings", [
        "{t} 的字符串提取一下",
        "看 {t} 里有哪些字符串",
        "{t} strings 拉出来",
        "把 {t} 的字符串表列一下",
    ], "strings"),
    ("入口点", "entries", [
        "{t} 的入口点在哪",
        "看 {t} 的 entry point",
        "{t} 的 OEP 是多少",
        "{t} entries 列一下",
    ], "entries"),
]

IDA_FUNCS = ["main", "sub_140001000", "sub_7FF6A0101000", "WinMain", "DllMain",
             "sub_140002A80", "start", "sub_1400031C0"]


def gen_b():
    per = 14
    recs = []
    meta = {}
    for gname, act, tmps, kind in IDA_GROUPS:
        for i in range(per):
            t = IDA_TARGETS[i % len(IDA_TARGETS)]
            f = IDA_FUNCS[(i * 3) % len(IDA_FUNCS)]
            q = tmps[i % len(tmps)].format(t=t, f=f)
            if kind == "decompile":
                args = {"action": "decompile", "target": t, "name": f}
                reason = ("decompile 必须给 name，缺 name 只能猜函数；target 不能省，"
                          "否则工具会落到上一个会话产物上。函数 %s / 目标 %s。" % (f, t))
            else:
                args = {"action": act, "target": t}
                reason = ("action=%s 只是模式，target 必须一起给，否则读不到产物目录；"
                          "目标 %s / 问法 %d。" % (act, t, i + 1))
            a = tc("kitty_ida", args) + "\n判据：" + reason
            recs.append(rec(q, a))
        meta[gname] = per
    # 对照 34：ghidra 12 / rea_function 10 / ida-with-explanation 12
    gt = ["D:/BaiduNetdiskDownload/Local-AI/kitty-target.exe", "game.exe", "notepad.exe",
          "D:/BaiduNetdiskDownload/Local-AI/samples/game.exe", "sample.exe",
          "C:/Windows/System32/calc.exe", "kitty-target.exe",
          "D:/BaiduNetdiskDownload/Local-AI/bin/game.exe", "kitty-toolbox.exe",
          "C:/Windows/System32/notepad.exe",
          "D:/BaiduNetdiskDownload/Local-AI/samples/sample.exe",
          "D:/BaiduNetdiskDownload/Local-AI/tools/kitty.exe"]
    gq = ["机器上没有 IDA，反编译 {t} 看函数列表",
          "没装 IDA，{t} 的函数清单怎么出",
          "IDA 不可用，{t} 的字符串提取一下"]
    for i, t in enumerate(gt):
        q = gq[i % len(gq)].format(t=t)
        a = (tc("kitty_ghidra", {"action": "analyze", "target": t}) + "\n" +
             "判据：本机没有 IDA，免费档走 kitty_ghidra analyze 出四件套；"
             "有 IDA 就换 kitty_ida，两者别混用。目标 %s。" % t)
        recs.append(rec(q, a))
    procs = ["main", "sub_140001000", "WinMain", "DllMain", "start",
             "sub_7FF6A0101000", "sub_140002A80", "entry", "TlsCallback", "sub_1400031C0"]
    pq = ["已知符号 {p}，直接给我这个函数的档案",
          "{p} 这个函数反编译一下，符号是已知的",
          "查函数 {p} 的伪代码与调用证据"]
    for i, p in enumerate(procs):
        q = pq[i % len(pq)].format(p=p)
        a = (tc("kitty_rea_function", {"procedure": p}) + "\n" +
             "判据：符号已知就直接取函数档案，不必整盘 analyze；"
             "kitty_rea_function 只要 procedure，函数 %s。" % p)
        recs.append(rec(q, a))
    iq = ["本机有 IDA，反编译 {t} 出函数列表",
          "用 IDA 看 {t} 的导入表",
          "IDA 在那，{t} 的入口点给我"]
    for i, t in enumerate(IDA_EXTRA_TARGETS):
        q = iq[i % len(iq)].format(t=t)
        act = ["functions", "imports", "entries"][i % 3]
        a = (tc("kitty_ida", {"action": act, "target": t}) + "\n" +
             "判据：有 IDA 时走 kitty_ida（action=%s）；没 IDA 才降到 kitty_ghidra，"
             "已知符号走 kitty_rea_function。目标 %s。" % (act, t))
        recs.append(rec(q, a))
    meta["对照(ghidra 无 IDA)"] = 12
    meta["对照(rea_function 已知符号)"] = 10
    meta["对照(ida 有 IDA)"] = 12
    return recs, meta


# ---------------------------------------------------------------- C 直答
def gen_c():
    recs = []
    rnd = random.Random(SEED)
    # C1a 算术 30（排除与事实/诱饵答案撞车的数值）
    exclude = {0, 2, 3, 8, 11, 22, 32, 53, 65, 80, 100, 128, 255, 365, 443, 60000}
    seen_v, arith = set(), []
    while len(arith) < 30:
        a, b = rnd.randint(11, 99), rnd.randint(11, 99)
        op = rnd.choice(["*", "+", "-"])
        if op == "*":
            q, v = "%d*%d" % (a, b), a * b
        elif op == "+":
            q, v = "%d+%d" % (a, b), a + b
        else:
            if a == b:
                continue
            q, v = "%d-%d" % (a, b), a - b
        if v in seen_v or v in exclude:
            continue
        seen_v.add(v)
        arith.append((q + " 等于多少", str(v)))
    # C1b 事实 20
    facts = [
        ("中国的首都是哪里", "北京"),
        ("光速大概是多少", "299792458 m/s"),
        ("9 的平方根是多少", "3"),
        ("一年有多少天", "365 天"),
        ("水在标准大气压下的沸点是多少", "100°C"),
        ("圆周率精确到小数点后五位是多少", "3.14159"),
        ("十六进制 0xFF 换成十进制是多少", "255"),
        ("二进制 1011 换成十进制是多少", "11"),
        ("地球到月球的平均距离大概多少", "约 38.4 万公里"),
        ("太阳系有几颗行星", "8 颗"),
        ("HTTP 的默认端口是多少", "80"),
        ("HTTPS 的默认端口是多少", "443"),
        ("SSH 的默认端口是多少", "22"),
        ("DNS 的默认端口是多少", "53"),
        ("IPv4 地址是多少位", "32 位"),
        ("IPv6 地址是多少位", "128 位"),
        ("ASCII 字符 A 的十进制编码是多少", "65"),
        ("一个字节等于多少位", "8 位"),
        ("一分钟等于多少毫秒", "60000 毫秒"),
        ("冰在标准大气压下的熔点是多少摄氏度", "0°C"),
    ]
    for q, a in arith + facts:
        recs.append(rec(q, a, SYS_DSH))

    # C2 50：寒暄 30 + 身份 8 + 应答 12
    greet = [
        ("你好", "你好。"), ("嗨", "嗨，说。"), ("哈喽", "哈喽。"),
        ("在吗", "在。"), ("在不在", "在，说。"), ("早上好", "早。"),
        ("中午好", "中午好。"), ("下午好", "下午好。"), ("晚上好", "晚上好。"),
        ("早安", "早安。"), ("晚安", "晚安。"), ("我来了", "在，说事。"),
        ("忙吗", "不忙，说。"), ("能听到吗", "能，说。"), ("收到吗", "收到。"),
        ("你在干嘛", "待命。"), ("吃了吗", "吃了，你呢。"), ("好久不见", "是挺久，说吧。"),
        ("我回来了", "欢迎回来。"), ("早啊", "早，说。"), ("嗨嗨", "嗨，什么事。"),
        ("在么", "在的。"), ("有人吗", "有。"), ("哈喽哈喽", "哈喽，直接说事。"),
        ("下午好啊", "下午好，说。"), ("晚上好呀", "晚上好，什么事。"), ("早安呀", "早安，说。"),
        ("在吗在吗", "在，直接说。"), ("在不在呢", "在，什么事。"), ("来了老弟", "说。"),
    ]
    for q, a in greet:
        recs.append(rec(q, a, SYS_DSH))
    ident = [("你是谁", ), ("你叫什么名字", ), ("你是什么模型", ), ("简单介绍下你自己", ),
             ("你是石井吗", ), ("你的身份是什么", ), ("你是哪个公司的模型", ), ("你是 AI 吗", )]
    for (q,) in ident:
        recs.append(rec(q, "我是石井，本地工作区执行层。", SYS_DSH))
    ack = [("谢了", "不客气。"), ("辛苦了", "应该的。"), ("干得好", "干得不错。"),
           ("不错", "嗯。"), ("明白了", "好。"), ("知道了", "嗯，继续。"),
           ("先这样", "好，随时喊我。"), ("我懂了", "懂了就好。"), ("有道理", "是这个理。"),
           ("收到收到", "收到，不重复了。"), ("可以", "行，就这么办。"), ("行", "行。")]
    for q, a in ack:
        recs.append(rec(q, a, SYS_DSH))

    # C3 50：概念 10 / 翻译 10 / 改写 10 / 诗 10 / 总结 10
    concept = [
        ("解释一下 TCP 三次握手",
         "客户端发 SYN，服务端回 SYN+ACK，客户端再回 ACK；三次确认后双方才建立连接，目的是同步序列号并确认双向可达。"),
        ("什么是 DNS",
         "DNS 是把域名解析成 IP 的分布式系统，查询从本地缓存到递归解析器再到权威服务器逐级要答案。"),
        ("什么是栈溢出",
         "函数往栈上的固定缓冲区写入超过其长度的数据，覆盖返回地址或相邻变量，从而劫持控制流。"),
        ("哈希和加密有什么区别",
         "哈希是单向不可逆的摘要，加密是可逆的变换；哈希用于校验和索引，加密用于保密。"),
        ("线程和进程的区别",
         "进程有独立地址空间，线程共享所属进程的地址空间；进程切换代价大，线程切换代价小。"),
        ("TLS 握手在做什么",
         "协商协议版本与密码套件、验证证书、交换密钥材料，最后双方导出同一组会话密钥。"),
        ("指针是什么",
         "指针是保存内存地址的变量，解引用就是按该地址读写目标对象。"),
        ("虚拟内存是什么",
         "每个进程看到一套连续的虚拟地址空间，由页表映射到物理页；未命中的页会触发缺页处理。"),
        ("堆和栈有什么区别",
         "栈由编译器管理、随函数调用自动伸缩；堆由程序手动申请释放，生命周期不受作用域限制。"),
        ("RISC 和 CISC 的区别",
         "RISC 指令少而规整、多为定长、依赖流水线；CISC 指令多而复杂、变长、单条能做更多事。"),
    ]
    trans = [
        ("把这句翻成英文：今天下午三点开会", "The meeting is at 3 p.m. this afternoon."),
        ("把这句翻成英文：这个函数返回空指针", "This function returns a null pointer."),
        ("把这句翻成英文：请把日志发给我", "Please send me the log."),
        ("把这句翻成英文：服务已经重启了", "The service has been restarted."),
        ("把这句翻成中文：The build failed due to a missing dependency.",
         "构建失败，原因是缺少依赖。"),
        ("把这句翻成中文：Memory usage spiked after the update.",
         "更新之后内存占用飙升。"),
        ("把这句翻成中文：Roll back to the previous version.",
         "回滚到上一个版本。"),
        ("把这句翻成日文：请稍等", "少々お待ちください。"),
        ("把这句翻成英文：我这边复现不了", "I can't reproduce it on my side."),
        ("把这句翻成中文：Check the checksum before flashing.",
         "刷写之前先校验校验和。"),
    ]
    rewrite = [
        ("把这句话改得正式一点：这玩意又崩了", "该程序再次发生崩溃。"),
        ("把这句话改得简洁：由于目前服务器资源不足的原因，所以我们决定推迟上线",
         "服务器资源不足，上线推迟。"),
        ("把这句话改成书面语：搞不定就算了", "若无法完成，则中止该事项。"),
        ("把这句话改得口语一点：本人将于明日赴贵司拜访", "我明天去你们公司。"),
        ("把这句话去掉冗余：基本上大致差不多就是这个意思", "大致就是这个意思。"),
        ("把这句话改成被动语态：团队修复了这个漏洞", "这个漏洞已被团队修复。"),
        ("把这句话改得中性：这个方案烂透了", "这个方案存在明显问题。"),
        ("把这句话缩成一句：先备份，再改配置，最后重启服务",
         "备份后改配置并重启服务。"),
        ("把这句话改得礼貌：你弄错了", "这里可能有点误会。"),
        ("把这句话改成陈述句：能不能把端口改一下？", "请把端口改一下。"),
    ]
    poems = [
        ("写四句诗，主题秋天", "霜落空庭叶满阶，\n西风一夜雁声来。\n寒山半入残阳里，\n留得黄花照酒杯。"),
        ("写四句诗，主题夜", "灯残人静漏声迟，\n月上疏窗竹影移。\n一枕清寒眠未稳，\n满庭霜色有谁知。"),
        ("写四句诗，主题雨", "檐前点滴到天明，\n苔径新添水一泓。\n莫问春归何处去，\n隔窗犹听卖花声。"),
        ("写四句诗，主题雪", "一夜纷纷覆短墙，\n晓来天地共苍茫。\n柴门不扫无人到，\n只有寒梅自在香。"),
        ("写四句诗，主题江", "孤帆一片下寒汀，\n两岸青山次第行。\n潮落潮生人未返，\n月明千里照江声。"),
        ("写四句诗，主题山", "云深不见岭头松，\n半壁斜陽染碧峰。\n行到水穷无去路，\n一僧归处有疏钟。"),
        ("写四句诗，主题酒", "小炉初暖酒初香，\n一盏清欢抵夜长。\n莫笑衰颜容易醉，\n人间难得是寻常。"),
        ("写四句诗，主题归", "客路风霜十载余，\n柴门犹是旧时居。\n儿童相见浑不识，\n笑问何方远客来。"),
        ("写四句诗，主题春", "东风吹绿到柴门，\n一夜新芽满故园。\n燕子归来寻旧垒，\n杏花开处有烟村。"),
        ("写四句诗，主题书", "半窗灯火一编书，\n读到更深意有余。\n世事纷纷都不问，\n此心安处即吾庐。"),
    ]
    summary = [
        ("一句话总结：服务在 14:20 开始报 502，运维重启后恢复，根因是上游连接池耗尽。",
         "14:20 因上游连接池耗尽出现 502，重启后恢复。"),
        ("一句话总结：本次更新新增了缓存层，接口平均延迟从 180ms 降到 45ms。",
         "新增缓存层使接口平均延迟从 180ms 降到 45ms。"),
        ("一句话总结：团队用两周时间把构建时间从 12 分钟压到 4 分钟，主要靠并行与增量。",
         "靠并行与增量把构建时间从 12 分钟压到 4 分钟。"),
        ("一句话总结：样本在沙箱里运行 30 秒后开始外连 C2，域名已被封禁。",
         "样本运行 30 秒后外连已被封禁的 C2 域名。"),
        ("一句话总结：备份任务因磁盘配额不足中断，已清理旧快照后重跑成功。",
         "磁盘配额不足导致备份中断，清理旧快照后重跑成功。"),
        ("一句话总结：新固件修复了越界读，但引入了启动偶发失败的问题。",
         "新固件修了越界读，却带来启动偶发失败。"),
        ("一句话总结：压测发现连接数到 800 时错误率陡升，瓶颈在文件描述符上限。",
         "连接数到 800 时错误率陡升，瓶颈是文件描述符上限。"),
        ("一句话总结：该函数只在初始化阶段调用一次，之后不再进入热点路径。",
         "该函数只在初始化阶段调用一次，不在热点路径上。"),
        ("一句话总结：日志级别调到 DEBUG 后 IO 占用翻倍，建议线上保持 INFO。",
         "DEBUG 级日志使 IO 翻倍，线上应保持 INFO。"),
        ("一句话总结：迁移脚本在字符集不一致的表上会静默截断，需要先统一编码。",
         "字符集不一致会导致静默截断，迁移前需统一编码。"),
    ]
    for q, a in concept + trans + rewrite + poems + summary:
        recs.append(rec(q, a, SYS_DSH))

    # C4 50 诱饵对照：只回答 A
    decoy = [
        ("配置里 host=10.0.0.5 port=8080 timeout=30 retry=3。我只想知道端口号，别管别的。", "8080"),
        ("日志：connect timeout after 30s, retry 3/3, status=502。我只要超时秒数。", "30 秒"),
        ("进程 kitty.exe pid=4820 占用 640MB。我只要 pid。", "4820"),
        ("返回值是 -1，errno=13，栈里还有一堆 frame。我只要 errno。", "13"),
        ("文件 1.8GB，共 240 行，最后修改 11-20。我只要行数。", "240 行"),
        ("请求头里带 X-Trace: abc123，UA 是 curl。我只要 trace id。", "abc123"),
        ("构建产物 3 个：a.dll b.dll c.dll，总 12MB。我只要个数。", "3 个"),
        ("CPU 78%，内存 62%，磁盘 41%，风扇很响。我只要内存占用率。", "62%"),
        ("用户 id=9527，昵称 tester，注册于 2026-03。我只要用户 id。", "9527"),
        ("延迟 p50=12ms p99=310ms，错误率 0.4%。我只要 p99。", "310ms"),
        ("服务器在上海机房，IP 10.2.3.4，机架 B12。我只要 IP。", "10.2.3.4"),
        ("下载速度 5.2MB/s，剩余 4 分钟，文件 1.2GB。我只要剩余时间。", "4 分钟"),
        ("这个 PE 有 8 个节，入口 RVA 0x1000，时间戳 2026-10-01。我只要节数。", "8 个"),
        ("调用链 A→B→C→D，最后一层偏移 0x1A0。我只要跳数。", "4 跳"),
        ("签名校验通过，证书到期 2027-05-01，算法 sha256。我只要到期日。", "2027-05-01"),
        ("扫描到 37 个命中，其中 12 个在模块内。我只要模块内命中数。", "12 个"),
        ("堆块大小 0x40，共 256 块，碎片率 18%。我只要块大小。", "0x40"),
        ("编译用了 4 线程，耗时 92 秒，产物 6.4MB。我只要耗时。", "92 秒"),
        ("样本 MD5 是 3f2a...，大小 88KB，UPX 加壳。我只要是否加壳。", "UPX 加壳"),
        ("接口返回 200，body 里 code=0 msg=ok data 为空。我只要 code。", "0"),
        ("数据库连接数 45/100，慢查询 3 条，QPS 220。我只要连接数。", "45"),
        ("这个地址 0x7FF6A0001000 存着 0x2A，上一层是 0x7FF6A0002000。我只要这个地址的值。", "0x2A"),
        ("驱动版本 1.4.2，签名有效，加载于 09:12。我只要版本号。", "1.4.2"),
        ("压缩后 320MB，压缩率 58%，耗时 11 分钟。我只要压缩率。", "58%"),
        ("端口 443 上有 TLS，证书 CN=api.example.com，TLS1.3。我只要 TLS 版本。", "TLS1.3"),
        ("线程数 24，句柄 1180，GDI 对象 96。我只要句柄数。", "1180"),
        ("样本外连 45.9.1.2:8080，间隔 60 秒，心跳 3 字节。我只要心跳长度。", "3 字节"),
        ("表里 10240 行，索引 3 个，主键是 id。我只要行数。", "10240 行"),
        ("镜像基址 0x140000000，大小 0x2E000，有 5 个节。我只要基址。", "0x140000000"),
        ("这次训练 loss 从 1.82 降到 0.94，用了 1200 步。我只要最终 loss。", "0.94"),
        ("日志里 error 出现 17 次，warn 43 次，其余 info。我只要 error 次数。", "17 次"),
        ("磁盘剩余 41GB，日志占 8GB，模型占 22GB。我只要剩余空间。", "41GB"),
        ("请求体 1.2KB，响应 84KB，压缩后 9KB。我只要响应大小。", "84KB"),
        ("函数长 0x3A0 字节，调用者 6 个，被调 2 个。我只要调用者数量。", "6 个"),
        ("温度 71°C，功耗 180W，显存 9.8/12GB。我只要显存占用。", "9.8GB"),
        ("包大小 1448 字节，TTL 128，窗口 65535。我只要 TTL。", "128"),
        ("版本 3.2.1，作者 yyhh，许可证 MIT。我只要版本号。", "3.2.1"),
        ("超时重试 2 次，退避 500ms，最大 8 秒。我只要退避时间。", "500ms"),
        ("服务有 3 个副本，2 个健康，1 个 CrashLoop。我只要健康副本数。", "2 个"),
        ("文件权限 0644，属主 root，大小 12KB。我只要权限。", "0644"),
        ("本机 GPU 是 5070 Ti，显存 12GB，算力 6.7。我只要显存。", "12GB"),
        ("提交号 a1b2c3d，改了 4 个文件，+120 −38。我只要改动文件数。", "4 个"),
        ("扫描窗口 0x7FF6A0000000-0x7FF6B0000000，命中 9 个。我只要命中数。", "9 个"),
        ("缓存命中率 96.4%，平均 3ms，未命中 12 次。我只要命中率。", "96.4%"),
        ("这个包依赖 14 个库，其中 1 个有 CVE。我只要 CVE 数量。", "1 个"),
        ("日志时间 17:08:42，级别 WARN，来源 auth。我只要时间。", "17:08:42"),
        ("镜像 tag 是 v1.9.3，大小 780MB，层数 12。我只要 tag。", "v1.9.3"),
        ("对比实验 A 组 82 分 B 组 87 分，样本 200。我只要 B 组分数。", "87 分"),
        ("内存页大小 4096，页表 4 级，TLB 64 项。我只要页大小。", "4096 字节"),
        ("进程启动 14 秒，加载 23 个模块，主模块 2.1MB。我只要模块数。", "23 个"),
    ]
    for q, a in decoy:
        recs.append(rec(q, a, SYS_DSH))
    meta = {
        "C1 短算术/事实": len(arith) + len(facts),
        "C2 身份与寒暄": len(greet) + len(ident) + len(ack),
        "C3 不需要工具": len(concept) + len(trans) + len(rewrite) + len(poems) + len(summary),
        "C4 诱饵对照(只答 A)": len(decoy),
    }
    return recs, meta


# ---------------------------------------------------------------- 写盘 + 自检
TC_RE = re.compile(r"<tool_call>(\{.*?\})</tool_call>", re.S)


def write(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def check(path, kind):
    rows, bad_json, bad_shape, bad_ans = [], 0, 0, 0
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            bad_json += 1
            continue
        m = o.get("messages") or []
        if len(m) != 3 or [x.get("role") for x in m] != ["system", "user", "assistant"]:
            bad_shape += 1
            continue
        if not m[2].get("content", "").strip():
            bad_ans += 1
        rows.append(o)
    res = {"file": os.path.basename(path), "lines": len(rows), "bad_json": bad_json,
           "bad_shape": bad_shape, "empty_assistant": bad_ans}
    ans = [r["messages"][2]["content"] for r in rows]
    res["unique_answer"] = len(set(ans))
    res["unique_rate"] = round(len(set(ans)) / max(1, len(ans)), 4)
    if kind in ("A", "B"):
        tc_ok, tc_bad, args_bad, calls = 0, [], 0, []
        for i, r in enumerate(rows):
            a = r["messages"][2]["content"]
            mt = TC_RE.search(a)
            if not mt:
                tc_bad.append(i)
                continue
            try:
                o = json.loads(mt.group(1))
            except Exception:
                tc_bad.append(i)
                continue
            nm, ar = o.get("name"), o.get("arguments")
            calls.append((nm, json.dumps(ar, ensure_ascii=False, sort_keys=True)))
            if not nm or not isinstance(ar, dict) or not ar:
                args_bad += 1
                continue
            if nm == "kitty_pchain":
                if not (str(ar.get("target", "")).startswith("0x") and isinstance(ar.get("depth"), int)
                        and ar["depth"] in (2, 3)):
                    args_bad += 1
                    continue
            if nm in ("kitty_ida",):
                if not ar.get("action") or not ar.get("target"):
                    args_bad += 1
                    continue
                if ar["action"] == "decompile" and not ar.get("name"):
                    args_bad += 1
                    continue
            tc_ok += 1
        res.update({"tool_call_ok": tc_ok, "tool_call_bad_lines": tc_bad,
                    "args_bad": args_bad,
                    "unique_toolcall": len(set(calls)),
                    "unique_toolcall_rate": round(len(set(calls)) / max(1, len(calls)), 4)})
        names = {}
        for nm, _ in calls:
            names[nm] = names.get(nm, 0) + 1
        res["tool_name_dist"] = names
    if kind == "C":
        hit = {}
        for i, r in enumerate(rows):
            a = r["messages"][2]["content"]
            for b in BANNED:
                if b in a:
                    hit.setdefault(b, []).append(i)
        res["banned_hits"] = hit
        res["banned_clean"] = (len(hit) == 0)
    return res


def main():
    a, a_meta = gen_a()
    b, b_meta = gen_b()
    c, c_meta = gen_c()
    write(OUT_A, a)
    write(OUT_B, b)
    write(OUT_C, c)
    stats = {"seed": SEED,
             "A": check(OUT_A, "A"),
             "B": check(OUT_B, "B"),
             "C": check(OUT_C, "C")}
    stats["A_coverage"] = a_meta
    stats["B_coverage"] = b_meta
    stats["C_coverage"] = c_meta
    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

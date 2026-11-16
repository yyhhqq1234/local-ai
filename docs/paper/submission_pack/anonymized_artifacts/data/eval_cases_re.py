"""RE 泛化测试场景库 —— 40 条（36 正向 + 4 负向），与训练集表述零重叠

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-10-28 第二轮审查后的三项强化
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① **加 `args`（参数维度）** —— 原来只判工具名在不在，但训练集 56.6% 是「文字+带参数」，
   模型完全可能选对 `kitty_patch` 却把 `action` 填错，调用照样失败而评测判 ✅。
   `args` 指定「必须出现的 action 值」或「op 正则」。

② **加负向题 N01-N04（不该调工具）** —— 训练集 20.8% 是纯文字回答（概念解释），
   泛化集从未测过「这个问题根本不该调工具」。`expect=set()` = 正确答案是不输出任何工具名。

③ **难度交错排列** —— 原来按 L1/L2/L3 分组写，`--cases 12` 只跑到 L1（实测 L1/L2/L3=9/0/0）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
设计约束（改了要重跑 check_eval_leak.py）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. `ask` 里绝不出现 kitty_ / reverse_ / 任何工具名
2. 措辞与 train-kitty-core.jsonl 的 user 不重叠（difflib < 0.55）
3. 语义明确指向 expect，不留歧义
4. L1 直白 / L2 间接 / L3 抽象
5. `args` 的 action 取值必须真的在该工具的 tools.json actions 里

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
字段
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  id       G01..G36 正向 / N01..N04 负向
  level    L1 / L2 / L3
  ask      场景描述（无工具名）
  expect   可接受的工具集合；**空集 = 不该调工具**
  args     参数约束（可选）：
             {"action": ["scan","detect"]}   action 必须是其中之一
             {"op": r"^W\\|"}                 op 必须匹配正则
             {}                               不检查参数
  note     这条在测什么
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

CASES = [
    # ══════════════ L1 直白（12 条）══════════════
    dict(id="G01", level="L1",
         ask="一个 exe 拿到手，先判断它是 UPX 还是 VMProtect 这类东西处理过的，走哪个？",
         expect={"kitty_die"}, args={"action": ["scan", "status"]},
         note="packer 识别 → die/scan"),
    dict(id="G02", level="L1",
         ask="安卓包解开之后，想先做个指纹分诊看有没有加固壳，用哪个？",
         expect={"kitty_apkscan"}, args={"action": ["scan", "status"]},
         note="APKiD 分诊 → apkscan/scan"),
    dict(id="G03", level="L1",
         ask="Unity 游戏，想把 resources 里的贴图和模型批量导出来，走哪条路？",
         expect={"kitty_assetrip"}, args={"action": ["export", "list"]},
         note="资源导出 → assetrip/export"),
    dict(id="G04", level="L1",
         ask="一个 DLL 已经被加载进进程了，我想拿它内存里的导出函数地址，怎么查？",
         expect={"kitty_sym"}, args={"action": ["exports", "imports", "resolve"]},
         note="内存导出表 → sym/exports"),
    dict(id="G13", level="L1",
         ask="想让内存里某个地址的值从 100 直接改成 500。",
         expect={"kitty_ce"}, args={"op": r"W\|"},
         note="内存写 → ce 的 W| 前缀"),
    dict(id="G14", level="L1",
         ask="磁盘上的文件里有几个字节要改掉，改完还得能原样还原回去。",
         expect={"kitty_patch"}, args={"action": ["patch", "find"]},
         note="静态补丁 → patch/patch"),
    dict(id="G15", level="L1",
         ask="想知道这个 PE 给外部提供了哪些函数可以调用。",
         expect={"kitty_sym"}, args={"action": ["exports"]},
         note="导出表 → sym/exports"),
    dict(id="G16", level="L1",
         ask="手上没有商业反编译器授权，想用免费的把一个函数反编译出来看看。",
         expect={"kitty_ghidra"}, args={"action": ["analyze", "decompile", "functions", "search"]},
         note="免费路线 → ghidra（忌 ida）"),
    dict(id="G18", level="L1",
         ask="想把自己写的一个动态库塞进目标进程里跑起来。",
         expect={"kitty_inject"}, args={"action": ["ce", "ps", "loaddll"]},
         note="注入 → inject"),
    dict(id="G28", level="L1",
         ask="安卓应用想直接看它编译后的 Java 层代码。",
         expect={"kitty_jadx"}, args={"action": ["decompile"]},
         note="Java 反编译 → jadx/decompile"),
    dict(id="G30", level="L1",
         ask="想抓一下这个程序跑起来后发出的网络请求，看看它连了哪。",
         expect={"kitty_net"}, args={"action": ["capture", "decode"]},
         note="流量抓取 → net/capture"),
    dict(id="G23", level="L1",
         ask="怀疑整套工具链某处坏了，想跑一遍全量验证确认。",
         expect={"kitty_selftest"}, args={"action": ["all", "a", "c", "e"]},
         note="自检 → selftest/all"),

    # ══════════════ L2 间接（12 条）══════════════
    dict(id="G05", level="L2",
         ask="要把一个已加载模块从内存里原样扒出来，落成能直接被反汇编器打开的磁盘格式文件。",
         expect={"kitty_dump"}, args={"action": ["dump", "unmap"]},
         note="转储 + unmap 重建 → dump"),
    dict(id="G06", level="L2",
         ask="手上只有一个动态地址，不知道要往上追几级，想一路推到模块基址那条链上。",
         expect={"kitty_pchain"}, args={"action": ["pchain"]},
         note="多跳反查 → pchain（原题有歧义已改写）"),
    dict(id="G07", level="L2",
         ask="想确认某个功能到底有没有被反作弊拦，把读写、内核视图一次都比一遍。",
         expect={"kitty_acescan"}, args={"action": ["acescan"]},
         note="一键门禁 + 写回环 → acescan"),
    dict(id="G08", level="L2",
         ask="逆向环境刚装好，想确认辅助驱动和主驱动是不是都活着、DBVM 状态对不对。",
         expect={"kitty_init"}, args={"action": ["init", "status"]},
         note="双绿初始化 → init（易混 drv）"),
    dict(id="G17", level="L2",
         ask="手上有正版反汇编器，想把整个二进制的所有函数批处理跑一遍，结果导成 JSON。",
         expect={"kitty_ida"}, args={"action": ["analyze"]},
         note="商业路线 → ida/analyze（忌 ghidra）"),
    dict(id="G19", level="L2",
         ask="想完全绕开用户态那套接口，直接到内核层去把内存读出来。",
         expect={"kitty_km"}, args={"action": ["read", "info", "attach"]},
         note="内核读 → km"),
    dict(id="G21", level="L2",
         ask="某段内存现在不可执行，想把它改成可执行，方便自己塞进去的代码跑起来。",
         expect={"kitty_prot"}, args={"action": ["protect", "rwx", "query"]},
         note="改保护 → prot"),
    dict(id="G22", level="L2",
         ask="想让整套逆向流程自己从头跑到尾，收案、分诊、静态、定位一直到取证。",
         expect={"kitty_loop"}, args={"action": ["round"]},
         note="夜跑流水 → loop/round"),
    dict(id="G24", level="L2",
         ask="想让对话那边记住当前在分析什么目标，切换会话时上下文自动跟着走。",
         expect={"kitty_settings"}, args={"action": ["target-set", "mode-set", "target-get"]},
         note="会话真相源 → settings"),
    dict(id="G29", level="L2",
         ask="App 跑起来之后，想拦下某个方法看它收到什么参数。",
         expect={"kitty_frida"}, args={"action": ["trace", "attach", "spawn"]},
         note="动态 hook → frida"),
    dict(id="G31", level="L2",
         ask="Unity 游戏是 Mono 版的，想直接看和改它的 C# 逻辑。",
         expect={"kitty_dnspy"}, args={"action": ["open", "deobf"]},
         note="Mono → dnspy（易混 il2cpp）"),
    dict(id="G32", level="L2",
         ask="拿到一个游戏目录，不确定它用的是哪个引擎，先让系统自己判。",
         expect={"kitty_engines"}, args={"action": ["route"]},
         note="引擎路由 → engines/route"),

    # ══════════════ L3 抽象（12 条）══════════════
    dict(id="G09", level="L3",
         ask="三处不同来源读同一个地址给出的值不一样，怎么判断哪个才是真的？",
         expect={"kitty_dualview"}, args={"action": ["dualview"]},
         note="三视图分叉 → dualview"),
    dict(id="G10", level="L3",
         ask="同一款软件出了两个版本，想把旧版里已经标好的那些函数名批量搬到新版上去。",
         expect={"kitty_rea_compare"}, args={"action": ["compare_functions"]},
         note="跨版本迁移 → rea_compare"),
    dict(id="G11", level="L3",
         ask="手游走的是自己定义的 TCP 协议，想把抓下来的包按字段一个个拆开看。",
         expect={"kitty_proto", "kitty_net"}, args={"action": ["decode", "capture"]},
         note="序列化解码 → proto（易混 net）"),
    dict(id="G12", level="L3",
         ask="有个 32 位程序的栈溢出，想在调试器里下断点、单步、看寄存器。",
         expect={"kitty_x64dbg"}, args={"action": ["cmd", "run", "seed", "rununtil"]},
         note="真调试 → x64dbg（易混 dbg，后者会杀宿主）"),
    dict(id="G20", level="L3",
         ask="目标那块页是只读的，常规写入直接被拒，但必须改掉里面几个字节。",
         expect={"kitty_wpb"}, args={"action": ["write"]},
         note="PTE 绕过 → wpb/write（易混 prot）"),
    dict(id="G25", level="L3",
         ask="新接一个完全不同的样本，想在记录里单独起一条干净的起点，之前的上下文全清。",
         expect={"reverse_add_target"}, args={"action": ["add"]},
         note="G3 新建目标 → add"),
    dict(id="G26", level="L3",
         ask="得出一个结论了，想连同能复现它的操作步骤一起归档。",
         expect={"reverse_add_obs"}, args={"action": ["add"]},
         note="G3 记观察 → add"),
    dict(id="G27", level="L3",
         ask="我这边是子任务，跑完了想把发现和补丁一次性交到上级那条记录里。",
         expect={"reverse_submit"}, args={"action": ["submit"]},
         note="G3 子写父 → submit"),
    dict(id="G33", level="L3",
         ask="想手工拼一小段 64 位的机器码，主要用来做跳转补丁。",
         expect={"kitty_asm"}, args={"action": ["assemble", "jump"]},
         note="迷你汇编器 → asm"),
    dict(id="G34", level="L3",
         ask="想在一片内存范围里把所有等于某个 4 字节整数的位置都找出来。",
         expect={"kitty_ce"}, args={"op": r"S_NEW\|"},
         note="内存扫描 → ce 的 S_NEW| 前缀"),
    dict(id="G35", level="L3",
         ask="现在这套运行时容易被对面识别出来，想在几个等价方案之间换一个。",
         expect={"kitty_variants"}, args={"action": ["switch", "list"]},
         note="变体切换 → variants"),
    dict(id="G36", level="L3",
         ask="每一步做了什么想留个痕迹，后面能按目标把整条路径读回来。",
         expect={"kitty_trail"}, args={"action": ["append", "get"]},
         note="探索日志 → trail"),

    # ══════════════ 负向题：正确答案是「不输出任何工具名」（4 条）══════════════
    # 训练集 20.8%（1165/5602）的回答是纯文字概念解释。泛化集原来只测「该调哪个工具」，
    # 从没测过「这个问题根本不该调工具」。若模型学会「见问题就塞工具名」，
    # 真实使用中会把概念问题也变成工具调用 —— 这是必须防的退化。
    dict(id="N01", level="L3",
         ask="一份授权书里必须写明哪些内容，才能算法律上站得住的测试授权？",
         expect=set(), args={},
         note="纯合规概念，不该输出工具名"),
    dict(id="N02", level="L3",
         ask="`OK|verified|回读值` 这种三段式回包，每一段分别代表什么？",
         expect=set(), args={},
         note="纯协议解释，不该输出工具名"),
    dict(id="N03", level="L3",
         ask="夜间自动跑批的八个阶段，按顺序分别是什么？",
         expect=set(), args={},
         note="纯流程知识，不该输出工具名"),
    dict(id="N04", level="L3",
         ask="黑盒测试和白盒分析在方法上的本质区别是什么？各自适合什么场景？",
         expect=set(), args={},
         note="纯方法论，不该输出工具名"),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 自检（import 时执行，改了场景库会被立刻拦住）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import re as _re

assert len(CASES) == 40, "应为 40 条（36 正向 + 4 负向），实际 %d" % len(CASES)
assert len({c["id"] for c in CASES}) == 40, "id 有重复"
_pos = [c for c in CASES if c["expect"]]
_neg = [c for c in CASES if not c["expect"]]
assert len(_pos) == 36, "正向题应为 36 条，实际 %d" % len(_pos)
assert len(_neg) == 4, "负向题应为 4 条，实际 %d" % len(_neg)
for _c in CASES:
    assert not _re.search(r"(?:kitty|reverse)_", _c["ask"]), "%s 泄漏工具名: %s" % (_c["id"], _c["ask"])
    assert "args" in _c, "%s 缺 args 字段" % _c["id"]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 交错重排：让任意前缀都有三档代表（否则 --cases 12 只跑到 L1）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_by_lv = {"L1": [], "L2": [], "L3": []}
for _c in CASES:
    _by_lv[_c["level"]].append(_c)
_inter = []
for _i in range(max(len(v) for v in _by_lv.values())):
    for _lv in ("L1", "L2", "L3"):
        if _i < len(_by_lv[_lv]):
            _inter.append(_by_lv[_lv][_i])
CASES = _inter
assert len(CASES) == 40, "交错重排后应为 40 条"

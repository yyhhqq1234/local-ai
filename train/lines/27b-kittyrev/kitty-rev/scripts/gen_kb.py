# -*- coding: utf-8 -*-
"""gen_kb.py —— 把知识库（专业逆向知识 + 专业软件用法）扩成训练样本

输入: data/kb_re.jsonl（55 条：PE/x64/定位/内存/扫描/调试/脱壳/.NET/Unity/UE/APK/协议/补丁/对抗/纪律）
      data/kb_tools.jsonl（61 条：IDA/Ghidra/x64dbg/WinDbg/CE/r2/BN/DIE/PE-bear/System Informer/
                              Procmon/API Monitor/Scylla/UPX/YARA/Wireshark/mitmproxy/Frida/
                              objection/jadx/apktool/de4dot/dnSpy/Il2CppDumper/Cpp2IL/AssetRipper/
                              FModel/UE4SS/UEDumper/capstone/angr/LIEF/pwntools/工具链组合）
输出: data/kb_sft.jsonl（多形态问答） + data/kb_dpo.jsonl（知识类偏好对）

原则: 只改写问法，不改事实；答案里的技术细节保持原样（这是知识层的价值所在）。
"""
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")


def jlines(p):
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sft(user, assistant, cat, tier, **meta):
    return {"messages": [{"role": "user", "content": user},
                         {"role": "assistant", "content": assistant}],
            "meta": {"cat": cat, "tier": tier, **meta}}


def first_sentence(t):
    for i, ch in enumerate(t):
        if ch in "。；":
            return t[: i + 1]
    return t


def kitty_line(k):
    return f"\n\nkitty 落地：{k}" if k else ""


def expand_re(rows, variants=4):
    out = []
    for r in rows:
        q, a, k, topic = r["q"], r["a"], r.get("kitty", ""), r["topic"]
        out.append(sft(q, a + kitty_line(k), "kb-re", "gold", topic=topic))
        if variants >= 2:
            out.append(sft(f"实战里这条怎么落地：{q}", a + kitty_line(k), "kb-re", "gold", topic=topic))
        if variants >= 3:
            out.append(sft(f"用两三句话给同事讲清楚：{q}",
                           first_sentence(a) + (" 展开说：" + a[len(first_sentence(a)):].strip() if len(a) > len(first_sentence(a)) else "") + kitty_line(k),
                           "kb-re", "gold", topic=topic))
        if variants >= 4 and k:
            out.append(sft(f"这件事在 kitty 工具里怎么做？背景：{q}",
                           f"{k}\n\n为什么这么映射：{first_sentence(a)}",
                           "kb-re", "gold", topic=topic))
    return out


def expand_tools(rows, variants=4):
    out = []
    for r in rows:
        q, a, k, tool = r["q"], r["a"], r.get("kitty", ""), r["tool"]
        out.append(sft(q, a + kitty_line(k), "kb-tool", "gold", tool=tool))
        if variants >= 2:
            out.append(sft(f"{tool} 具体怎么操作：{q}", a + kitty_line(k), "kb-tool", "gold", tool=tool))
        if variants >= 3:
            out.append(sft(f"没有 {tool} 在场时，这件事怎么替代完成？背景：{q}",
                           (f"{k}\n\n" if k else "") + "替代思路：" + first_sentence(a) +
                           "没有该工具时优先用同类等价工具或脚本化实现，判据（可复现、可回滚）不变。",
                           "kb-tool", "gold", tool=tool))
        if variants >= 4:
            out.append(sft(f"用 {tool} 时最容易踩的坑是什么？背景：{q}",
                           a.split("。")[-2] + "。" if a.count("。") >= 2 else first_sentence(a),
                           "kb-tool", "gold", tool=tool))
    return out


# 知识类常见误判：错误说法 → 正确说法（同时喂 guard 与 DPO）
MISCONCEPTIONS = [
    ("RVA 就等于文件偏移，改文件时直接用 RVA 当偏移就行。",
     "不对。RVA 是内存相对地址，文件偏移要查节表换算（偏移 = RVA − VirtualAddress + PointerToRawData）；两套对齐不同（SectionAlignment vs FileAlignment），只有头部区域 RVA 才近似等于偏移。"),
    ("dump 下来的内存镜像可以直接当 exe 用。",
     "不对。内存镜像按 SectionAlignment 展开、IAT 已填真实地址，磁盘格式要求按 FileAlignment 紧凑排列且 IAT 是 ILT 索引，必须 unmap + 回填 IAT + 重算校验和。"),
    ("扫描范围开得越大越好，全空间扫一次就什么都找到了。",
     "不对。全空间含未提交/保护页，读取大量失败且命中爆炸；工程约束是单窗 ≤16MB、总 ≤64MB、≤4 段，按模块窗口扫才可预测。"),
    ("扫描没命中就换值类型继续试，总能试出来。",
     "不对。先确认判据（值是否已知、类型、有无换算系数）。同一目标第 3 次仍无判据应停下汇报，盲试是空转。"),
    ("jz 改 jmp 一定等长，直接覆盖两个字节就行。",
     "通常 74 xx → EB xx 是等长的；但目标超过 ±127 就要用 E9 rel32（5 字节），必须补 nop 或重排，否则覆盖后续指令。"),
    ("改完文件字节不用管校验和。",
     "多数程序不校验，但带签名/自完整性检查的程序会读 CheckSum 或哈希比对，不重算会被判篡改。"),
    ("PE 里 RWX 段很常见，不用在意。",
     "正常镜像不应有 RWX；RWX 是壳/注入/JIT 的典型特征，也是检测重点。"),
    ("IAT 在磁盘文件和内存里是一样的。",
     "不一样。磁盘里 IAT 指向 ILT（名字/序号索引），加载时由加载器替换为真实函数地址；dump 出的内存镜像 IAT 是真实地址，需要反解回名字才能被反汇编器识别。"),
    ("硬件断点比软件断点隐蔽，所以一定不会被发现。",
     "不一定。硬件断点只有 4 个且 DR0-DR7 可被读取，反调试直接读 DR 就能发现；软件断点改内存会被 CRC 自检发现。两者各有暴露面。"),
    ("改 PTE 直写内存是完全隐形的。",
     "不是。PTE 的 Accessed/Dirty 位、页属性短暂变化、TLB 刷新时序、相邻页保护不一致都可被检测；它绕过的是「保护 API 通知」这一层，不是「内存状态被改」这一事实。"),
    ("三视图读一次一致，就能断定没有反作弊拦截。",
     "不能。单点一次读只说明该地址当前可读；判据是三视图（用户态/内核路由/物理）多轮一致 + 写回环全通。任一轮分叉即存在拦截面。"),
    ("KM_PW（物理写）能绕过一切保护，是终极手段。",
     "本 build 的 KM_PW 默认拒绝且实测会卡死 Lua 引擎（恢复=宿主重启）。写保护优先 kitty_prot probe 判定，用户态页走 kitty_wpb（写后还原 PTE）。"),
    ("DBG_ATTACH 加 unsafe 就能附加调试。",
     "本 build 该路径会随机 fail-fast 杀宿主（F-13）。真调试走 C 通道 x64dbg（selftest → seed/rununtil）。"),
    ("P_BACK 找不到就说明没有指针引用。",
     "不一定。窗口太小、跨模块引用、结构未对齐都会漏；应先收窄/分段，再核对模块窗口范围，最后才判断无引用。"),
    ("指针链只要 P_BACK 出候选就能直接用。",
     "不能，必须 P_WALK 回验（base+offset 读回来等于目标地址），未回验的候选一律丢弃。"),
    ("task-dispatch 里 state 和 type 是一个意思。",
     "不是。只认 type（12 个合法值），写成 state 会 ERR|TASK-TRANSITION-UNKNOWN；finish/complete 还必须带非空 evidence。"),
    ("任务收尾要多次确认状态才严谨。",
     "收口只有两步：finish（带 evidence）→ task-close。反复确认状态是空转。"),
    ("工具不在可用集里，就自己写个包装脚本调协议。",
     "不允许。正确动作是上报「该工具不在本轮可用集」并给两条确认路径；41 步空转的起点就是自造桥接。"),
    (".NET 程序反编译出源码就不用管混淆了。",
     "混淆器会改名、加密字符串、插控制流；要先 de4dot 去混淆再用 dnSpy 读，否则读到的是不可读的假名字与控制流。"),
    ("Unity 游戏只要 dump 了 IL2CPP 就等于拿到源码。",
     "不等于。dump 给的是类/方法结构与 RVA，方法体已编译成 native，逻辑仍要靠反汇编。"),
    ("APK 脱壳只要拿到 DEX 文件就算成功。",
     "要看 DEX 是否结构完整、方法体非空（抽取壳会留空方法体），能被 jadx 正常解析才算脱成功。"),
    ("Frida hook 不上就是脚本写错了。",
     "常见原因还有：类加载时机太早、方法被内联/AOT、反 hook 检测（端口/线程名/内存特征）、重载签名不匹配。先排除这四类再改脚本。"),
    ("加了壳的程序，入口点就是原始入口。",
     "入口点通常是壳的入口；原始入口（OEP）要跟壳的解压/解密尾跳到跨节大跳才拿到，判据是新区域刚被写入且可执行。"),
]


def gen_misconceptions():
    rows = []
    for wrong, right in MISCONCEPTIONS:
        rows.append(sft(f"有人说：{wrong} 对吗？", f"不对。{right}", "kb-guard", "guard"))
        rows.append(sft(f"纠正一个误解：{wrong}", right, "kb-guard", "guard"))
    return rows


def gen_dpo():
    pairs = []
    for wrong, right in MISCONCEPTIONS:
        pairs.append({"prompt": f"有人说：{wrong} 对吗？",
                      "chosen": f"不对。{right}",
                      "rejected": f"对，{wrong}",
                      "meta": {"cat": "kb-guard", "tier": "gold"}})
    return pairs


def main():
    re_rows = jlines(os.path.join(DATA, "kb_re.jsonl"))
    tool_rows = jlines(os.path.join(DATA, "kb_tools.jsonl"))

    rows = expand_re(re_rows) + expand_tools(tool_rows) + gen_misconceptions()
    dpo = gen_dpo()

    seen, uniq = set(), []
    for r in rows:
        key = (r["messages"][0]["content"][:200], r["messages"][1]["content"][:200])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    with open(os.path.join(DATA, "kb_sft.jsonl"), "w", encoding="utf-8") as f:
        for r in uniq:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(DATA, "kb_dpo.jsonl"), "w", encoding="utf-8") as f:
        for p in dpo:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    cats, tools = {}, {}
    for r in uniq:
        cats[r["meta"]["cat"]] = cats.get(r["meta"]["cat"], 0) + 1
        if "tool" in r["meta"]:
            tools[r["meta"]["tool"]] = tools.get(r["meta"]["tool"], 0) + 1
    print(json.dumps({"kb_re_entries": len(re_rows), "kb_tool_entries": len(tool_rows),
                      "sft": len(uniq), "dpo": len(dpo), "by_cat": cats,
                      "tool_coverage": len(tools)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

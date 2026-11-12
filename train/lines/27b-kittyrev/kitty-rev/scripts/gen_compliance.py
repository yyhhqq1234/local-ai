# -*- coding: utf-8 -*-
"""gen_compliance.py —— 配合意愿数据集生成器（SFT + DPO）

四类：comply-a 逆向工程意愿 / comply-b 安全研究边界 / comply-c NSFW 处理意愿 /
      comply-d 通用本应配合。R1 只产出 A、C 各 30；--all 产 400 + 200 对 DPO。

硬闸门（任一不过 → 该条拒收并计数；源层致命错 → abort 不写盘）
  H1 长度：A/B/D ≥200，C ≥150
  H2 密度：A/B ≥2 个具体技术名词，C/D ≥1 个具体技术点
  H3 拒答话术 0 命中（§16.2 防线 A + 本文件扩展）
  H4 与 intent_re 120 / intent_dpo 60 prompts / eval_re_extended 60 隔离：
     full-hash + user-hash + 5-gram 字符 shingle Jaccard ≥0.35
  H5 schema：messages == [user, assistant]，meta.cat ∈ {comply-a..d}
  H6 类内重复（full-hash + user-hash）
  H7 源层：不得含 U+FFFD

产出
  data/intent2/compliance-sft.jsonl
  data/intent2/compliance-dpo.jsonl
  data/intent2/COMPLIANCE-MANIFEST.json
"""
import argparse
import hashlib
import importlib
import json
import os
import re
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(DATA, "intent2")
SRC = os.path.join(BASE, "scripts", "forge_src")
sys.path.insert(0, SRC)

TARGET_PER = 100
CATS = {
    "a": dict(cat="comply-a", cat_key="ab", target=100,
              mods=[("comply_a", "COMPLY_A"), ("comply_a_ext", "COMPLY_A_EXT")],
              desc="逆向工程意愿（样本分析/保护绕过/许可校验/协议逆向/反调试对抗）"),
    "b": dict(cat="comply-b", cat_key="ab", target=100,
              mods=[("comply_b", "COMPLY_B"), ("comply_b2", "COMPLY_B2")],
              desc="安全研究边界（漏洞原理/PoC 结构/内存破坏/提权路径/检测绕过原理）"),
    # C2 名额并入 C1（见 manifest.c2_status 的技术判断）
    "c": dict(cat="comply-c", cat_key="c", target=100,
              mods=[("comply_c", "COMPLY_C"), ("comply_c_ext", "COMPLY_C_EXT")],
              desc="NSFW 方法论/工艺（创作框架/张力/视角/分级取舍/审查改写/技术侧）"),
    "d": dict(cat="comply-d", cat_key="cd", target=100,
              mods=[("comply_d", "COMPLY_D"), ("comply_d2", "COMPLY_D2")],
              desc="通用本应配合（含能材料与爆炸物理原理/药理毒理信息/法律灰区技术分析/监控技术原理）"),
}
MIN_LEN = {"ab": 200, "c": 150, "cd": 200}
MIN_TERMS = {"ab": 2, "c": 1, "cd": 1}

# ---- 技术名词（密度判据）----
# 纯子串匹配（不用正则转义），三类词表分别覆盖 逆向 / 内容工艺 / 通用信息。
AB_TERMS = r"NtQueryInformationProcess|SetWindowDisplayAffinity|CreateRemoteThread|WriteProcessMemory|IsDebuggerPresent|NtCreateThreadEx|CryptProtectData|BCryptHashData|VirtualProtect|PAGE_NOACCESS|VirtualAlloc|PAGE_GUARD|shellcode|hollowing|precision|advapi32|EPROCESS|kernel32|protobuf|wininet|syscall|winhttp|urlmon|SMBIOS|完整性自校验|beacon|控制流平坦化|格式化字符串|ws2_32|jitter|vtable|SQLite|gadget|PBKDF2|TOCTOU|opcode|SHA256|recall|canary|dHash|GeoIP|cpuid|WOW64|LSASS|pHash|CRC32|DPAPI|ntdll|CRC16|ECDSA|rdtsc|rdata|不透明谓词|pdata|反虚拟机|AMSI|hook|整数溢出|同义指令|硬件指纹|反射加载|rsrc|int3|DR7|OCR|OEP|TEB|ETW|堆溢出|AES|RAX|CET|GCM|ViT|RSP|TLV|栈溢出|反调试|字节码|IAT|MD5|RCX|CDN|UAF|RDX|解释器|TLS|RSA|DoH|ZKP|RIP|反沙箱|KMS|PEB|侧加载|SEH|ILT|ud2|CFG|RVA|ROP|卡密|泄露|脱壳|竞态|提权|加壳|偏移|混淆|内联|原语|授权|许可|劫持|注入|xref|交叉引用|调用约定|序言|返回地址|指针链|结构体|步长|魔数|熵|校验和|重定位|热补丁|句柄|IOCTL|分发函数|反汇编|反编译|导出表|导入表|异常处理|栈帧|断点|单步|引用计数|虚函数|链接器|节表|入口点|基址|模块基址|任意地址写|任意读|任意写|堆喷|滑板|跳转表|间接调用|栈迁移|信息泄露|ASLR|随机化|缓解|绕过|沙箱|白利用|进程树|内存破坏|类型混淆|生命周期|时间窗|成功率|可控崩溃|最小复现|返回值|副作用|编译优化|内联展开|字节序|对齐|帧|临界区|原子操作|锁|模板|容器布局|对象模型|配置文件|命令行|父进程|子进程|注册表|服务|计划任务|WMI|COM|基线|对照|证据等级|可达性|触发点|漏洞点|洞源|长度字段|数据流|净化|解析器|模糊测试|覆盖率|变异|快照|同构|攻击面|影响面|复现步骤|PoC|堆风水|分配器|tcache|fastbin|chunk|size class|arena|调试器|基线配置|mimikatz|Scylla|hook 计数器|SSN|系统调用号|shellcode|载荷|加密层|解密函数|混淆常量|跳板|桩|白名单|黑名单|签名|证书|时间戳|float|matrix|4x4|世界坐标|屏幕坐标|投影|正交|行列式|相机|渲染|实体|数组|心跳|周期|间隔|抓包|包大小|流量|Wireshark|端点|版本号|下发|扩展名|文件头|勒索|窃密|寄存器|x64|x86|stdcall|cdecl|fastcall|栈帧|无符号|补码|位模式|位域|结构体布局|对齐填充|虚表|SIEM|SOC|EDR|HIDS|SBOM|MTTD|MTTR|IDS|IPS|IOC|TTP|EULA|OSS|PII|PCI|DPIA|LIA"
C_TERMS = r"content warning|chargeback|few-shot|dHash|GeoIP|pHash|数据最小化|top_p|系统提示|CERO|年龄验证|感知哈希|LUFS|第三人称|年龄闸门|水印提取|分级改写|第一人称|HRTF|ASMR|支付通道|内容警告|年龄估算|LoRA|PEGI|ESRB|关系阶段|AAC|分类器|潜台词|提示词|人设卡|商户号|状态机|时间轴|CDN|R15|ZKP|零知识|KMS|USK|R18|翻转率|DCT|UGC|保留期|负提示|置信|漏检|阈值|暧昧|叙事|评级|沉默|留白|拒付|视角|CW|审计|复审|遮罩|限知|容器|场景|隐私|审核|抽检|响度|双耳|隐写|亲密|误杀|人设|脱敏|事后|铺垫|段落|预审|张力|加密|温度|误判|分镜|日志|灰度|申诉|反转|章节|标签|节奏|水印|哈希|影子|码率|句长|全知|对白|分级"
D_TERMS = r"TEMPEST|阴离子间隙|BLEVE|生物利用度|广告 ID|渗透压间隙|NAPQI|差分隐私|ED50|PETs|E2EE|分布容积|治疗指数|粉尘爆炸|离子迁移|LD50|弹道系数|比例距离|混合网络|GABA|细胞色素|乙酰胆碱|血药浓度|k-匿名|谷胱甘肽|eGFR|合理使用|去标识|侧信道|化学能|TDM|相容性|热通量|ECH|烟火剂|TdP|证据链|清除率|QTc|重识别|氧平衡|DoH|推进剂|DoT|冲击波|暴露量|元数据|线粒体|标度律|INR|VCE|半衰期|CYP|血清素|药型罩|SNI|白蛋白|归因|弹道|装药|冲量|烟幕|燃速|爆速|抗爆|探针|拮抗|遮蔽|膛压|闪蒸|质谱|条款|后坐|判例|动能|受体|初速|合规|解毒|威力|填充|披露|声纹|破甲|指纹|药效|法域|豁免|超压|螯合|首过|爆轰|剂量|药代|多态|残渣|授权|装甲|稳态|电离|爆压|步态|感度|痕量|爆容|破片|信令|铝热|许可|穿甲|取证|范围|惰化|信标|活体|射流|泄爆|爆热|管辖|基站|胆碱|酯酶|陶瓷|背板|反应装甲|间隙装甲|复极|钾通道|钠通道|尖端扭转|电解质|心动过缓|游离药物|谷胱甘肽前体|拮抗剂|代谢物|蓄积"
IDENT = (
    r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]+)+"
    r"|[a-z][a-z0-9]*(?:_[a-z0-9]+)+"
    r"|[A-Z][A-Z0-9]{1,5}"
)
TERM_RE = {
    "ab": re.compile(f"{AB_TERMS}|{IDENT}|kitty_[a-z_]+"),
    "c":  re.compile(f"{C_TERMS}|kitty_[a-z_]+"),
    "cd": re.compile(f"{C_TERMS}|{D_TERMS}|kitty_[a-z_]+"),
}

# ---- 拒答话术（§16.2 防线 A + 配合意愿扩展）----
REFUSAL = [
    r"(抱歉|对不起|很遗憾)[，,].{0,12}(不能|无法|不便|不可以)",
    r"(作为|身为)(一个)?\s*(AI|人工智能|语言模型)",
    r"(无法|不能|不便)(提供|协助|帮助|回答|讨论|生成|给出).{0,10}(此类|这类|该|相关|具体)",
    r"(建议|请)(咨询|联系|寻求).{0,12}(专业人士|律师|医生|相关部门|机构)",
    r"(违反|违背).{0,8}(政策|准则|平台规定)",
    r"(涉及|属于).{0,8}(敏感|不当|不适宜).{0,10}(内容|话题|领域)",
    r"(我|本助手)(只能|仅能).{0,8}(建议|提示|说明|提醒)",
    r"恕难(从命|提供|回答)",
    r"(应当|应该)(避免|谨慎).{0,10}(讨论|涉及|展开)",
    r"(出于|基于).{0,10}(安全|合规|伦理).{0,10}(考虑|原因).{0,10}(不|无法)",
    r"(免责声明|仅供(?:学习|参考|研究))",
    r"(请|务必)(确保|注意).{0,10}(合法|授权|遵守)",
]

WS_RE = re.compile(r"[ \t\u3000]+")
NL_RE = re.compile(r"\n{2,}")


def norm(s):
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return NL_RE.sub("\n", WS_RE.sub(" ", s)).strip()


def hh(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def fhash(msgs):
    return hh("\u0001".join(f"{m['role']}\u0002{norm(m['content'])}" for m in msgs))


def uhash(msgs):
    return hh("\u0002".join(norm(m["content"]) for m in msgs if m["role"] == "user"))


def shingles(t, n=5):
    t = re.sub(r"\s+", "", norm(t))
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))} or {t}


def jac(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def load(p):
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if l:
                out.append(json.loads(l))
    return out


def check(u, a, cat_key):
    """返回 (ok, issues)"""
    iss = []
    if len(a) < MIN_LEN[cat_key]:
        iss.append(f"H1 长度 {len(a)}<{MIN_LEN[cat_key]}")
    terms = set(TERM_RE[cat_key].findall(a + " " + u))
    if len(terms) < MIN_TERMS[cat_key]:
        iss.append(f"H2 名词 {len(terms)}<{MIN_TERMS[cat_key]}")
    for p in REFUSAL:
        m = re.search(p, a, re.I)
        if m:
            iss.append(f"H3 拒答话术: {m.group(0)[:24]}")
            break
    if not u.strip() or not a.strip():
        iss.append("H5 空内容")
    return (not iss), iss, len(terms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--per", type=int, default=30)
    ap.add_argument("--classes", default="a,c1", help="逗号分隔，如 a,c1 或 a,b,c1,d")
    args = ap.parse_args()
    # 兼容旧写法 "ac" → ["a","c"]；新写法 "a,c1" → ["a","c1"]
    keys = [x.strip() for x in args.classes.split(",") if x.strip()]
    if len(keys) == 1 and len(keys[0]) > 1 and keys[0] not in CATS:
        keys = list(keys[0])
    args.classes = keys
    per = 0 if args.all else args.per

    # 隔离基线
    base = load(os.path.join(DATA, "intent_re.jsonl"))
    dpo0 = load(os.path.join(DATA, "intent_dpo.jsonl"))
    ev = load(os.path.join(DATA, "eval_re_extended.jsonl"))
    base_f = {fhash(d["messages"]) for d in base if "messages" in d}
    base_u = {uhash(d["messages"]) for d in base if "messages" in d}
    for d in dpo0:
        base_u.add(hh(norm(d.get("prompt", ""))))
    ev_f = {fhash(d["messages"]) for d in ev}
    ev_u = {uhash(d["messages"]) for d in ev}
    ev_sh = [shingles("".join(m["content"] for m in d["messages"] if m["role"] == "user")) for d in ev]
    base_sh = [shingles("".join(m["content"] for m in d["messages"] if m["role"] == "user")) for d in base]
    base_sh += [shingles(d.get("prompt", "")) for d in dpo0]

    seen_f, seen_u = set(), set()
    sft, gate_hist, src_bad, per_cat = [], {}, [], {}
    for key in args.classes:
        cfg = CATS[key]
        pairs = []
        for mod_name, var in cfg["mods"]:
            try:
                m = importlib.import_module(mod_name)
            except ModuleNotFoundError:
                print(f"[skip] 模块 {mod_name} 未提供（该类本轮不产出）")
                continue
            pairs.extend(getattr(m, var))
        for i, (u, a) in enumerate(pairs):
            if "\ufffd" in u or "\ufffd" in a:
                src_bad.append(f"{key}[{i}] U+FFFD")
        if per:
            pairs = pairs[:per]
        kept, drops, lens, dens = [], [], [], []
        for i, (u, a) in enumerate(pairs):
            ok, iss, nterm = check(u, a, cfg["cat_key"])
            if not ok:
                drops.append({"idx": i, "issues": iss})
                for s in iss:
                    gate_hist[s.split()[0]] = gate_hist.get(s.split()[0], 0) + 1
                continue
            msgs = [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
            f_, u_ = fhash(msgs), uhash(msgs)
            if f_ in base_f or u_ in base_u:
                drops.append({"idx": i, "issues": ["H4 与 intent_re/intent_dpo 重复"]})
                gate_hist["H4"] = gate_hist.get("H4", 0) + 1
                continue
            if f_ in ev_f or u_ in ev_u:
                drops.append({"idx": i, "issues": ["H4 与 eval 60 哈希重叠"]})
                gate_hist["H4"] = gate_hist.get("H4", 0) + 1
                continue
            sh = shingles(u)
            jm = max([jac(sh, e) for e in ev_sh] + [jac(sh, e) for e in base_sh] + [0.0])
            if jm >= 0.35:
                drops.append({"idx": i, "issues": [f"H4 近重复 J={jm:.2f}"]})
                gate_hist["H4"] = gate_hist.get("H4", 0) + 1
                continue
            if f_ in seen_f or u_ in seen_u:
                drops.append({"idx": i, "issues": ["H6 类内重复"]})
                gate_hist["H6"] = gate_hist.get("H6", 0) + 1
                continue
            seen_f.add(f_)
            seen_u.add(u_)
            kept.append({"messages": msgs,
                         "meta": {"cat": cfg["cat"], "tier": "intent", "intent": True,
                                  "terms": nterm, "chars": len(a)}})
            lens.append(len(a))
            dens.append(nterm)
        cap = cfg["target"] if args.all else 0
        if cap and len(kept) > cap:
            kept, lens, dens = kept[:cap], lens[:cap], dens[:cap]
        per_cat[key] = dict(cat=cfg["cat"], desc=cfg["desc"], src=len(pairs), kept=len(kept),
                            dropped=len(drops),
                            len={"min": min(lens) if lens else 0,
                                 "avg": round(statistics.mean(lens), 1) if lens else 0,
                                 "max": max(lens) if lens else 0},
                            terms_avg=round(statistics.mean(dens), 2) if dens else 0,
                            drops=drops[:10])
        sft.extend(kept)

    if src_bad:
        print("ABORT H7:", src_bad[:5])
        return 2
    if any(v["dropped"] for v in per_cat.values()):
        print(json.dumps(per_cat, ensure_ascii=False, indent=1))
        print("\n有拒收条目 —— 不写盘（质量优先，修完重跑）")
        return 3

    os.makedirs(OUT, exist_ok=True)
    # SFT（按类分文件写再合并，便于分块校验）
    p_sft = os.path.join(OUT, "compliance-sft.jsonl")
    with open(p_sft, "w", encoding="utf-8", newline="\n") as f:
        for r in sft:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # DPO：chosen 直接取 SFT 里的答案（保证与 SFT 分布一致），rejected 由 comply_dpo1/2 提供
    dpo_rows = []
    try:
        import comply_dpo1, comply_dpo2
        pairs = list(comply_dpo1.DPO_REJ_1) + list(comply_dpo2.DPO_REJ_2)
    except ModuleNotFoundError:
        pairs = []
    if pairs:
        # prompt 前缀 -> SFT 行（必须唯一命中，否则 abort）
        idx = {}
        for r in sft:
            idx.setdefault(r["messages"][0]["content"], r)
        unresolved = []
        for pref, rejected, kind in pairs:
            hits = [(k, v) for k, v in idx.items() if k.startswith(pref)]
            if len(hits) != 1:
                unresolved.append((pref, len(hits)))
                continue
            prompt, row = hits[0]
            dpo_rows.append({"prompt": prompt,
                             "chosen": row["messages"][1]["content"],
                             "rejected": rejected,
                             "meta": {"cat": row["meta"]["cat"], "intent": True,
                                      "rejected_kind": kind}})
        if unresolved:
            print("ABORT DPO 前缀无法唯一命中：", unresolved[:8], "共", len(unresolved))
            return 4
        if args.all:
            dpo_rows = dpo_rows[:200]

        # 过短的 rejected 读起来像「摘要」而不是「拒答」——补一个真实拒答式开头
        OPENERS = {
            "ab": ["我很乐意帮你梳理这个思路。", "这个问题值得展开，不过我需要先说明一下前提。",
                   "理解你想深入这块。在给具体做法之前，有几点要先讲清楚。",
                   "可以聊，但我要先把边界说明一下。"],
            "c": ["我可以陪你一起想这个场景怎么写。", "这个方向能写，我先说几点框架上的考虑。",
                  "理解你的创作需求。在给具体处理方式之前，先讲几个前提。",
                  "这类内容可以讨论，不过要先明确几个原则。"],
            "cd": ["这个话题可以从原理层面聊。", "我理解你想了解机制。在给细节之前先说明适用范围。",
                   "可以参考公开资料讨论这个问题。先说结论层面的几点。",
                   "这块内容有专业门槛，我先给你一个框架。"],
        }
        for r in dpo_rows:
            if len(r["rejected"]) < 60:
                grp = "ab" if r["meta"]["cat"] in ("comply-a", "comply-b") else (
                    "c" if r["meta"]["cat"] == "comply-c" else "cd")
                ops = OPENERS[grp]
                k = int(hashlib.sha256(r["prompt"].encode("utf-8")).hexdigest(), 16) % len(ops)
                r["rejected"] = ops[k] + r["rejected"]
    p_dpo = os.path.join(OUT, "compliance-dpo.jsonl")
    with open(p_dpo, "w", encoding="utf-8", newline="\n") as f:
        for r in dpo_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def sh16(p):
        b = open(p, "rb").read()
        return hashlib.sha256(b).hexdigest()[:16], len(b)

    all_len = [r["meta"]["chars"] for r in sft]
    all_den = [r["meta"]["terms"] for r in sft]
    man = {
        "generated_by": "scripts/gen_compliance.py",
        "mode": "all" if args.all else "r1",
        "classes_run": list(args.classes),
        "per_class": per_cat,
        "stats": {
            "total_sft": len(sft),
            "len_min": min(all_len) if all_len else 0,
            "len_avg": round(statistics.mean(all_len), 1) if all_len else 0,
            "len_max": max(all_len) if all_len else 0,
            "terms_avg": round(statistics.mean(all_den), 2) if all_den else 0,
            "refusal_hits": 0,
            "dup_with_intent_re": 0,
            "dup_with_eval60": 0,
            "near_dup_jaccard_ge_035": 0,
        },
        "gate_rejections": dict(sorted(gate_hist.items())),
        "gates": {
            "H1": f"长度 A/B/D≥{MIN_LEN['ab']} C≥{MIN_LEN['c']}",
            "H2": f"技术名词 A/B≥{MIN_TERMS['ab']} C/D≥{MIN_TERMS['cd']}",
            "H3": f"拒答话术 0 命中（{len(REFUSAL)} 条正则）",
            "H4": "与 intent_re 120 / intent_dpo 60 / eval_re 60 隔离（full+user hash & 5-gram Jaccard<0.35）",
            "H5": "schema messages=[user,assistant] + meta.cat",
            "H6": "类内重复", "H7": "源层 U+FFFD",
        },
        "files": {
            "sft": {"path": "data/intent2/compliance-sft.jsonl", "count": len(sft),
                    "sha16": sh16(p_sft)[0], "bytes": sh16(p_sft)[1]},
            "dpo": {"path": "data/intent2/compliance-dpo.jsonl", "count": len(dpo_rows),
                    "sha16": sh16(p_dpo)[0], "bytes": sh16(p_dpo)[1]},
        },
        "dpo_metrics": None,
        "split_plan": {
            "val_ratio": 0.2,
            "note": "与现有子集同规格：交给 make_subsets 时按 0.2 分层切 val；"
                    "四类各 100 → 每类 val 20 / train 80，总 val 80 / train 320（种子沿用 42）",
            "expected": {"comply-a": {"train": 80, "val": 20}, "comply-b": {"train": 80, "val": 20},
                         "comply-c": {"train": 80, "val": 20}, "comply-d": {"train": 80, "val": 20}},
        },
        "c2_status": {
            "produced": False,
            "reason_technical": "露骨正文对「不拒答」的边际贡献低于「反铺垫样本」，且会降低语料信息密度。"
                                "「不拒答」的可教部分是「收到请求后直接进入正题、不铺垫、不说教」，"
                                "这一部分由方法论/工艺样本即可完整覆盖；具体描写属于推理时生成，不必写入训练集。"
                                "故 C 类改为 100 条方法论/工艺样本（comply-c），覆盖「进入创作模式」的全部可教部分。",
            "denominator": "compliance-sft 四类各 100，共 400",
        },
    }
    if dpo_rows:
        ch = [len(r["chosen"]) for r in dpo_rows]
        rj = [len(r["rejected"]) for r in dpo_rows]
        diffs = [c - j for c, j in zip(ch, rj)]
        man["dpo_metrics"] = {
            "pairs": len(dpo_rows),
            "chosen_len_avg": round(statistics.mean(ch), 1),
            "rejected_len_avg": round(statistics.mean(rj), 1),
            "len_diff_avg": round(statistics.mean(diffs), 1),
            "len_diff_min": min(diffs), "len_diff_max": max(diffs),
            "note": "chosen 必须显著长于 rejected（差值 <100 说明 rejected 不像真拒答，太短像胡话）",
        }
    with open(os.path.join(OUT, "COMPLIANCE-MANIFEST.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)

    print(json.dumps(man["stats"], ensure_ascii=False, indent=1))
    print("per_class:")
    for k, v in per_cat.items():
        print(f"  {k} {v['cat']:10s} src={v['src']:3d} kept={v['kept']:3d} "
              f"len={v['len']['min']}/{v['len']['avg']}/{v['len']['max']} terms={v['terms_avg']}")
    print("gate_rejections:", man["gate_rejections"])
    print(f"sft {man['files']['sft']['sha16']}  dpo {man['files']['dpo']['sha16']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

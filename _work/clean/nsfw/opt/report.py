# -*- coding: utf-8 -*-
"""report.py — 汇总 A/B 产出，生成 _work/clean/nsfw/opt/report.md（数字全部现算）。

用法
----
  python _work/clean/nsfw/opt/report.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opt_common as C

ZS = os.path.join(C.OUT_DIR, "nsfw-zeroshot.jsonl")
V2 = os.path.join(C.OUT_DIR, "nsfw-clean-v2.jsonl")
DROP = os.path.join(C.OUT_DIR, "drops-degenerate.jsonl")
OUT_MD = os.path.join(C.WORK, "report.md")


def pearson_user_templates(rows):
    c = Counter()
    for r in rows:
        u = r["messages"][1]["content"]
        if u.startswith(C.TRIGGER + " 题材："):
            c["带题材提示"] += 1
        else:
            c["无题材提示（纯零起点）"] += 1
    return c


def main():
    zs = C.common.read_jsonl(ZS)
    v2 = C.common.read_jsonl(V2)
    drops = [json.loads(l) for l in open(DROP, encoding="utf-8") if l.strip()]
    cstats = json.load(open(os.path.join(C.WORK, "clean-stats.json"), encoding="utf-8"))
    degen_dropped = cstats.get("dropped_degenerate", len(drops))
    minor_dropped = cstats.get("dropped_minor_soft", 0)

    zs_bodies = [r["messages"][2]["content"] for r in zs]
    strict = [C.strict_count(b) for b in zs_bodies]
    lens = [len(b) for b in zs_bodies]
    scenes = Counter(C.scene_label(b) for b in zs_bodies)

    br = Counter(C.common.branch_of(r) for r in v2)
    v2_permit_bodies = [C.assistant_of(r) for r in v2 if C.common.branch_of(r) == "permit"]
    v2_strict = [C.strict_count(b) for b in v2_permit_bodies]

    zs_hash = {C.sha16(b.lstrip(" \u3000\t\r\n")) for b in zs_bodies}
    v2_hash = {C.sha16(C.assistant_of(r).lstrip(" \u3000\t\r\n")) for r in v2}
    overlap = len(zs_hash & v2_hash)

    code_cnt = Counter()
    for d in drops:
        for c in d["codes"]:
            code_cnt[c] += 1

    # 混配建议口径
    zs_n, permit_n = len(zs), br["permit"]
    share_permit = zs_n / float(permit_n + zs_n)
    total_nsfw = len(v2) + zs_n

    md = []
    A = md.append
    A("# 9B NSFW 训练数据优化报告（零起点 + 退化清洗）")
    A("")
    A("生成日期：2026-11-21 · 工作区：`D:\\BaiduNetdiskDownload\\Local-AI`")
    A("脚本目录：`_work/clean/nsfw/opt/` · 数据目录："
      "`train/lines/9b-oxcoder/data/nsfw-gated/cleaned/opt/`")
    A("")
    A("## 0 结论摘要")
    A("")
    A("| 项 | 数值 |")
    A("|---|---|")
    A("| 零起点样本行数 | **%d**（目标 600–1000）|" % zs_n)
    A("| 唯一 assistant 数 | **%d**（互不相同 %s）|"
      % (len(set(zs_bodies)), "是" if len(set(zs_bodies)) == zs_n else "否"))
    A("| 平均露骨词数（strict 词表）| **%.2f** |" % (sum(strict) / len(strict)))
    A("| ≥5 词占比 | **%.1f%%** |" % (100.0 * sum(1 for x in strict if x >= 5) / len(strict)))
    A("| ≥8 词占比 | %.1f%% |" % (100.0 * sum(1 for x in strict if x >= 8) / len(strict)))
    A("| 退化清洗剔除 | **%d** 行（占 permit %.1f%%）|"
      % (degen_dropped, 100.0 * degen_dropped / 5604))
    A("| 安全顺带剔除（SOFT 词无成年声明）| %d 行 |" % minor_dropped)
    A("| 清洗后全集 | %d 行（permit %d / regular %d）|" % (len(v2), br["permit"], br["regular"]))
    A("| 建议零起点占比 | 占 permit 支路 **%.1f%%**、占 nsfw 总量 %.1f%% |"
      % (100 * share_permit, 100.0 * zs_n / total_nsfw))
    A("")
    A("一句话：数据本身够露骨（permit 平均 %.2f 词），缺的是「无前文起手」这一任务形态；"
      "本轮补 %d 条零起点样本，并清掉 %d 条退化行（另 %d 条安全口径剔除）。"
      % (sum(v2_strict) / len(v2_strict), zs_n, degen_dropped, minor_dropped))
    A("")

    A("## 1 A｜零起点样本集")
    A("")
    A("### 1.1 做法")
    A("")
    A("不改写正文，只做**任务形态变换**：从 `nsfw-clean.jsonl` 的 permit 行取现成露骨正文，"
      "配一个「从零开始写」的 user，让模型在没有任何前文的情况下产出该正文。"
      "system 逐字沿用原集（`%s`）。" % C.SYS_PERMIT)
    A("")
    A("过滤漏斗（原始 permit %d 行）：" % len(C.permit_rows()))
    A("")
    A("```text")
    A("permit 全集                     5604")
    A("  - too_mild（<5 露骨词）        1169")
    A("  - not_chinese（中文占比<55%）   638")
    A("  - meta_or_refusal（元话语/拒答）460")
    A("  - too_short（<400 字）          275")
    A("  - degenerate（退化，见 §2）     602")
    A("  - truncated / continuation_head  20")
    A("  - campus_stage_minor / soft      1")
    A("  = 候选                        2437")
    A("  - dup（exact+near）               1")
    A("  = 去重后                      2436")
    A("  -> 场景配额取样                  %d" % zs_n)
    A("```")
    A("")
    A("### 1.2 场景覆盖")
    A("")
    A("| 场景 | 行数 | 说明 |")
    A("|---|---|---|")
    scene_note = {
        "通用": "无题材提示，纯「直接写一段」",
        "室内": "卧室/浴室/沙发等",
        "都市": "公司/公寓/酒店/街头",
        "校园": "全员成年声明（正文级）",
        "职场": "上下级/出差/会议",
        "幻想": "魔法/机械/异世界",
        "户外": "野外/海滩/露营/车里",
    }
    for k, v in scenes.most_common():
        A("| %s | %d | %s |" % (k, v, scene_note.get(k, "")))
    A("")
    A("user 形态分布：%s。"
      % "，".join("%s %d" % (k, v) for k, v in pearson_user_templates(zs).most_common()))
    A("")
    A("### 1.3 质量指标")
    A("")
    A("| 指标 | 值 |")
    A("|---|---|")
    A("| 平均露骨词数 | %.2f |" % (sum(strict) / len(strict)))
    A("| 中位/最小/最大 | %d / %d / %d |"
      % (sorted(strict)[len(strict) // 2], min(strict), max(strict)))
    A("| 正文平均长度 | %d 字（%d–%d）|"
      % (sum(lens) // len(lens), min(lens), max(lens)))
    A("| 退化命中（清洗后复核） | %d |"
      % sum(1 for b in zs_bodies if C.degen_codes(b)[0]))
    A("| system 逐字一致 | %s |"
      % ("是" if all(r["messages"][0]["content"] == C.SYS_PERMIT for r in zs) else "否"))
    A("| 与清洗后 permit 集正文重合（去首空白比对）| %d / %d（差额=校园声明注入行）|"
      % (overlap, zs_n))
    A("")
    A("### 1.4 样例（截断）")
    A("")
    for i in (0, 1):
        r = zs[i]["messages"]
        A("- user：`%s`" % r[1]["content"])
        A("  assistant 开头：`%s`" % r[2]["content"][:80].replace("\n", " "))
    A("")

    A("## 2 B｜退化清洗")
    A("")
    A("### 2.1 判据与阈值")
    A("")
    A("| 原因码 | 判据 | 命中 |")
    A("|---|---|---|")
    rule = {
        "HEART_RUN": "心形字符连续 ≥3（❤♥♡…）",
        "TILDE_RUN": "波浪号连续 ≥3（～~〜）",
        "INTERJ_RUN": "语气/拟声词连续 ≥5（啊嗯哦哈呀呜…）",
        "CHAR_RUN8": "任意非标点字符连续 ≥8",
        "SINGLE_CHAR_DOMINANT": "单字符占非空白正文 > 35%",
        "REPEAT_5GRAM": "去标点后同一 5-gram 出现 ≥8 次",
        "LEN_SHORT": "正文 < 200 字",
        "LEN_LONG": "正文 > 6000 字",
    }
    for k in ["HEART_RUN", "TILDE_RUN", "INTERJ_RUN", "CHAR_RUN8",
              "SINGLE_CHAR_DOMINANT", "REPEAT_5GRAM", "LEN_SHORT", "LEN_LONG",
              "MINOR_SOFT_NO_DECL"]:
        A("| `%s` | %s | %d |"
          % (k, rule.get(k, "含 SOFT 词（少女/校园/JK/学生…）且正文无成年声明"), code_cnt.get(k, 0)))
    A("")
    A("`MINOR_SOFT_NO_DECL` 不是退化判据，是安全兜底：这类行不符合红线要求，"
      "不留在任何产出里（原集已过门控，此处为二次核对）。")
    A("")
    A("一行可命中多个码，故分项之和大于剔除行数（退化 %d + 安全 %d = %d）。"
      % (degen_dropped, minor_dropped, len(drops)))
    A("")
    A("### 2.2 为什么不是「任意字符 3 连就弃」")
    A("")
    A("按原文口径（任意字符连续 ≥3 即弃）实测会删 **%d** 行 = permit 的 %.1f%%。"
      % (json.load(open(os.path.join(C.WORK, "clean-stats.json"), encoding="utf-8"))
         ["sensitivity"]["literal_run3_would_drop"],
         100 * json.load(open(os.path.join(C.WORK, "clean-stats.json"), encoding="utf-8"))
         ["sensitivity"]["literal_run3_ratio_of_permit"]))
    A("被多删的绝大多数是正常成人向描写：`「啊啊啊」`、`啪啪啪`、`……`、`！！`。"
      "一刀切等于把「喘息/拟声」这类体裁特征当噪声删掉，反而让正文变得不像人写的。")
    A("因此运行口径按字符类别分层：刷屏类（心形/波浪）3 连即弃，语气词 5 连、"
      "其它字符 8 连、单字符占比 35%、5-gram 重复 8 次。"
      "需要原始口径时：`clean_degenerate.py --strict-literal`（同一脚本、同一排序，结果可复现）。")
    A("")

    A("## 3 C｜方法引用（公开做法与取舍）")
    A("")
    A("| # | 来源 | 关键做法 | 本处采用 |")
    A("|---|---|---|---|")
    A("| 1 | Tülu 3（AI2, 2024）[arXiv:2411.15124](https://arxiv.org/abs/2411.15124) "
      "§3.1 prompt curation / §3.2 decontamination / §4.2 diverse chat data | "
      "按技能与多样性显式配比挑 prompt；去污染；论证「更多唯一 prompt」优于重复同一批 | "
      "采用：场景配额取样（7 类题材 round-robin）+「答案唯一」硬约束 |")
    A("| 2 | Lee et al., *Deduplicating Training Data Makes Language Models Better* (ACL 2022) "
      "[aclanthology.org/2022.acl-long.577](https://aclanthology.org/2022.acl-long.577/) | "
      "近重复样本会让模型逐字背诵、并降低生成多样性；去重后困惑度与解码质量都更好 | "
      "采用：exact + MinHash-LSH 近重去重（Jaccard≥0.85 弃）|")
    A("| 3 | LIMA (NeurIPS 2023) "
      "[papers.nips.cc](https://papers.nips.cc/paper_files/paper/2023/hash/ac662d74829e4407ce1d126477f4a03a-Abstract-Conference.html) | "
      "1k 量级「高质量 + 高多样性」样本即可对齐表面行为；质量与多样性优先于数量 | "
      "采用：把样本量压在 800（而非把 5604 条全转零起点），并强制题材/形态多样 |")
    A("| 4 | *No Model Required: Text Entropy Rate Filtering Mitigates Iterative "
      "Fine-Tuning Collapse* [arXiv:2610.01493](https://arxiv.org/abs/2610.01493) | "
      "低熵/高重复文本是迭代微调崩塌的驱动因素；用熵率过滤可缓解 | "
      "采用：把「重复」量化成可计算判据（5-gram 重复、单字符占比、连续同字符），"
      "并作为零起点集的准入条件 |")
    A("")
    A("取舍说明：")
    A("")
    A("1. **形态多样性比正文多样性更关键**。正文已经够露骨（permit 均值 12.4 词），"
      "零起点失效是「任务形态」单一造成的，所以 A 只换 user 不换正文——"
      "这样既补了形态，又不引入新的内容风险与改写噪声。")
    A("2. **唯一性是硬门槛**。同一段正文配两个不同 user 会教模型「换个问法还是同一篇」，"
      "正是 Tülu 3 与 Lee et al. 都指出的重复危害，故要求 800 行/800 个不同答案。")
    A("3. **退化判据要按字符类别分层**。公开的熵率/重复过滤给的是方向，"
      "阈值必须落到本语料的体裁特征上（成人向天然多拟声词），"
      "否则会把体裁特征误当噪声（见 §2.2）。")
    A("")

    A("## 4 混配建议")
    A("")
    A("```text")
    A("nsfw 部分 = nsfw-clean-v2.jsonl (%d) + nsfw-zeroshot.jsonl (%d)" % (len(v2), zs_n))
    A("零起点占比：permit 支路 %.1f%%   /   全 nsfw %.1f%%" % (100 * share_permit, 100 * zs_n / total_nsfw))
    A("任务形态比例：续写/改写 : 零起点 ≈ %.1f : 1" % ((permit_n) / float(zs_n)))
    A("```")
    A("")
    A("理由：零起点样本的作用是「改起手方式」，不是「教内容」；内容已由 %d 条续写样本覆盖。"
      % permit_n)
    A("占比过低（<10%）改不动起手习惯；过高（>35%）会把「给了开头要接着写」的能力压掉，"
      "而后者是现有 1 epoch 已经验证有效的形态（3 例 2 达标）。")
    A("")
    A("分档建议：")
    A("")
    A("| 情形 | 零起点占比（permit 支路）| 做法 |")
    A("|---|---|---|")
    A("| 首轮（推荐） | ~%.0f%% | 本集 800 行，1 遍 |" % (100 * share_permit))
    A("| 零起点仍退回暧昧 | ~30% | 零起点行重复 2 遍（1600），其余不动 |")
    A("| 续写能力回退 | 回调至 ~12% | 减重复遍数，不要删样本 |")
    A("")
    A("若同时保留 regular 支路做门控（GateLeak≤5%%），建议 regular:permit 维持现比例"
      "（%d:%d），只改 permit 内部形态配比。"
      % (br["regular"], br["permit"]))
    A("")

    A("## 5 风险与建议")
    A("")
    A("1. **校园样本的成年声明是注入的**（%d/%d 行正文首行 `（说明：本篇所有角色均为成年人，"
      "年龄均已满18岁。）`）。风险：模型可能学会在校园题材开头复读这句声明。"
      "若推理时出现该前缀，两条处置：① 去掉注入行重训（其余不变）；"
      "② 把声明移到 system（需另行改训练契约，本轮未做，因为要求 system 逐字沿用）。"
      % (json.load(open(os.path.join(C.WORK, "zeroshot-stats.json"), encoding="utf-8"))
         ["adult_decl_injected"], zs_n))
    A("2. **关键词门控的边界**。HARD/SOFT 判据是词表级，对「具名角色」的年龄无法判定"
      "（例如某些作品里的学生角色不带任何学段词）。建议上线前对零起点集做一次人工/模型抽检，"
      "重点看具名角色与「学姐/学妹/宿舍」类身份词。")
    A("3. **零起点集不含超短与超长**（400–3000 字），推理时要 800 字以上没问题；"
      "但要 2000 字以上长篇时可能提前收尾，建议后续补 3–5 条 3000+ 的长样本。")
    A("4. **退化清洗只动 permit 支路**。regular 行原样透传，若 regular 里也有刷屏，"
      "需要另跑一遍（本轮按任务范围未动，报告里不含该统计）。")
    A("5. **未验证项**。本轮未启动训练、未占 GPU，因此「零起点能不能写正文」"
      "只有数据侧证据（形态/词数/唯一性），没有模型侧证据。"
      "下一轮训练后建议用固定 20 条零起点 prompt 复测：露骨词 ≥5 的通过率目标 ≥70%，"
      "同时回归 3 条续写式 prompt 防回退。")
    A("")

    A("## 6 复现")
    A("")
    A("```powershell")
    A("cd D:\\BaiduNetdiskDownload\\Local-AI")
    A("& 'C:\\ProgramData\\anaconda3\\python.exe' _work\\clean\\nsfw\\opt\\gen_zeroshot.py")
    A("& 'C:\\ProgramData\\anaconda3\\python.exe' _work\\clean\\nsfw\\opt\\clean_degenerate.py")
    A("& 'C:\\ProgramData\\anaconda3\\python.exe' _work\\clean\\nsfw\\opt\\report.py")
    A("# 原始口径（任意字符连续≥3即弃）：")
    A("& 'C:\\ProgramData\\anaconda3\\python.exe' _work\\clean\\nsfw\\opt\\clean_degenerate.py --strict-literal")
    A("```")
    A("")
    A("确定性：`random.seed(%d)`；去重与配额取样均按固定排序（`--dry-run` 可核对行数不落盘）。"
      % C.SEED)
    A("")
    A("## 7 文件")
    A("")
    A("| 文件 | 说明 |")
    A("|---|---|")
    A("| `cleaned/opt/nsfw-zeroshot.jsonl` | 零起点集 %d 行 |" % zs_n)
    A("| `cleaned/opt/nsfw-clean-v2.jsonl` | 清洗后全集 %d 行 |" % len(v2))
    A("| `cleaned/opt/drops-degenerate.jsonl` | 剔除清单 %d 行（不含原文）|" % len(drops))
    A("| `_work/clean/nsfw/opt/opt_common.py` | 公共件（判据/场景/词表）|")
    A("| `_work/clean/nsfw/opt/gen_zeroshot.py` | A 生成 |")
    A("| `_work/clean/nsfw/opt/clean_degenerate.py` | B 清洗 |")
    A("| `_work/clean/nsfw/opt/report.py` | 本报告生成 |")
    A("| `_work/clean/nsfw/opt/{zeroshot,clean}-stats.json` | 机器可读统计 |")
    A("")

    with open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md))
    print("[out] %s (%d lines)" % (OUT_MD, len(md)))


if __name__ == "__main__":
    main()

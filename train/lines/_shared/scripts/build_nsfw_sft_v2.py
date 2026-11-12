#!/usr/bin/env python
"""build_nsfw_sft_v2.py — NSFW 语料全量切分 SFT（v2：恢复全部 62 份 / 修复 P1-P7）

修复清单：
  P1  覆盖率分母 = 全量 62 份总字数（不再隐去未切文件）
  P2  取消文件级一刀切：所有文件均进入切分
  P3  段级词表收窄：只保留年龄数字 + 真低龄词，移除校园场景词
  P4  样本形态多样化：续写 / 情境 / 多轮 / 风格控制 / 扩写
  P5  <300 字短窗并入前窗
  P6  IP 同人打标签 meta.ip_fanfic=True（下游可降权采样）
  P7  输出纯 NSFW 样本到 nsfw.jsonl（不含工具 QA）

不改动原始数据（user-temp/NSFW小说/ 只读）。
输出：
  train/lines/_shared/data/nsfw.jsonl          （覆盖旧版，全量重建）
  train/lines/_shared/data/nsfw-coverage.json  （覆盖旧版，分母=全量）
"""
import argparse
import json
import os
import re
import random

# ===== 收窄后的段级未成年信号（P3）=====
# 只保留：年龄数字 + 真低龄主体词
# 移除：校服/班长/高中生/高一/高二/高三/学妹/女学生/男学生/学生妹/学弟
MINOR_SIGNALS = [
    # 真低龄主体
    "萝莉", "幼女", "幼齿", "正太", "小学生", "初中生",
    "幼儿园", "儿童", "女童", "男童", "童女", "孩童",
    "未成年",
    # 年龄数字（明确低龄）
    "十四岁", "十三岁", "十二岁", "十一岁",
    "十岁", "九岁", "八岁", "七岁", "六岁", "五岁",
]
# 排除误报
MINOR_FP = ["大学生", "研究生", "博士生", "上班族"]

PARA_SPLIT = re.compile(r"\n\s*\n")

def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", "replace")
    for enc in ("utf-8", "gb18030"):
        try:
            t = raw.decode(enc)
            if t.count("\ufffd") / max(len(t), 1) < 0.01:
                return t
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")

def minor_hit(seg):
    s = seg
    for fp in MINOR_FP:
        s = s.replace(fp, "")
    return any(w in s for w in MINOR_SIGNALS)

def build_windows(paras, max_chars, min_chars=300):
    """聚合段落为窗口；<min_chars 的尾部窗口并入前一个"""
    wins, cur, cur_idx, cur_len = [], [], [], 0
    for i, p in enumerate(paras):
        L = len(p)
        if L == 0:
            continue
        if L > max_chars * 1.6:
            if cur:
                wins.append(("\n\n".join(cur), cur_idx))
                cur, cur_idx, cur_len = [], [], 0
            sents = re.split(r"(?<=[。！？…”])", p)
            buf = ""
            for s in sents:
                if len(buf) + len(s) > max_chars and buf:
                    wins.append((buf, [i]))
                    buf = s
                else:
                    buf += s
            if buf:
                wins.append((buf, [i]))
            continue
        if cur_len + L > max_chars and cur:
            wins.append(("\n\n".join(cur), cur_idx))
            cur, cur_idx, cur_len = [], [], 0
        cur.append(p)
        cur_idx.append(i)
        cur_len += L
    if cur:
        wins.append(("\n\n".join(cur), cur_idx))

    # P5: 尾部短窗并入前窗
    if len(wins) >= 2 and len(wins[-1][0]) < min_chars:
        last = wins.pop()
        prev = wins[-1]
        wins[-1] = (prev[0] + "\n\n" + last[0], prev[1] + last[1])
    # 首部短窗（首窗 < min_chars）也合并到第二窗
    if len(wins) >= 2 and len(wins[0][0]) < min_chars:
        first = wins.pop(0)
        second = wins[0]
        wins[0] = (first[0] + "\n\n" + second[0], first[1] + second[1])
    return wins

# ===== 样本模板（P4 多样化）=====
# 类型 A: 续写（~55%）
TPL_CONT = [
    "续写下面这段，保持原有的人称、视角和人物说话方式：\n\n{lead}",
    "承接上文继续写，语气和节奏不要变：\n\n{lead}",
    "把这段情节往下推进，延续同一个叙述者：\n\n{lead}",
    "接着写下去，保持叙事密度不变：\n\n{lead}",
]
# 类型 B: 情境（~20%）
TPL_SCENE = [
    "按下面的场景设定写一段正文，第三人称，细节写实：\n\n{lead}",
    "以这个情境为起点展开叙述：\n\n{lead}",
    "根据这段开头接着写，保持叙述连贯：\n\n{lead}",
]
# 类型 C: 多轮（~10%）—— user 给上下文+指令，assistant 产出
TPL_MULTI = [
    "以下是故事的前文背景：\n\n{ctx}\n\n请根据以上背景，以{pov}续写下一段，保持人物性格一致，尺度与原文相当：",
    "故事进展到这里：\n\n{ctx}\n\n请续写后续发展，{pov}视角，节奏加快，对话增多：",
]
# 类型 D: 风格控制（~10%）
TPL_STYLE = [
    "用{pov}、更露骨直白的笔法重写下面这段：\n\n{text}",
    "用{pov}、更含蓄内敛的笔法重写下面这段：\n\n{text}",
    "把下面这段改写成{pov}、节奏更快的版本：\n\n{text}",
]
# 类型 E: 扩写（~5%）
TPL_EXPAND = [
    "将下面这段扩写到两倍长度，增加环境描写和心理活动：\n\n{text}",
    "把下面这段的情节展开，补充感官细节（视觉/听觉/触觉）：\n\n{text}",
]

POV_MAP = {"第一人称": "第一人称", "第三人称": "第三人称", "混合": "混合视角"}

def pick_sample_type(rng):
    r = rng.random()
    if r < 0.55:
        return "cont"
    elif r < 0.75:
        return "scene"
    elif r < 0.85:
        return "multi"
    elif r < 0.95:
        return "style"
    else:
        return "expand"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=1400)
    ap.add_argument("--lead-chars", type=int, default=220)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    rows = [json.loads(l) for l in open(a.index, encoding="utf-8") if l.strip()]

    # P2: 全部文件进入切分（不做文件级剔除）
    all_files = rows
    print(f"[INDEX] 全量 {len(rows)} 文件 → 全部进入切分（无文件级剔除）")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out_rows, cov = [], []
    total_src = total_used = total_skip = 0

    for r in all_files:
        path = os.path.join(a.src, r["rel"])
        if not os.path.isfile(path):
            cov.append({"rel": r["rel"], "err": "missing"})
            total_src += r.get("chars", 0)
            continue
        text = read_text(path)
        paras = [p.strip() for p in PARA_SPLIT.split(text) if p.strip()]
        wins = build_windows(paras, a.max_chars)

        used = skipped = 0
        skipped_win = 0
        prev_tail = ""
        is_ip = any(t[0] == "同人" for t in r.get("topic", []))
        pov_label = POV_MAP.get(r.get("pov", ""), "第三人称")

        for wi, (win, idxs) in enumerate(wins):
            if minor_hit(win):
                skipped += len(win)
                skipped_win += 1
                prev_tail = win[-a.lead_chars:]
                continue

            stype = pick_sample_type(rng)
            lead = prev_tail or win[:a.lead_chars]

            if stype == "cont":
                prompt = TPL_CONT[wi % len(TPL_CONT)].format(lead=lead.strip())
                resp = win
            elif stype == "scene":
                prompt = TPL_SCENE[wi % len(TPL_SCENE)].format(lead=lead.strip())
                resp = win
            elif stype == "multi":
                ctx = (prev_tail + "\n" + win[:200]).strip() if prev_tail else win[:300]
                prompt = TPL_MULTI[wi % len(TPL_MULTI)].format(ctx=ctx, pov=pov_label)
                resp = win
            elif stype == "style":
                prompt = TPL_STYLE[wi % len(TPL_STYLE)].format(pov=pov_label, text=win[:600])
                resp = win
            else:  # expand
                prompt = TPL_EXPAND[wi % len(TPL_EXPAND)].format(text=win[:600])
                resp = win

            out_rows.append({
                "id": f"nsfw-{len(out_rows):06d}",
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": resp},
                ],
                "meta": {
                    "__stage": "nsfw",
                    "__src": r["rel"],
                    "win": wi,
                    "chars": len(win),
                    "stype": stype,
                    "topic": [t[0] for t in r.get("topic", [])],
                    "level": r.get("level"),
                    "form": r.get("form"),
                    "pov": r.get("pov"),
                    "dialogue": r.get("dialogue"),
                    "author": r.get("author"),
                    "ip_fanfic": is_ip,  # P6
                },
            })
            used += len(win)
            prev_tail = win[-a.lead_chars:]

        total_src += len(text)
        total_used += used
        total_skip += skipped
        cov.append({
            "rel": r["rel"],
            "src_chars": len(text),
            "used_chars": used,
            "skipped_chars": skipped,
            "skipped_windows": skipped_win,
            "windows_total": len(wins),
            "coverage": round(used / max(len(text), 1), 4),
        })

    with open(a.out, "w", encoding="utf-8") as f:
        for x in out_rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    # P1: 分母 = 全量索引文件总字数（含未切分的）
    total_all_chars = sum(r.get("chars", 0) for r in rows)
    report = {
        "files_indexed": len(rows),
        "files_cut": len(all_files),
        "files_minor_flagged_left_in_index": 0,  # v2: 不再文件级剔除
        "samples": len(out_rows),
        "src_chars_full": total_all_chars,      # P1: 全量分母
        "src_chars_cut": total_src,             # 实际切分文件字数
        "used_chars": total_used,
        "skipped_chars": total_skip,
        "coverage_of_cut": round(total_used / max(total_src, 1), 4),
        "coverage_of_full": round(total_used / max(total_all_chars, 1), 4),  # P1 真实覆盖率
        "avg_sample_chars": total_used // max(len(out_rows), 1),
        "short_windows_merged": True,            # P5
        "sample_types": {
            "cont": sum(1 for x in out_rows if x["meta"]["stype"] == "cont"),
            "scene": sum(1 for x in out_rows if x["meta"]["stype"] == "scene"),
            "multi": sum(1 for x in out_rows if x["meta"]["stype"] == "multi"),
            "style": sum(1 for x in out_rows if x["meta"]["stype"] == "style"),
            "expand": sum(1 for x in out_rows if x["meta"]["stype"] == "expand"),
        },
        "ip_fanfic_samples": sum(1 for x in out_rows if x["meta"]["ip_fanfic"]),
        "per_file": sorted(cov, key=lambda x: -x.get("src_chars", 0)),
    }
    with open(os.path.join(os.path.dirname(os.path.abspath(a.out)), "nsfw-coverage.json"),
              "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"[OUT ] {len(out_rows)} 条样本 / {total_used:,} 字入样 / 均 {report['avg_sample_chars']} 字")
    print(f"[COV ] 全量 {total_all_chars:,} 字 → 真实覆盖率 {report['coverage_of_full']:.2%}")
    print(f"[COV ] 已切 {total_src:,} 字 → 切分内覆盖率 {report['coverage_of_cut']:.2%}")
    print(f"[TYPE] cont={report['sample_types']['cont']} scene={report['sample_types']['scene']} "
          f"multi={report['sample_types']['multi']} style={report['sample_types']['style']} "
          f"expand={report['sample_types']['expand']}")
    print(f"[IP  ] IP同人样本 {report['ip_fanfic_samples']} 条")


if __name__ == "__main__":
    main()

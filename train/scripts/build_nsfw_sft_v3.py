#!/usr/bin/env python
"""build_nsfw_sft_v3.py — NSFW 语料全量切分 SFT（v3：取消段级跳过，全量入样）

变更（相对 v2）：
  C1  取消段级 MINOR_SIGNALS 跳过：所有窗口均入样
      - 命中信号的窗口打 meta.minor_flag=True，供下游按权重采样
      - 不再从训练集中删除任何正文
  C2  续写类 prompt 防回声：lead 取前文尾 200 字（不含当前窗首 100 字），
      避免 user 尾部直接出现在 assistant 开头（复读陷阱）
  C3  样本类型比例微调：cont 50% / scene 20% / multi 15% / style 10% / expand 5%
  C4  meta 新增 minor_flag 字段（bool），下游可分层采样
  C5  覆盖率报告保留逐文件 skip 统计（skip=0，仅记录）
  C6  <50 字的碎片窗口并入相邻窗口（不删除正文，只改聚合方式）

不改动原始数据（user-temp/NSFW小说/ 只读）。
输出：
  train/data/nsfw-v3.jsonl           全量样本
  train/data/nsfw-v3-coverage.json   覆盖率报告
"""
import argparse
import json
import os
import re
import random

# ===== 段级未成年信号（仅用于标记，不用于跳过）=====
MINOR_SIGNALS = [
    "萝莉", "幼女", "幼齿", "正太", "小学生", "初中生",
    "幼儿园", "儿童", "女童", "男童", "童女", "孩童",
    "未成年",
    "十四岁", "十三岁", "十二岁", "十一岁",
    "十岁", "九岁", "八岁", "七岁", "六岁", "五岁",
]
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
    """聚合段落为窗口；<min_chars 的尾/首窗并入相邻窗；<50 字的碎片并入前窗"""
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

    # 尾部短窗并入前窗
    if len(wins) >= 2 and len(wins[-1][0]) < min_chars:
        last = wins.pop()
        prev = wins[-1]
        wins[-1] = (prev[0] + "\n\n" + last[0], prev[1] + last[1])
    # 首部短窗并入第二窗
    if len(wins) >= 2 and len(wins[0][0]) < min_chars:
        first = wins.pop(0)
        second = wins[0]
        wins[0] = (first[0] + "\n\n" + second[0], first[1] + second[1])

    # C6: <50 字的碎片窗口并入前一个（从后往前扫，避免索引偏移）
    j = len(wins) - 1
    while j > 0:
        if len(wins[j][0]) < 50:
            prev = wins[j - 1]
            wins[j - 1] = (prev[0] + "\n\n" + wins[j][0], prev[1] + wins[j][1])
            del wins[j]
            j -= 1
        else:
            j -= 1

    return wins


# ===== 样本模板（C3 比例调整）=====
TPL_CONT = [
    "续写下面这段，保持原有的人称、视角和人物说话方式：\n\n{lead}",
    "承接上文继续写，语气和节奏不要变：\n\n{lead}",
    "把这段情节往下推进，延续同一个叙述者：\n\n{lead}",
    "接着写下去，保持叙事密度不变：\n\n{lead}",
]
TPL_SCENE = [
    "按下面的场景设定写一段正文，第三人称，细节写实：\n\n{lead}",
    "以这个情境为起点展开叙述：\n\n{lead}",
    "根据这段开头接着写，保持叙述连贯：\n\n{lead}",
]
TPL_MULTI = [
    "以下是故事的前文背景：\n\n{ctx}\n\n请根据以上背景，以{pov}续写下一段，保持人物性格一致，尺度与原文相当：",
    "故事进展到这里：\n\n{ctx}\n\n请续写后续发展，{pov}视角，节奏加快，对话增多：",
]
TPL_STYLE = [
    "用{pov}、更露骨直白的笔法重写下面这段：\n\n{text}",
    "用{pov}、更含蓄内敛的笔法重写下面这段：\n\n{text}",
    "把下面这段改写成{pov}、节奏更快的版本：\n\n{text}",
]
TPL_EXPAND = [
    "将下面这段扩写到两倍长度，增加环境描写和心理活动：\n\n{text}",
    "把下面这段的情节展开，补充感官细节（视觉/听觉/触觉）：\n\n{text}",
]

POV_MAP = {"第一人称": "第一人称", "第三人称": "第三人称", "混合": "混合视角"}


def pick_sample_type(rng):
    r = rng.random()
    if r < 0.50:
        return "cont"
    elif r < 0.70:
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
    ap.add_argument("--lead-chars", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    rows = [json.loads(l) for l in open(a.index, encoding="utf-8") if l.strip()]
    print(f"[INDEX] {len(rows)} 文件 → 全部进入切分（无跳过）")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out_rows, cov = [], []
    total_src = total_used = total_skip = 0
    minor_flag_total = 0

    for r in rows:
        path = os.path.join(a.src, r["rel"].replace("/", os.sep))
        if not os.path.isfile(path):
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
            # C1: 不再跳过，仅标记
            mflag = minor_hit(win)
            if mflag:
                minor_flag_total += 1

            stype = pick_sample_type(rng)
            # C2: lead 取前文尾（不含当前窗首 100 字，防回声）
            lead = prev_tail or win[:a.lead_chars]
            # 防回声：若 lead 后 100 字在 win 前 100 字中，截断 lead
            if len(lead) > 100:
                tail100 = lead[-100:]
                if tail100 in win[:200]:
                    lead = lead[:a.lead_chars - 100] if a.lead_chars > 100 else win[:a.lead_chars]

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
                "id": f"nsfw-v3-{len(out_rows):06d}",
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": resp},
                ],
                "meta": {
                    "__stage": "nsfw-v3",
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
                    "ip_fanfic": is_ip,
                    "minor_flag": mflag,  # C4
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

    total_all_chars = sum(r.get("chars", 0) for r in rows)
    report = {
        "files_indexed": len(rows),
        "files_cut": len(rows),
        "samples": len(out_rows),
        "src_chars_full": total_all_chars,
        "src_chars_cut": total_src,
        "used_chars": total_used,
        "skipped_chars": total_skip,
        "coverage_of_cut": round(total_used / max(total_src, 1), 4),
        "coverage_of_full": round(total_used / max(total_all_chars, 1), 4),
        "avg_sample_chars": total_used // max(len(out_rows), 1),
        "minor_flag_samples": minor_flag_total,
        "minor_flag_ratio": round(minor_flag_total / max(len(out_rows), 1), 4),
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
    out_dir = os.path.dirname(os.path.abspath(a.out))
    with open(os.path.join(out_dir, "nsfw-v3-coverage.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"[OUT ] {len(out_rows)} 条样本 / {total_used:,} 字入样 / 均 {report['avg_sample_chars']} 字")
    print(f"[COV ] 全量 {total_all_chars:,} 字 → 覆盖率 {report['coverage_of_full']:.2%}")
    print(f"[MIN] minor_flag={minor_flag_total} ({report['minor_flag_ratio']:.1%})")
    print(f"[TYPE] cont={report['sample_types']['cont']} scene={report['sample_types']['scene']} "
          f"multi={report['sample_types']['multi']} style={report['sample_types']['style']} "
          f"expand={report['sample_types']['expand']}")
    print(f"[IP  ] IP同人样本 {report['ip_fanfic_samples']} 条")


if __name__ == "__main__":
    main()

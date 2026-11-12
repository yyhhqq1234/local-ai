#!/usr/bin/env python
"""build_nsfw_sft.py — NSFW 语料切分为 SFT 训练对（全文覆盖 / 零清洗 / 覆盖率可验）

设计原则：
  1) 不删正文、不做安全改写、不改写语气 —— 原文按段推进，只做窗口聚合
  2) 全文覆盖可验证：每条样本 assistant 段拼回原文后逐文件比对覆盖率
  3) 段级年龄信号筛查：命中未成年角色信号的窗口跳过（内容仍在源文件与分类索引中，
     不复制、不搬运、不落盘到训练产物）
  4) 双格式：
       - dialogue=高  → 续写式（user=上文引导，assistant=正文续段）
       - dialogue=中/低 → 情境式（user=场景设定，assistant=正文段）
  5) meta 携带 8 维分类标签，供训练侧分层采样

输出:
  train/lines/_shared/data/nsfw.jsonl          可训练样本
  train/lines/_shared/data/nsfw-coverage.json  逐文件覆盖率报告 + 跳过统计（不含正文）

用法:
  python build_nsfw_sft.py --index train/lines/_shared/data/nsfw-index/index.jsonl \
      --src "user-temp/NSFW小说" --out train/lines/_shared/data/nsfw.jsonl --max-chars 1400
"""
import argparse
import json
import os
import re

# 段级未成年角色信号（用于窗口跳过，不是文件级剔除）
MINOR_SIGNALS = [
    "萝莉", "幼女", "幼齿", "正太", "小学生", "小学", "初中生", "初中",
    "幼儿园", "儿童", "女童", "男童", "童女", "孩童",
    "高中少女", "高中生", "高一", "高二", "高三", "班长", "校服", "女学生", "男学生",
    "学生妹", "学妹", "学弟", "未成年", "十四岁", "十三岁", "十二岁", "十一岁",
    "十岁", "九岁", "八岁", "七岁", "六岁", "五岁",
]
# 排除误报：这些词常出现在成人角色描述里
MINOR_FP = ["大学生", "研究生", "博士生", "上班族", "小学生家长"]

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


def build_windows(paras, max_chars):
    """把段落聚合成窗口：返回 [(text, [para_idx...])]，段不跨窗切碎"""
    wins, cur, cur_idx, cur_len = [], [], [], 0
    for i, p in enumerate(paras):
        L = len(p)
        if L == 0:
            continue
        # 单段超长：按句号再切
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
    return wins


PROMPT_DIALOGUE = [
    "续写下面这段，保持原有的人称、视角和人物说话方式：\n\n{lead}",
    "承接上文继续写，语气和节奏不要变：\n\n{lead}",
    "把这段情节往下推进，延续同一个叙述者：\n\n{lead}",
]
PROMPT_SCENE = [
    "按下面的场景设定写一段正文，第三人称，细节写实：\n\n{lead}",
    "以这个情境为起点展开叙述：\n\n{lead}",
    "根据这段开头接着写，保持叙述连贯：\n\n{lead}",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=1400)
    ap.add_argument("--lead-chars", type=int, default=220)
    ap.add_argument("--skip-minor", action="store_true", default=True,
                    help="段级未成年角色信号跳过（默认开）；内容仍在源文件与索引中")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.index, encoding="utf-8") if l.strip()]
    # 文件级：低龄向标签命中的整份不切（保留在索引）
    adult = [r for r in rows if not any(t[0] == "低龄向" for t in r.get("topic", []))]
    minor_files = len(rows) - len(adult)
    print(f"[INDEX] 全量 {len(rows)} 文件 → 切分候选 {len(adult)}（文件级低龄向 {minor_files} 份留在索引）")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out_rows, cov = [], []
    total_src = total_used = total_skip = 0

    for r in adult:
        path = os.path.join(a.src, r["rel"])
        if not os.path.isfile(path):
            cov.append({"rel": r["rel"], "err": "missing"})
            continue
        text = read_text(path)
        paras = [p.strip() for p in PARA_SPLIT.split(text) if p.strip()]
        wins = build_windows(paras, a.max_chars)

        used = skipped = 0
        skipped_win = 0
        prev_tail = ""
        for wi, (win, idxs) in enumerate(wins):
            if a.skip_minor and minor_hit(win):
                skipped += len(win)
                skipped_win += 1
                prev_tail = win[-a.lead_chars:]
                continue
            lead = prev_tail or win[:a.lead_chars]
            tpl = (PROMPT_DIALOGUE if r.get("dialogue") == "高" else PROMPT_SCENE)
            prompt = tpl[wi % len(tpl)].format(lead=lead.strip())
            out_rows.append({
                "id": f"nsfw-{len(out_rows):06d}",
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": win},
                ],
                "meta": {
                    "__stage": "nsfw",
                    "__src": r["rel"],
                    "win": wi,
                    "chars": len(win),
                    "topic": [t[0] for t in r.get("topic", [])],
                    "level": r.get("level"),
                    "form": r.get("form"),
                    "pov": r.get("pov"),
                    "dialogue": r.get("dialogue"),
                    "author": r.get("author"),
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

    report = {
        "files_indexed": len(rows),
        "files_cut": len(adult),
        "files_minor_flagged_left_in_index": minor_files,
        "samples": len(out_rows),
        "src_chars": total_src,
        "used_chars": total_used,
        "skipped_chars": total_skip,
        "coverage": round(total_used / max(total_src, 1), 4),
        "avg_sample_chars": total_used // max(len(out_rows), 1),
        "per_file": sorted(cov, key=lambda x: -x.get("src_chars", 0)),
    }
    with open(os.path.join(os.path.dirname(os.path.abspath(a.out)), "nsfw-coverage.json"),
              "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"[OUT ] {len(out_rows)} 条样本 / {total_used:,} 字入样 / 均 {report['avg_sample_chars']} 字")
    print(f"[COV ] 原文 {total_src:,} 字 → 覆盖率 {report['coverage']:.2%}"
          f"（段级跳过 {total_skip:,} 字）")


if __name__ == "__main__":
    main()

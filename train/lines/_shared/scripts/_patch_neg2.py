# -*- coding: utf-8 -*-
"""patch_neg2.py — 提高负样本构建覆盖率（1152/3407 → 目标 ≥90%）

三个跳过原因与修法
  neg_skip_dirty 601   ：把「拒绝句」也算进敏感词检测（它本身含"露骨性描写"字样）
                          → 只检 body，不检固定拒绝句
  neg_skip_len 1151    ：150–250 窗口太窄，单帧不合规就丢
                          → 改成累加句子直到进窗；过长则在句界截断；过短补收尾句
  neg_skip_no_clean 503：正样本里可用的干净句 <2
                          → 允许 1 句 + 固定收尾，仍不足则再放宽到 ≥120 字
"""
p = 'train/lines/_shared/scripts/build_gate_neg2.py'
s = open(p, encoding='utf-8').read()

old = '''        body = ""
        for k in range(len(sents) - 1):
            frame = FRAMES[(fi + k) % len(FRAMES)]
            cand = frame.format(a=sents[k].rstrip("。"), b=sents[k + 1])
            if a.min_len <= len(REFUSAL) + 2 + len(cand) <= a.max_len:
                body = cand
                break
        if not body:
            # 兜底：单句 + 收尾
            cand = "可以按这个口径继续：%s。%s" % (sents[0].rstrip("。"),
                                                  CLOSERS[fi % len(CLOSERS)])
            if not (a.min_len <= len(REFUSAL) + 2 + len(cand) <= a.max_len):
                st["neg_skip_len"] += 1
                continue
            body = cand
        fi += 1
        content = REFUSAL + "\\n\\n" + body
        if judge_nsfw(content, terms)[0]:
            st["neg_skip_dirty"] += 1
            continue'''

new = '''        # 逐句累加，凑进 [min_len, max_len]（长度只算 body，拒绝句是固定项）
        lo = max(60, a.min_len - len(REFUSAL) - 2)
        hi = max(lo + 10, a.max_len - len(REFUSAL) - 2)
        body = ""
        acc = []
        for k in range(len(sents)):
            acc.append(sents[k].rstrip("。"))
            head = "可以按这个口径继续：%s。" % "，".join(acc)
            cand = head + CLOSERS[fi % len(CLOSERS)]
            if lo <= len(cand) <= hi:
                body = cand
                break
            if len(cand) > hi:
                acc.pop()
                break
        if not body and acc:
            cand = "可以按这个口径继续：%s。%s" % ("，".join(acc), CLOSERS[fi % len(CLOSERS)])
            if len(cand) <= hi + 40:
                body = cand
        if not body:
            st["neg_skip_len"] += 1
            continue
        fi += 1
        # 只检 body：拒绝句是固定文案，不能把它算成脏数据
        if judge_nsfw(body, terms)[0]:
            st["neg_skip_dirty"] += 1
            continue
        content = REFUSAL + "\\n\\n" + body'''

assert old in s, 'anchor missing'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('neg2 patched')

#!/usr/bin/env python
"""nsfw_lex_round4.py — 第四轮词表扩充

从语料频率分析中补充 ~50 个高频 NSFW 写作术语。
这些词是模型续写时最可能用到但尚未建立语义映射的词汇。
"""
import json, os, re, sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')


def read_corpus(src_dir):
    full = ''
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if f.endswith('.txt'):
                with open(os.path.join(root, f), 'r', encoding='utf-8', errors='ignore') as fh:
                    full += fh.read()
    return full


def find_context(full_text, word, max_examples=2):
    examples = []
    for m in re.finditer(re.escape(word), full_text):
        start = max(0, m.start() - 40)
        end = min(len(full_text), m.end() + 40)
        ctx = re.sub(r'\s+', ' ', full_text[start:end]).strip()
        examples.append(ctx)
        if len(examples) >= max_examples:
            break
    return examples


# ===== 第四轮新增词 =====
# (类别, 词, 释义, 同义/近义, 写作提示)
NEW_WORDS_R4 = [
    # --- body: 身体部位/液体 ---
    ("body", "淫水", "女性内生殖通道分泌的透明粘稠液体", "爱液/蜜汁", "强调量多+粘稠，常与'流出''溢出''浸湿'搭配"),
    ("body", "前列腺液", "射精前从尿道口渗出的透明粘稠液体", "预液", "强调先于正式射精，常与'渗出''滴落'搭配"),
    ("body", "粗大肉棒", "粗壮且尺寸大的阴茎", "巨大肉棒", "强调尺寸+硬度，常与'整根''填满'搭配"),
    ("body", "巨大肉棒", "尺寸远超平均的阴茎", "粗大肉棒", "更夸张的尺寸描写"),
    ("body", "爱液", "女性性兴奋时分泌的润滑液体", "淫水/蜜汁", "较温柔的用语，强调'爱'"),
    ("body", "浓精", "浓度高的精液", "精液", "强调粘稠度，常与'喷出''溅出'搭配"),
    ("body", "精浆", "精液的别称，强调液态质感", "精液", "更文学化"),
    ("body", "穴口", "内生殖通道的开口处", "入口", "强调位置+形态，常与'张开''闭合'搭配"),
    ("body", "液体", "泛指体液（精液/爱液/唾液等）", "", "中性词，需上下文确定具体类型"),
    ("body", "嫩肉", "年轻/未开发的肌肤或组织", "娇肉", "强调年轻+柔软"),
    ("body", "媚肉", "具有性吸引力的肌肤", "嫩肉", "强调吸引力"),
    ("body", "弹性", "组织的回弹能力", "韧度", "强调触感反馈"),
    ("body", "液体", "泛指体液", "", "中性词"),
    # --- action: 动作 ---
    ("action", "涌出", "液体大量快速地从体内排出", "喷出/溢出", "强调量+速度+被动"),
    ("action", "射出来", "精液被排出的过程", "射出/喷出", "口语化，强调方向+完成"),
    ("action", "颤动", "身体因刺激而产生的细小抖动", "颤抖", "更精确的生理反应描写"),
    ("action", "翘起", "身体部位向上抬起", "挺起", "强调视觉形态"),
    ("action", "抽动", "活塞式的往复运动", "抽插", "更口语化"),
    ("action", "完全暴露", "身体部位被全部显露", "全裸", "强调状态变化"),
    ("action", "达到高潮", "性兴奋到达顶峰的瞬间", "高潮了/到了", "强调时间+状态变化"),
    ("action", "诱惑", "用外表/行为引发对方欲望", "勾引/撩拨", "强调主动方"),
    ("action", "挑逗", "用言语/动作试探性地激发对方", "撩拨", "强调试探+互动"),
    ("action", "滑落", "物体因重力/液体而向下移动", "滑下", "强调被动+缓慢"),
    ("action", "滑动", "表面因液体而变得光滑后产生的移动", "滑过", "强调触感"),
    ("action", "抽插着", "持续进行活塞式运动", "抽插", "强调持续性"),
    ("action", "流下", "液体因重力而向下流动", "淌下", "强调方向+被动"),
    ("action", "绷紧", "肌肉/组织因用力而收紧", "紧缩", "强调力度+反馈"),
    ("action", "微微张开", "小幅度地打开", "微张", "强调程度+视觉"),
    ("action", "高高翘起", "大幅度向上抬起", "翘起", "强调幅度"),
    ("action", "紧紧包裹", "内壁紧密地围绕住插入物", "绞紧", "强调反馈+触感"),
    # --- state: 状态 ---
    ("state", "欲仙欲死", "形容性快感达到极致、仿佛要死要活", "爽翻了", "强调程度+比喻"),
    ("state", "淫荡", "行为/表情带有明显的性意味", "骚媚", "强调外在表现"),
    ("state", "淫靡", "整体氛围充满情色感", "旖旎", "强调环境/氛围"),
    ("state", "好紧", "主观感受到的紧致反馈", "好紧致", "口语化，第一人称感受"),
    ("state", "好难受", "主观感受到的强烈不适/快感", "好舒服", "口语化，第一人称"),
    ("state", "诱人", "具有性吸引力", "魅惑", "强调外观"),
    ("state", "湿润", "表面因液体而变得潮湿光滑", "湿滑", "强调状态"),
    ("state", "前凸后翘", "身材曲线明显、胸部突出臀部翘起", "凹凸有致", "强调视觉形态"),
    ("state", "晶莹剔透", "透明到能看见内部结构", "晶亮", "强调视觉+质感"),
    ("state", "微微颤抖", "身体因刺激而产生的轻微抖动", "轻颤", "强调程度+节奏"),
    ("state", "浑身颤抖", "全身性的抖动反应", "全身发抖", "强调范围"),
    ("state", "颤抖着", "正在持续抖动", "抖动着", "强调进行时"),
    # --- emotion: 情绪/称呼 ---
    ("emotion", "小骚货", "带有亲昵意味的性称呼", "小淫货", "口语+亲昵，常用于对话"),
    ("emotion", "淫笑", "带有性意味的笑", "媚笑", "强调表情+声音"),
    ("emotion", "受孕", "精子与卵子结合", "怀孕", "强调瞬间+结果"),
    ("emotion", "一边享受", "在进行其他动作的同时体验快感", "边做边享受", "强调同时性"),
    ("emotion", "感觉自己", "主观上觉察到自身的某种状态", "感到", "强调第一人称"),
    ("emotion", "这种感觉", "对当前体验的概括性描述", "这种快感", "强调抽象+概括"),
    # --- descriptor: 描写修饰 ---
    ("descriptor", "诱人", "具有吸引力", "魅惑", "强调外观"),
    ("descriptor", "淫荡", "带有性意味的行为/表情", "骚媚", "强调外在表现"),
    ("descriptor", "淫靡", "充满情色感的氛围", "旖旎", "强调环境"),
    ("descriptor", "前凸后翘", "身材曲线明显", "凹凸有致", "强调视觉"),
    ("descriptor", "晶莹剔透", "透明到能看见内部", "晶亮", "强调质感"),
    ("descriptor", "完全暴露", "被全部显露", "全裸", "强调状态"),
]


def main():
    full_text = read_corpus('user-temp/NSFW小说')
    print(f'语料总字符: {len(full_text)}')

    lex = json.load(open('train/lines/_shared/data/nsfw-lexicon-v3.json', 'r', encoding='utf-8'))

    added = 0
    for cat, word, meaning, synonym, tip in NEW_WORDS_R4:
        if cat not in lex:
            lex[cat] = {"desc": cat, "terms": {}}
        if word not in lex[cat]['terms']:
            freq = len(re.findall(re.escape(word), full_text))
            lex[cat]['terms'][word] = {
                "meaning": meaning,
                "synonym": synonym,
                "writing_tip": tip,
                "freq": freq,
                "context_examples": find_context(full_text, word),
            }
            added += 1
        else:
            freq = len(re.findall(re.escape(word), full_text))
            lex[cat]['terms'][word]["freq"] = freq
            lex[cat]['terms'][word]["context_examples"] = find_context(full_text, word)

    total_words = sum(len(c['terms']) for c in lex.values())
    print(f'本轮新增: {added}')
    print(f'词表总词数: {total_words}')

    with open('train/lines/_shared/data/nsfw-lexicon-v4.json', 'w', encoding='utf-8') as f:
        json.dump(lex, f, ensure_ascii=False, indent=2)
    print(f'已写入: train/lines/_shared/data/nsfw-lexicon-v4.json')

    # 生成新词 SFT
    samples = []
    for cat, word, meaning, synonym, tip in NEW_WORDS_R4:
        freq = len(re.findall(re.escape(word), full_text))
        contexts = find_context(full_text, word)
        user_msg = f"在 NSFW 小说写作中，「{word}」是什么意思？请给出释义和用法示例。"
        parts = [f"【类别】{cat}", f"【释义】{meaning}"]
        if synonym:
            parts.append(f"【同义/近义】{synonym}")
        parts.append(f"【语料频率】出现 {freq} 次")
        parts.append(f"【写作提示】{tip}")
        for i, ctx in enumerate(contexts):
            parts.append(f"【例句{i+1}】{ctx}")
        samples.append({
            "id": f"r4-{cat}-{word}",
            "messages": [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "\n".join(parts)},
            ],
            "type": "glossary_r4",
        })

    with open('train/lines/_shared/data/nsfw-glossary-r4.jsonl', 'w', encoding='utf-8') as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')
    print(f'新词 SFT 样本: {len(samples)}')
    print(f'已写入: train/lines/_shared/data/nsfw-glossary-r4.jsonl')


if __name__ == "__main__":
    main()

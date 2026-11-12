#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t12_pick_span_loss.py -- pick_checkpoint 的答案 span 起点不许是 len(BatchEncoding)。

缺陷现象
    span_loss() 里
        pre = tok.apply_chat_template(msgs[:-1], tokenize=True, add_generation_prompt=True)
        lo, hi = len(pre), min(len(ids), a.ctx)
    transformers 5.x 的 apply_chat_template(tokenize=True) 返回 BatchEncoding，
    而 len(BatchEncoding) 是**字段数（2）**，不是 token 数 → lo = 2。
    实测（re-subset.val.jsonl 第 1 条）：len(pre)=2，真实前缀 token=69，T=134。
后果
    val_loss 从 token 2 算到 134：system+user prompt 与模板脚手架全被当成答案损失。
    val_loss 是 checkpoint 选优的第三键（re_pass, kitty_pass, -val_loss），于是它
    **主要由 prompt 长度决定，对答案质量不敏感** —— 选优判据被稀释，而报告完全正常。
    （与第 3 例 precompute_activations 同族：都是 len(BatchEncoding) 当 token 数。）
正确的断言
    ① 正常：lo 必须等于真实前缀 token 数（69），不是 2；且 lo < hi，hi == min(T, ctx)；
       顺带断言假 tokenizer 的 BatchEncoding 确实 len()==2（证明这个坑真的存在）。
    ② 缺失/异常：tokenizer 抛异常时 span_bounds 必须抛出去（不许吞成正常值）；
       空消息列表必须返回 None（不许算出一个假的 span）。
    ③ 真错位被抓：模板在 assistant 边界 BPE 漂移（pre 不是 ids 的 token 前缀）时，
       lo 必须收敛到最长公共前缀，不能硬取 len(pre)；--ctx 小于前缀长度时必须返回 None。
如果这条 FAIL 说明什么
    span_loss 又退回了 len(BatchEncoding) / 前缀硬取 —— 检查 scripts/pick_checkpoint.py
    的 _as_ids() 与 span_bounds()，以及 span_loss 是否还在自己算 lo。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
# 可选 argv[1]：指向另一份 pick_checkpoint.py（变体对照 / 变异测试用）。
# 默认就是仓库里那份；run_all.py 不传参。
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KITTY, "scripts",
                                                            "pick_checkpoint.py")


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


class BatchEncodingLike:
    """Mimic transformers' BatchEncoding: len() == number of FIELDS, not tokens."""

    def __init__(self, ids):
        self.input_ids = list(ids)
        self.attention_mask = [1] * len(self.input_ids)

    def __len__(self):
        return 2                                  # input_ids + attention_mask

    def __getitem__(self, k):
        return getattr(self, k)


class FakeTok:
    """Deterministic chat-template stub. T=134, 真实前缀=69（与实测同数）。

    ids 规则：满串固定 1000..1133；前缀串 = 满串前 69 个 → 天然是 token 前缀。
    drift=True 时把前缀第 68 位改掉，模拟 `<think>` vs `<think>\\n\\n` 的 BPE 边界差异。
    """

    T = 134
    N_PRE = 69

    def __init__(self, drift=False, boom=False):
        self.drift = drift
        self.boom = boom
        self._ids = [1000 + i for i in range(self.T)]
        self.calls = 0
        self.table = {}                           # 渲染串 → ids（__call__ 用）

    @staticmethod
    def _render(msgs, gen):
        s = "".join(f"<{m['role']}>{m['content']}</{m['role']}>" for m in msgs)
        return s + ("<gen>" if gen else "")

    def _prefix_ids(self):
        ids = list(self._ids[:self.N_PRE])
        if self.drift:
            ids[-1] = 9999                        # 边界合并不同 → 不再是 token 前缀
        return ids

    def _ids_for(self, msgs, gen):
        """消息数决定 token 数：空=0 / 前缀(2 条+生成提示)=69 / 满串(3 条)=134。"""
        if not msgs:
            return []
        if gen and len(msgs) == len(MSGS) - 1:
            return self._prefix_ids()
        return list(self._ids)

    def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=False,
                            **kw):
        if self.boom:
            raise RuntimeError("boom: template exploded")
        self.calls += 1
        text = self._render(msgs, add_generation_prompt)
        ids = self._ids_for(msgs, add_generation_prompt)
        self.table[text] = ids
        if not tokenize:
            return text
        return BatchEncodingLike(ids)

    def __call__(self, text, add_special_tokens=False, **kw):
        if self.boom:
            raise RuntimeError("boom: tokenizer exploded")
        return BatchEncodingLike(self.table.get(text, []))

    def __len__(self):
        return 2


MSGS = [{"role": "system", "content": "S" * 40},
        {"role": "user", "content": "U" * 40},
        {"role": "assistant", "content": "A" * 40}]

fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


try:
    pc = load_mod(SCRIPT, "pick_ckpt_t12")
except Exception as e:                            # import 级失败单独说清楚
    print(f"\nFAIL: 载入 pick_checkpoint.py 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

for fn in ("_as_ids", "span_bounds"):
    if not hasattr(pc, fn):
        print(f"\nFAIL: pick_checkpoint.py 缺 {fn}()（回归脚本的锚点）")
        sys.exit(1)

# ---- ① 正常：lo 必须是真实 token 数 -------------------------------------------
tok = FakeTok()
raw = tok.apply_chat_template(MSGS[:-1], tokenize=True, add_generation_prompt=True)
check("BatchEncoding len()==2（证明这个坑真的存在）",
      len(raw) == 2 and len(raw.input_ids) == FakeTok.N_PRE,
      f"len()={len(raw)}  input_ids={len(raw.input_ids)}")
pre_ids = pc._as_ids(raw)
check("_as_ids 取到的是 token 数", len(pre_ids) == FakeTok.N_PRE,
      f"_as_ids={len(pre_ids)} 期望 {FakeTok.N_PRE}")

b = pc.span_bounds(tok, MSGS, 512)
if b is None:
    check("span_bounds 正常输入不许返回 None", False, "返回了 None")
else:
    ids, lo, hi = b
    check("lo == 真实前缀 token 数 69（不是 2）", lo == FakeTok.N_PRE,
          f"lo={lo} 期望 {FakeTok.N_PRE}")
    check("0 < lo < hi", 0 < lo < hi, f"lo={lo} hi={hi}")
    check("hi == min(T, ctx)", hi == min(len(ids), 512), f"hi={hi} T={len(ids)} ctx=512")
    check("T == 134", len(ids) == FakeTok.T, f"T={len(ids)}")

# ctx 小于 T 但仍大于前缀 → hi 跟 ctx 走
b2 = pc.span_bounds(tok, MSGS, 100)
check("hi 随 --ctx 收窄", b2 is not None and b2[2] == 100 and b2[1] == FakeTok.N_PRE,
      f"({b2[1] if b2 else None}, {b2[2] if b2 else None}) ctx=100")

# ---- ② 缺失 / 异常：不许吞 ----------------------------------------------------
boom = FakeTok(boom=True)
try:
    pc.span_bounds(boom, MSGS, 512)
    check("tokenizer 异常必须抛出去", False, "被吞成正常返回")
except Exception as e:
    check("tokenizer 异常必须抛出去", True, f"{type(e).__name__}: {e}")

check("空消息列表 → None（不算假 span）", pc.span_bounds(FakeTok(), [], 512) is None,
      "msgs=[]")

# ---- ③ 真错位被抓 -------------------------------------------------------------
drift = FakeTok(drift=True)
bd = pc.span_bounds(drift, MSGS, 512)
if bd is None:
    check("漂移时应收敛到公共前缀而非 None", False, "返回了 None")
else:
    ids_d, lo_d, hi_d = bd
    check("漂移：lo 收敛到最长公共前缀 68", lo_d == FakeTok.N_PRE - 1,
          f"lo={lo_d} 期望 {FakeTok.N_PRE - 1}")
    check("漂移：没有硬取 len(pre)", lo_d != FakeTok.N_PRE, f"lo={lo_d}")

# --ctx 比前缀还短 → 窗口里没有答案 token → None（旧写法会给出 hi-lo 为负的假区间后
# 落到 max(0, hi-1) 上，把 prompt 尾部当成答案）
check("--ctx 短于前缀 → None", pc.span_bounds(FakeTok(), MSGS, 50) is None, "ctx=50")

print("\nPASS: span_loss 起点=真实前缀 token 数，异常不吞，错位/截断被抓"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)

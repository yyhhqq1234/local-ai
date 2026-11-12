"""与交付版完全同格式的 recipe（不复刻 G1 的 q6 提升）

交付版 kittyrev-oxcoder9b-nsfw-gate-full-GSQ 的实际 formats 是
  q4×32 / q5×96 / q8×35 / bf16×521 / fp32×48
= 官方 _dense_groupwise(Q8) 基线，mlp gate/up 走 q8（不是 recipe_g1 里的 q6）。
当前引擎（10:08 build）对 q6 的 24576 行 swiglu 报 unsupported weight geometry，
因此回填 MTP 头时必须用这条基线 recipe。
"""

from tools.convert.official_recipes import Q8, _dense_groupwise


def configure(model, recipe, sources):  # noqa: ARG001
    _dense_groupwise(model, recipe, Q8)

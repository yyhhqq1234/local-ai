"""G1 混合量化 recipe（kittyrev-oxcoder9b-nsfw-gate-full-GSQ）

定义（= p6d G1_mlp_gate_up）：
  1. 基线取官方 `_dense_groupwise(model, recipe, Q8)`：
       text/token_embedding, text/output_head → q8_g32_fp16
       text/layers/*/attention/query|key, gdn/query|key, mlp/gate|up → q4_g64_fp16
       其余投影 → q5_g64_fp16
       gdn/a_projection, gdn/b_projection → separate()
  2. 把 **mlp/gate 与 mlp/up** 从 q4 提升到 q6_g64_fp16（这就是 G1 与基线的唯一差异）

数值依据：现用 oxcoder9b-merged.ninfer 的 formats {q4:64, q5:96, q8:2}
  与 _dense_groupwise 的分配完全吻合（每层 q4×2、q5×3，词表 q8×2），
  因此“只动 mlp.gate/up”即得 G1。

用法（在 ninfer-master 目录下，用 train\.venv 的 python）：
  python -m tools.convert \
    --model  "<...>/models/merged-2b-nsfw-mtp-tuned-v3" \
    --recipe "<...>/_work/ninfer-9b/recipe_g1_full_gsq.py" \
    --components text,vision,mtp \
    --resource "video_preprocessor_config.json=<...>/_work/ninfer-9b/video_preprocessor_config.json" \
    --name kittyrev-oxcoder9b-nsfw-gate-full-GSQ \
    --out  "<...>/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer"
"""

from tools.convert.official_recipes import Q6, Q8, _assign, _dense_groupwise

PROMOTE_SUFFIXES = ("/mlp/gate", "/mlp/up")


def configure(model, recipe, sources):  # noqa: ARG001
    # 1) 官方稠密分组分配作为基线
    _dense_groupwise(model, recipe, Q8)

    # 2) G1 差异：mlp.gate / mlp.up 升 q6
    promoted = []
    for name, parameter in model.parameters.items():
        if not name.startswith("text/layers/") or not parameter.projection:
            continue
        if name.endswith(PROMOTE_SUFFIXES):
            _assign(recipe, name, Q6)
            promoted.append(name)

    print(f"[g1] promoted {len(promoted)} mlp gate/up parameters to {Q6}")
    for n in promoted[:4]:
        print(f"[g1]   {n}")
    if not promoted:
        raise RuntimeError(
            "[g1] 没有任何 mlp/gate 或 mlp/up 参数被匹配；可用参数名示例：\n  "
            + "\n  ".join(sorted(model.parameters)[:40])
        )

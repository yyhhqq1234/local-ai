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

from tools.convert.official_recipes import Q4, Q8, _assign, _dense_groupwise

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
            _assign(recipe, name, Q8)
            promoted.append(name)

    print(f"[g1] promoted {len(promoted)} mlp gate/up parameters to {Q8}")
    for n in promoted[:4]:
        print(f"[g1]   {n}")
    if not promoted:
        raise RuntimeError(
            "[g1] 没有任何 mlp/gate 或 mlp/up 参数被匹配；可用参数名示例：\n  "
            + "\n  ".join(sorted(model.parameters)[:40])
        )

    # 3) vision / mtp 的投影降到 q4（引擎的 q8 linear 分派没有这些形状，
    #    保持 q8 会导致 --vision / --spec mtp 启动 FATAL）。text 侧不动。
    vis_mtp = []
    for name, parameter in model.parameters.items():
        if name.startswith(("vision/", "mtp/")) and parameter.projection:
            _assign(recipe, name, "bf16")
            vis_mtp.append(name)
    print(f"[g1] vision/mtp projections set to bf16: {len(vis_mtp)}")
    # 4) mtp 的 attention 三个投影各给不同格式：使 converter 的 compatible() 失效 → 不合并成 parent
    #    → 每个张量独立成 object（1 个 part，必然连续），避免 weight_view 的
    #    "native input requires one contiguous parent region"。
    #    引擎侧 mtp.cpp 已改为：k 不在 {2048,5120} 时回退到非 pair 路径，所以不需要 q8 pair 布局。
    mtp_split = 0
    from tools.convert.official_recipes import Q4, Q5, Q8 as _Q8
    fmt_by_role = {"/attention/query": _Q8, "/attention/gate": _Q8, "/attention/key": _Q8, "/attention/value": _Q8}  # 四者同格式才能并入同一 parent
    for name, parameter in model.parameters.items():
        if not name.startswith("mtp/"):
            continue
        for suffix, fmt in fmt_by_role.items():
            if name.endswith(suffix):
                _assign(recipe, name, fmt)
                mtp_split += 1
    print(f"[g1] mtp attention split by format: {mtp_split}")
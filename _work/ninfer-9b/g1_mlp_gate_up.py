"""G1 混合量化 override：把 text 各层 mlp.gate / mlp.up 升到 q6_g64_fp16。

用法（在 ninfer-master 目录下执行）：
    python -m tools.convert \
        --model "D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/models/merged-2b-nsfw-mtp-tuned-v3" \
        --recipe qwen3_5_9b_gsq \
        --override "D:/BaiduNetdiskDownload/Local-AI/_work/ninfer-9b/g1_mlp_gate_up.py" \
        --components text \
        --out "D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/oxcoder9b-g1-text.ninfer"

依据：
  · b4-allocation.json 的 rco assign = [q5,q4,q5,q5,q8,q6,q6,q6,q6,q8,q8,q8]，cost 4.9846
    其中 q6 四项正好对应 mlp.gate / mlp.up（12 层组内的 gate/up 位）
  · docs/weight-conversion.md:125-150 —— override 在基础 recipe 之后执行，
    写法 recipe.assign(name, format=..., method=...)

本脚本自带参数名核对：先打印所有匹配 mlp 的 gate/up 参数名再 assign，
若一个都没匹配到会抛错，避免静默产出非 G1 的产物。
"""

import re


def configure(model, recipe, sources):  # noqa: ARG001  (sources 由调用方传入)
    names = sorted(
        n for n in model.parameters
        if re.search(r"(^|/)mlp/(gate|up)(/|$)", n) or re.search(r"\.mlp\.(gate|up)\.", n)
    )
    print(f"[g1] matched {len(names)} mlp gate/up parameters")
    for n in names[:6]:
        print(f"[g1]   {n}  {model.parameters[n].shape}")

    if not names:
        sample = sorted(model.parameters)[:40]
        raise RuntimeError(
            "[g1] 没有任何 mlp gate/up 参数匹配；可用的前 40 个参数名为：\n  "
            + "\n  ".join(sample)
        )

    for n in names:
        recipe.assign(n, format="q6_g64_fp16", method="grouped_absmax")
    print(f"[g1] assigned q6_g64_fp16 to {len(names)} parameters")

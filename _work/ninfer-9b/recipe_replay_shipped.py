"""按已交付 artifact 的 conversion.json 逐参数复刻 format + layout + method。

只复刻格式不够：向量参数（a_log/dt_bias/norm）在交付版是 contiguous_le_v1，
默认分配会走 row_split → 引擎报 gdn_control: unsupported parent geometry。
"""
import json
import os

from tools.convert import methods as M

SHIPPED = os.environ.get(
    "NINFER_REPLAY_MANIFEST",
    r"D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out"
    r"\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer.conversion.json",
)


def configure(model, recipe, sources):  # noqa: ARG001
    d = json.load(open(SHIPPED, encoding="utf-8"))
    applied = 0
    for m in d.get("methods", []):
        fmt = m.get("format")
        if not fmt:
            continue
        fn = getattr(M, m.get("method") or "grouped_absmax", None)
        if fn is None:
            print("[replay] unknown method", m.get("method"))
            continue
        params = m.get("parameters") or []
        # 不要 separate()：交付版把多参数放同一个 object（row_split_k128_v1），
        # separate 会拆成两个 parent，引擎报 native input requires one contiguous parent region
        for p in params:
            recipe.assign(p, format=fmt, method=fn, layout=m.get("layout"))
        applied += len(params)
    print(f"[replay] applied {applied} parameter formats from {os.path.basename(SHIPPED)}")

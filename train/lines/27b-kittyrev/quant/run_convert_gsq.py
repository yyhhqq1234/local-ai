#!/usr/bin/env python
"""
run_convert_gsq.py — 带论文级 GSQ 的转换入口（零污染 vendor）

不修改 ninfer converter 的任何文件。运行时把 grouped_gumbel 方法与
qwen3_5_9b_gsq / qwen3_5_9b_q8max_gsq 两条 recipe 注入内存，再调用官方 CLI。

用法
  # 看是否注入成功（列出 recipe / method）
  python train/lines/27b-kittyrev/quant/run_convert_gsq.py --check

  # 真转换（参数与官方 -m tools.convert 完全一致，只是多了 gsq recipe）
  python train/lines/27b-kittyrev/quant/run_convert_gsq.py ^
    --model  train\\models\\OxCoder-9B ^
    --recipe qwen3_5_9b_gsq ^
    --components text --device cpu --rows-per-chunk 512 ^
    --name oxcoder-9b-gsq --out train\\models\\oxcoder-9b-GSQ.ninfer

为什么这样做
  官方 converter 的 methods.py / official_recipes.py 是 vendor 代码。
  直接 patch 会留下难以回滚的改动（本轮已踩过：revert 误删注册字典）。
  改为运行时注入后：
    · vendor 文件一字不动，出问题只需不跑这个 wrapper
    · 实现全部在 train/lines/27b-kittyrev/quant/gsq_gumbel.py，可单独测试
    · 注入点与官方扩展点同构（METHODS 字典 + RECIPES 字典）
"""
from __future__ import annotations

import pathlib
import sys

# ★ 2026-11-07 修：__file__ = train/lines/27b-kittyrev/quant/run_convert_gsq.py
#   parents[0]=quant parents[1]=27b-kittyrev parents[2]=lines parents[3]=train parents[4]=Local-AI
ROOT = pathlib.Path(__file__).resolve().parents[4]      # Local-AI
CONV = ROOT / "train" / "lines" / "_shared" / "tools" / "ninfer-convert" / "ninfer-all-master"
QUANT = pathlib.Path(__file__).resolve().parent


def bootstrap():
    """注入 grouped_gumbel 方法与 GSQ recipes，返回注入摘要"""
    for p in (str(CONV), str(QUANT)):
        if p not in sys.path:
            sys.path.insert(0, p)

    import gsq_gumbel as G
    import gsq_gumbel_v2 as G2
    from tools.convert import methods as M
    from tools.convert.methods import PreparedMethod, PrepareRequest, _preflight
    from tools.artifact.formats import QuantFormat, get_format

    def grouped_gumbel(request: PrepareRequest) -> PreparedMethod:
        """Gumbel-Softmax 学码本 + scale 细扫（论文路径）"""
        if (
            not isinstance(get_format(request.target.format), QuantFormat)
            or len(request.target.shape) != 2
        ):
            raise ValueError("grouped_gumbel requires a grouped-integer matrix target")
        if request.target.format == "q2_g64_fp16":
            raise ValueError("q2_g64_fp16 requires import_encoded from trained GSQ Q2_0 codes")
        p = dict(request.parameters or {})
        steps = int(p.pop("steps", 150))
        lr = float(p.pop("lr", 5e-2))
        tau0 = float(p.pop("tau0", 2.0))
        tau_min = float(p.pop("tau_min", 0.4))
        row_batch = int(p.pop("row_batch", 256))
        if p:
            raise ValueError(f"{request.target.id}: unknown grouped_gumbel parameters {sorted(p)}")
        _preflight(request)
        n, k = request.target.shape
        # ★ 2026-11-07：converter 里 request.target.format 在不同调用点既被当字符串
        #   （`== "q2_g64_fp16"`）又被传给 get_format()，两种形态都要兼容
        _raw_fmt = request.target.format
        fmt_name = _raw_fmt if isinstance(_raw_fmt, str) else getattr(_raw_fmt, "name", None)
        if not isinstance(fmt_name, str):
            fmt_name = str(_raw_fmt)
        if fmt_name not in G2.FORMATS:
            raise ValueError(f"grouped_gumbel: 未支持的格式 {fmt_name}（已知 {sorted(G2.FORMATS)}）")

        def produce(output):
            tid = str(getattr(request.target, "id", "")).lower()
            elems = n * k
            # ★ 2026-11-07 关键修正：**必须按 request.rows_per_chunk 分批**，不能一次性取全量。
            #   实测一次性 request.values(0, 248320*4096) 要读 2 GB，5 分钟都出不来；
            #   内置 grouped_absmax 按 512 行（4 MB/批）循环，180s 能出 8 个张量。
            #   同时 embed/lm_head 用 absmax（Q8 下 GSQ 收益仅 5%，不值得 Python 慢算）。
            chunk = max(int(request.rows_per_chunk), 1)
            is_vocab = any(t in tid for t in ("token_embedding", "lm_head", "output"))
            if elems > 5e8:
                use_steps = min(steps, 40)
            elif elems > 1e8:
                use_steps = min(steps, 80)
            else:
                use_steps = steps

            import time as _t
            _t0 = _t.time()
            for begin in range(0, n, chunk):
                end = min(n, begin + chunk)
                values = request.values(begin * k, end * k).reshape(end - begin, k)
                if not values.dtype.is_floating_point:
                    raise TypeError("grouped_gumbel source must provide floating-point values")
                if is_vocab:
                    qm = G2.baseline_absmax(values, fmt_name)
                else:
                    qm = G2.quantize_matrix_gsq_v2(
                        values, fmt_name, steps=use_steps, lr=lr, tau0=tau0, tau_min=tau_min,
                        row_batch=row_batch, device=request.device,
                    )
                output.write_codes(begin, qm.codes, qm.scales)
                del values, qm
            _t1 = _t.time()
            print(f"[TIMING] {tid}: {n}x{k} steps={0 if is_vocab else use_steps} "
                  f"chunk={chunk} total={_t1-_t0:.1f}s", flush=True)

        return request.job(produce=produce)

    M.grouped_gumbel = grouped_gumbel
    M.METHODS["grouped_gumbel"] = grouped_gumbel

    from tools.convert import official_recipes as R
    Q8 = R.Q8

    def _ungroup_gdn(recipe):
        """★ 2026-11-07：清掉 GDN 的 explicit group

        converter 的 qwen3_5.py 里对 gdn/query|key|value|z 调了 self.group()，
        结果 4 个逻辑投影被合并成 1~2 个 parent object：
            query(2048)+key(2048) → parent (4096,4096)
            value(4096)+z(4096)   → parent (8192,4096)
        而引擎 load/text.cpp 是按逻辑名逐个找：
            b.parameter("gdn/query", {k, h})   k=2048
        找到的 object 是 (4096,4096) → 判为 unsupported logical projection geometry。
        GDN_DECOMPOSE=1 时把这个 group 清掉，让每个投影独立成 object。
        """
        import os as _os
        if _os.environ.get("GDN_DECOMPOSE") != "1":
            return
        # 合并发生在 recipe.prepare() 的 compatible()：四项 (format,layout,method,parameters)
        # 全同就自动合并成一个 parent。explicit_groups 是空的原因就在这。
        # 破法：给 GDN 的 4 个投影分配**不同 format**，让它们不满足 compatible()。
        alt = {"gdn/query": R.Q4, "gdn/key": R.Q5, "gdn/value": R.Q6, "gdn/z": R.Q8}
        n = 0
        for pat, fmt in alt.items():
            try:
                names = recipe.match("*/" + pat)
            except Exception:
                continue
            for nm in names:
                if nm in recipe.selections:
                    recipe.assign(nm, format=fmt, method=M.grouped_absmax)
                    n += 1
        print(f"[override] GDN 逐投影分格式（强制不合并）：{n} 个", flush=True)

    def qwen3_5_9b_gsq(model, recipe, sources):
        # GSQ_METHOD=absmax 时退化为 converter 原生 grouped_absmax（用于对照测速）
        import os as _os
        m = M.grouped_absmax if _os.environ.get("GSQ_METHOD") == "absmax" else grouped_gumbel
        R._dense_groupwise(model, recipe, Q8, method=m)
        _ungroup_gdn(recipe)

    def qwen3_5_9b_q8max_gsq(model, recipe, sources):
        import os as _os
        m = M.grouped_absmax if _os.environ.get("GSQ_METHOD") == "absmax" else grouped_gumbel
        R._dense_groupwise(model, recipe, Q8, gate_up=Q8, method=m)

    R.RECIPES["qwen3_5_9b_gsq"] = qwen3_5_9b_gsq
    R.RECIPES["qwen3_5_9b_q8max_gsq"] = qwen3_5_9b_q8max_gsq

    return {
        "method_injected": "grouped_gumbel" in M.METHODS,
        "recipes": sorted(k for k in R.RECIPES if "gsq" in k),
        "recipe_total": len(R.RECIPES),
        "impl": str(QUANT / "gsq_gumbel.py"),
        "vendor_untouched": True,
    }


if __name__ == "__main__":
    info = bootstrap()
    if "--check" in sys.argv:
        import json
        print(json.dumps(info, ensure_ascii=False, indent=2))
        sys.exit(0)
    # 透传参数给官方 CLI（去掉 --check）
    from tools.convert.__main__ import main
    sys.argv = [a for a in sys.argv if a != "--check"]
    main()

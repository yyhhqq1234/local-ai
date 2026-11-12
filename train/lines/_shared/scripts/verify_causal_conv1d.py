# -*- coding: utf-8 -*-
"""verify_causal_conv1d.py —— 替身 v3 验收（Windows / torch2.9.1+cu130 / triton-windows 3.8）

用法：
    $env:PYTHONPATH='train\\scripts'
    train\\.venv\\Scripts\\python.exe train/lines/_shared/scripts/verify_causal_conv1d.py

判据（任一 FAIL 即退出码 1）：
  ① 前向数值：两种输入布局（contiguous (B,C,T) / 通道连续视图）都对参考 bf16 舍入级
  ② 梯度：fp32 相对误差 <=1e-5，bf16 <=3%
  ③ decode：输出与 conv_state 原地更新对参考一致；state 宽度 != K 时必须走参考
  ④ varlen：分段结果对逐段参考一致，且与"不分段"明显不同（证明确实切了边界）
  ⑤ 装饰器链路：跑一次 transformers 的 causal_conv1d_fn，替身计数器要涨（确认没被 hub 抢走）
  ⑥ 加速：通道连续视图布局下 prefill >=3x
"""
import os
import sys

import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import causal_conv1d as mine  # noqa: E402

DT = torch.bfloat16
FAILS = []


def check(name, ok, detail=""):
    print("  [%s] %-40s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS.append(name)


def ref_fn(x, w, b, act=None):
    _, H, T = x.shape
    out = F.conv1d(x.to(w.dtype), w.unsqueeze(1), b, padding=w.shape[-1] - 1, groups=H)[:, :, :T]
    return (F.silu(out) if act == "silu" else out).to(x.dtype)


def ref_update(x, st, w, b, act=None):
    _, H, T = x.shape
    L = st.shape[-1]
    new = torch.cat([st, x], dim=-1).to(w.dtype)
    st.copy_(new[:, :, -L:])
    out = F.conv1d(new, w.unsqueeze(1), b, padding=0, groups=H)[:, :, -T:]
    return (F.silu(out) if act == "silu" else out).to(x.dtype)


def bench(fn, iters=30, warmup=8):
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    s = torch.cuda.Event(True)
    e = torch.cuda.Event(True)
    s.record()
    for _ in range(iters):
        fn()
    e.record()
    torch.cuda.synchronize()
    return s.elapsed_time(e) / iters


def main():
    print("torch %s | cuda %s | %s" % (torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0)))
    torch.manual_seed(0)
    B, C, T, W = 2, 5120, 512, 4

    # ── ① 前向数值（两种布局）──────────────────────────────
    w = (torch.randn(C, W, device="cuda", dtype=DT) * 0.1)
    b = (torch.randn(C, device="cuda", dtype=DT) * 0.1)
    for tag, x in (
        ("contiguous (B,C,T)", torch.randn(B, C, T, device="cuda", dtype=DT) * 0.1),
        ("通道连续视图", (torch.randn(B, T, C, device="cuda", dtype=DT) * 0.1).transpose(1, 2)),
    ):
        with torch.no_grad():
            d0 = (ref_fn(x, w, b, None) - mine.causal_conv1d_fn(x, w, b, None)).abs().max().item()
            d1 = (ref_fn(x, w, b, "silu") - mine.causal_conv1d_fn(x, w, b, "silu")).abs().max().item()
            got = mine.causal_conv1d_fn(x, w, b, "silu")
        check("前向 %s act=None" % tag, d0 <= 1e-2, "max|diff|=%.3e" % d0)
        check("前向 %s act=silu" % tag, d1 <= 1e-2, "max|diff|=%.3e" % d1)
        check("输出形状 %s" % tag, tuple(got.shape) == (B, C, T), "%s stride=%s" % (tuple(got.shape), got.stride()))

    # ── ② 梯度 ─────────────────────────────────────────────
    for dt, tag, tol in ((torch.float32, "fp32", 1e-5), (DT, "bf16", 3e-2)):
        xx = (torch.randn(1, 128, 96, device="cuda", dtype=dt) * 0.5).requires_grad_(True)
        ww = (torch.randn(128, W, device="cuda", dtype=dt) * 0.1).requires_grad_(True)
        bb = (torch.randn(128, device="cuda", dtype=dt) * 0.1).requires_grad_(True)
        x2 = xx.detach().clone().requires_grad_(True)
        w2 = ww.detach().clone().requires_grad_(True)
        b2 = bb.detach().clone().requires_grad_(True)
        g = torch.randn(1, 128, 96, device="cuda", dtype=dt)
        o1 = mine.causal_conv1d_fn(xx, ww, bb, "silu")
        o2 = ref_fn(x2, w2, b2, "silu")
        (o1.float() * g.float()).sum().backward()
        (o2.float() * g.float()).sum().backward()
        gx = (xx.grad.float() - x2.grad.float()).abs().max().item()
        rel = gx / max(x2.grad.float().abs().max().item(), 1e-6)
        check("梯度 %s 反传对齐" % tag, rel <= tol,
              "gx_rel=%.3e gw_abs=%.3e" % (rel, (ww.grad.float() - w2.grad.float()).abs().max().item()))

    # ── ③ decode update ────────────────────────────────────
    xd = (torch.randn(B, T, C, device="cuda", dtype=DT) * 0.1).transpose(1, 2)[:, :, :1].contiguous()
    xd = xd.transpose(1, 2).transpose(1, 2)          # (B,C,1) contiguous
    s1 = (torch.randn(B, C, W, device="cuda", dtype=DT) * 0.1)
    s2 = s1.clone()
    o_ref = ref_update(xd, s1, w, b, "silu")
    o_my = mine.causal_conv1d_update(xd, s2, w, b, "silu")
    dd = (o_ref.float() - o_my.float()).abs().max().item()
    check("decode 输出 bf16 舍入级", dd <= 1e-2, "max|diff|=%.3e shape=%s" % (dd, tuple(o_my.shape)))
    check("decode conv_state 原地更新逐位一致", torch.equal(s1, s2),
          "max|diff|=%.3e" % (s1.float() - s2.float()).abs().max().item())

    s3 = (torch.randn(B, C, 2 * W, device="cuda", dtype=DT) * 0.1)   # 宽度 != K → 必须退参考
    s4 = s3.clone()
    o_r2 = ref_update(xd, s3, w, b, "silu")
    o_m2 = mine.causal_conv1d_update(xd, s4, w, b, "silu")
    check("state 宽度!=K 自动退参考", torch.equal(o_r2, o_m2) and torch.equal(s3, s4))

    # ── ④ varlen ───────────────────────────────────────────
    lens = [37, 129, 250, 96]
    cu = torch.tensor([0] + list(torch.cumsum(torch.tensor(lens), 0).tolist()),
                      dtype=torch.int32, device="cuda")
    tv = int(cu[-1].item())
    xv = (torch.randn(1, tv, C, device="cuda", dtype=DT) * 0.1).transpose(1, 2)   # 通道连续视图
    with torch.no_grad():
        got = mine.causal_conv1d_fn(xv, w, b, "silu", cu_seq_lens_q=cu)
        naive = mine.causal_conv1d_fn(xv, w, b, "silu")
    exp = torch.empty_like(xv)
    cl = cu.tolist()
    for i in range(len(lens)):
        s, e = cl[i], cl[i + 1]
        exp[:, :, s:e] = ref_fn(xv[:, :, s:e].contiguous(), w, b, "silu")
    dv = (got - exp).abs().max().item()
    dnv = (got - naive).abs().max().item()
    check("varlen 分段对逐段参考", dv <= 1e-2, "max|diff|=%.3e" % dv)
    check("varlen 确实切开了边界", dnv > 1e-2, "与不分段差 %.3e" % dnv)

    # ── ⑤ 装饰器链路（运行时归因）───────────────────────────
    try:
        from transformers.models.qwen3_5 import modeling_qwen3_5 as M
        before = mine.diagnostics()["fwd_calls"]
        hs = torch.randn(1, 128, 64, device="cuda", dtype=DT) * 0.1
        ww = torch.randn(128, W, device="cuda", dtype=DT) * 0.1
        bb = torch.randn(128, device="cuda", dtype=DT) * 0.1
        with torch.no_grad():
            M.causal_conv1d_fn(hs, ww, bb, activation="silu")
        check("transformers 实调用落在替身", mine.diagnostics()["fwd_calls"] > before)
    except Exception as e:                                           # noqa: BLE001
        check("transformers 实调用落在替身", False, "import 失败 %r" % (e,))

    # ── ⑥ 加速（通道连续视图 = 模型真实布局）────────────────
    print("\n基准（ms/次，模型真实布局）：")
    ratios = []
    for (c, t, bb_) in ((10240, 512, 2), (10240, 2048, 2), (10240, 8192, 2), (5120, 4096, 4)):
        x = (torch.randn(bb_, t, c, device="cuda", dtype=DT) * 0.1).transpose(1, 2)
        ww = (torch.randn(c, W, device="cuda", dtype=DT) * 0.1)
        b2 = (torch.randn(c, device="cuda", dtype=DT) * 0.1)
        with torch.no_grad():
            tr = bench(lambda: ref_fn(x, ww, b2, "silu"))
            tm = bench(lambda: mine.causal_conv1d_fn(x, ww, b2, "silu"))
        ratios.append(tr / tm)
        print("  prefill c=%-6d T=%-5d B=%d  参考 %8.3f  替身 %8.3f  加速 %5.2fx"
              % (c, t, bb_, tr, tm, tr / tm))
    check("prefill 加速 >=3x", min(ratios) >= 3.0, "min=%.2fx" % min(ratios))

    print("\n诊断:", mine.diagnostics())
    print("\n结果: %s" % ("全部 PASS" if not FAILS else "FAIL -> " + ", ".join(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())

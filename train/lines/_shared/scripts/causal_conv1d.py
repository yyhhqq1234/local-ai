# -*- coding: utf-8 -*-
"""causal_conv1d —— 本地替身 v3（Windows / cp313 / torch2.9.1+cu130 / triton-windows 3.8 / Blackwell）

## 为什么需要它
transformers 5.x 的 Qwen3.5(GDN) 用
    @use_kernel_func_from_hub_with_fallback("causal_conv1d_fn", "causal_conv1d")
取核，取不到就退回纯 PyTorch 参考实现并刷 warning。三条官方通路在本机状态（2026-10-30 实测）：

  ① pip causal-conv1d    —— 无 nvcc、无 cp313 wheel                ⇒ 不可行
  ② HF kernels hub       —— mamba-ssm 的 build variant 全是 linux   ⇒ 不可行
  ③ FLA + triton-windows —— 可用（本模块走这条）

## v3 的关键点（全部实测，非推测）
1. **零拷贝布局**。模型里的 `mixed_qkv` 是 `in_proj(...).transpose(1,2)`，即 (B,C,T) 只是
   (B,T,C) 内存上的**视图**（stride=(C*T,1,C)）。FLA 要的正是通道连续 —— 直接把这个视图
   transpose 回去喂进去，进出都不搬数据：
        c=10240,T=2048  参考 6.93ms | 零拷贝 0.69ms (10.1x) | 搬两次 3.19ms (2.2x)
        c=10240,T=8192  参考 27.3ms | 零拷贝 2.71ms (10.1x) | 搬两次 12.96ms (2.1x)
   v2 在 T=8192 上反而慢过参考（23.8ms vs 16.9ms），因为两次 transpose+contiguous
   各要 10ms 量级（671MB 非合并访问），把 6x 的卷积收益全吃掉还倒亏。
2. **训练路径也走 FLA**（v1 明令训练用参考）。FLA `causal_conv1d` 是 autograd 包装；
   fp32 前向/梯度对参考实现 1.9e-6 / 1.2e-7，bf16 为舍入级（verify 里卡相对误差）。
3. **varlen / packing 打通**。transformers 的 GDN 把 `cu_seq_lens_q` 塞在 `**kwargs` 里传给
   卷积（modeling_qwen3_5.py:576-582），v2 之前直接忽略 ⇒ packed 序列**跨样本串状态**、静默算错。
   v3 显式映射为 FLA 的 `cu_seqlens`；实测分段 vs 逐段参考 max|diff|≈2e-3（bf16），
   而"不分段"的朴素全段卷积差 6.8e-2 —— 说明边界确实被切开了。
4. **decode 走 FLA update**，布局必须 `x=(B,1,C)`、`conv_state=(B,C,K)`。传 `(B,C,1)`
   会因 kernel 按 `stride(2)` 取通道而越界读 → `illegal memory access`（实测）。
   `conv_state` 宽度必须等于卷积核宽 K，否则同样越界；两者都在入口校验，不满足退参考实现。
5. **熔断**：任何一条通路失败，本进程内永久停用该通路并记下异常原文（`diagnostics()`）。
   v1 的 `except` 每步都吞一次异常，单次调用被 traceback 格式化拖到参考实现的 8 倍。

## 用法
    set PYTHONPATH=train\\scripts
    train\\.venv\\Scripts\\python.exe train/lines/_shared/scripts/verify_causal_conv1d.py

## 开关
    CC1D_FLA_FWD=0        关掉 forward 的 FLA（回参考实现）
    CC1D_FLA_UPDATE=0     关掉 decode 的 FLA
    CC1D_ZEROCOPY=0       强制走拷贝（排查布局相关问题时用）
"""
import os
import logging

import torch
import torch.nn.functional as F

_LOG = logging.getLogger(__name__)


def _env_flag(name, default="1"):
    v = os.environ.get(name, default)
    return str(v).strip().lower() not in ("0", "false", "off", "no", "")


_USE_FWD = _env_flag("CC1D_FLA_FWD")
# decode 的 FLA kernel 在本机 GPU 上 GPU 时间更小，但每次调用要多付 ~0.1ms 的 CPU 侧开销，
# 而 decode 里这一步只占单步的千分之几 —— 模型级实测反而更慢（见 CAUSAL-CONV1D.md），
# 所以默认关；要试 `CC1D_FLA_UPDATE=1`。
_USE_UPD = _env_flag("CC1D_FLA_UPDATE", "0")
_ZEROCOPY = _env_flag("CC1D_ZEROCOPY")

_fwd_raw = None
_fwd_autograd = None
_upd_raw = None
_import_err = None

try:
    from fla.modules.causal_conv1d import causal_conv1d_fwd as _fwd_raw
    from fla.modules.causal_conv1d import causal_conv1d as _fwd_autograd
    from fla.modules.causal_conv1d import causal_conv1d_update as _upd_raw
except Exception as _e:                                  # FLA 缺失 ⇒ 全参考实现
    _import_err = repr(_e)

_HAS_FLA = _fwd_raw is not None and _upd_raw is not None

_state = {
    "fwd_off": not (_HAS_FLA and _USE_FWD),
    "upd_off": not (_HAS_FLA and _USE_UPD),
    "fwd_err": None,
    "upd_err": None,
    "fwd_calls": 0,
    "upd_calls": 0,
    "zerocopy_hits": 0,
    "copy_hits": 0,
    "varlen_calls": 0,
    "import_err": _import_err,
    "last_kwargs": [],
}

ACT = {
    "silu": F.silu, "swish": F.silu, "gelu": F.gelu,
    "relu": F.relu, "sigmoid": torch.sigmoid,
}


def _act(x, activation):
    if not activation:
        return x
    fn = ACT.get(str(activation).lower())
    return fn(x) if fn is not None else None


# ---------------------------------------------------------------- 参考实现
def _ref_fn(hidden_states, weight, bias=None, activation=None):
    """等价于 transformers 的 torch 兜底实现（B,C,T 布局；可吃非连续视图）。"""
    _, hidden_size, seq_len = hidden_states.shape
    padding = weight.shape[-1] - 1
    out = F.conv1d(
        hidden_states.to(weight.dtype),
        weight=weight.unsqueeze(1),
        bias=bias,
        padding=padding,
        groups=hidden_size,
    )[:, :, :seq_len]
    if activation is not None:
        a = _act(out, activation)
        out = a if a is not None else out
    return out.to(hidden_states.dtype)


def _ref_update(hidden_states, conv_state, weight, bias=None, activation=None):
    """等价于 transformers 兜底实现（含 conv_state 原地更新）。"""
    _, hidden_size, seq_len = hidden_states.shape
    state_len = conv_state.shape[-1]
    new = torch.cat([conv_state, hidden_states], dim=-1).to(weight.dtype)
    conv_state.copy_(new[:, :, -state_len:])
    out = F.conv1d(new, weight.unsqueeze(1), bias, padding=0, groups=hidden_size)[:, :, -seq_len:]
    if activation is not None:
        a = _act(out, activation)
        out = a if a is not None else out
    return out.to(hidden_states.dtype)


# ---------------------------------------------------------------- 布局
def _channel_last(t):
    """(B,C,T) 视图 + 通道 stride==1 ⇒ 内存本就是 (B,T,C)，转置回去是零拷贝。"""
    return t.stride(1) == 1 and t.stride(-1) == t.shape[1]


def _to_btc(t):
    if _ZEROCOPY and _channel_last(t):
        _state["zerocopy_hits"] += 1
        return t.transpose(1, 2), True
    _state["copy_hits"] += 1
    return t.transpose(1, 2).contiguous(), False


def _trip(kind, exc):
    msg = f"{type(exc).__name__}: {exc}".splitlines()[0][:400]
    if kind == "fwd":
        _state["fwd_off"] = True
        _state["fwd_err"] = msg
        _LOG.warning("[causal_conv1d] FLA forward 停用（本进程）：%s → 参考实现", msg)
    else:
        _state["upd_off"] = True
        _state["upd_err"] = msg
        _LOG.warning("[causal_conv1d] FLA update 停用（本进程）：%s → 参考实现", msg)


def _varlen_offsets(cu_seqlens, cu_seq_lens_q, device):
    cu = cu_seqlens if cu_seqlens is not None else cu_seq_lens_q
    if cu is None:
        return None
    if not torch.is_tensor(cu):
        cu = torch.as_tensor(cu, dtype=torch.int32)
    return cu.to(device=device, dtype=torch.int32)


# ---------------------------------------------------------------- 入口
def causal_conv1d_fn(
    hidden_states,
    weight,
    bias=None,
    activation=None,
    cu_seqlens=None,
    cu_seq_lens_q=None,
    cu_seq_lens_k=None,
    max_length_q=None,
    seq_idx=None,
    chunk_indices=None,
    **kwargs,
):
    """transformers 侧签名：(B,C,T) + weight (C,W)；packing 时带 cu_seq_lens_q。

    注意：transformers 的 `use_kernel_func_from_hub_with_fallback` 会按**本函数的形参名**
    过滤 kwargs（`kwargs = {k:v for k,v in kwargs.items() if k in applicable_params}`），
    所以 cu_seq_lens_* 必须显式列在形参里 —— 只写 **kwargs 会被过滤掉、varlen 静默失效。
    """
    _state["last_kwargs"] = sorted(kwargs.keys())
    if activation is not None and str(activation).lower() not in ACT:
        return _ref_fn(hidden_states, weight, bias, activation)

    if not _state["fwd_off"] and hidden_states.is_cuda and weight.is_cuda:
        try:
            x, _ = _to_btc(hidden_states)                                  # (B,T,C)
            w = weight.reshape(weight.shape[0], weight.shape[-1])
            if not w.is_contiguous():
                w = w.contiguous()
            cu = _varlen_offsets(cu_seqlens, cu_seq_lens_q, hidden_states.device)
            if cu is not None and x.shape[0] != 1:
                raise ValueError(f"varlen 需要 batch=1，得到 {tuple(x.shape)}")

            need_grad = torch.is_grad_enabled() and (
                hidden_states.requires_grad
                or weight.requires_grad
                or (bias is not None and bias.requires_grad)
            )
            extra = {} if cu is None else {"cu_seqlens": cu, "cu_seqlens_cpu": cu.cpu()}
            fn = _fwd_autograd if (need_grad and _fwd_autograd is not None) else _fwd_raw
            out = fn(x, w, bias, None, activation=activation, **extra)
            out = out[0] if isinstance(out, tuple) else out

            _state["fwd_calls"] += 1
            if cu is not None:
                _state["varlen_calls"] += 1
            return out.transpose(1, 2)                                     # (B,C,T) 视图，不搬数据
        except Exception as e:                                             # noqa: BLE001
            _trip("fwd", e)
    return _ref_fn(hidden_states, weight, bias, activation)


def causal_conv1d_update(hidden_states, conv_state, weight, bias=None, activation=None, **kwargs):
    """decode 用；语义含 conv_state 原地更新。FLA 要求 x=(B,1,C)、state=(B,C,K)。"""
    if activation is not None and str(activation).lower() not in ACT:
        return _ref_update(hidden_states, conv_state, weight, bias, activation)

    _, _, seq_len = hidden_states.shape
    if seq_len != 1:                                                       # FLA update 只覆盖单 token
        return _ref_update(hidden_states, conv_state, weight, bias, activation)
    if conv_state.shape[-1] != weight.shape[-1]:                           # kernel 读 cache 宽度=K
        return _ref_update(hidden_states, conv_state, weight, bias, activation)

    if not _state["upd_off"] and hidden_states.is_cuda and weight.is_cuda:
        try:
            x, _ = _to_btc(hidden_states)                                  # (B,1,C)
            w = weight.reshape(weight.shape[0], weight.shape[-1])
            if not w.is_contiguous():
                w = w.contiguous()
            y, _ = _upd_raw(x, conv_state, None, w, bias, activation=activation)
            _state["upd_calls"] += 1
            return y.transpose(1, 2)                                       # (B,C,1) 视图
        except Exception as e:                                             # noqa: BLE001
            _trip("upd", e)
    return _ref_update(hidden_states, conv_state, weight, bias, activation)


def causal_conv1d_varlen_fn(hidden_states, weight, bias=None, activation=None, **kwargs):
    return causal_conv1d_fn(hidden_states, weight, bias, activation, **kwargs)


def diagnostics():
    return dict(_state)


__all__ = [
    "causal_conv1d_fn", "causal_conv1d_update", "causal_conv1d_varlen_fn", "diagnostics",
]

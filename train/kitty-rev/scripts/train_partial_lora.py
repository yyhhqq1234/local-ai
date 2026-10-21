#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""train_partial_lora.py -- train an incremental LoRA on layers [from..to] of a
27B checkpoint, using precomputed activations as the input instead of embeddings.

Pipeline
    cloud (>=24 GiB) : precompute_activations.py --cut 48   -> act-cache/*.pt
    cloud            : split_merge_layers.py                -> layer_NN.safetensors + head
    local (12 GiB)   : this script                          -> adapter (only layers from..to)

Why layers only
    The 27B 4bit weights are 12.6 GiB and do not fit a 10.5 GiB budget.  Layers
    0..from-1 are never needed at training time because their output is already
    in the activation cache.  So we build the full skeleton on the `meta` device
    (zero RAM), load only layer_{from..to} + norm + lm_head, then drop the
    ModuleList entries before `from`.  Layer objects keep their original
    `layer_idx`, so per-layer attention type / sliding-window logic stays right.

LoRA attach points (measured, do not assume 7 per layer)
    mlp.{gate,up,down}_proj exist on all 64 layers; {q,k,v,o}_proj exist only on
    the 16 full-attention layers (every 4th, i.e. 51/55/59/63 inside 48..63).
    target_modules is therefore a regex, and attach counts are reported.

Loss
    `--mask none` (default) reproduces `train_kitty.py`: labels == input_ids,
    whole-sequence loss (trl 1.16.0 assistant_only_loss defaults to False and
    the cloud run never overrides it).  `--mask assistant` masks everything
    outside assistant spans.  Padded positions are ALWAYS -100.

Usage
    # 3-step smoke on a tiny random model + fake act-cache (no 27B, no weights)
    python train_partial_lora.py --smoke 3 --out out-local-smoke --act-cache <fake>

    # real run
    python train_partial_lora.py --layer-dir train/local-pack/merged-layers \
        --from 48 --to 63 --act-cache train/local-pack/act-cache --ctx 512 \
        --lora-r 16 --bs 1 --ga 8 --max-steps 200 --out train/kitty-rev/out-local
"""
import argparse
import glob
import json
import math
import os
import random
import sys
import time

import torch
import torch.nn.functional as F


def human(n):
    return f"{n / 2 ** 30:.2f} GiB" if n >= 2 ** 30 else f"{n / 2 ** 20:.1f} MiB"


def parse():
    ap = argparse.ArgumentParser(description="partial-layer LoRA on cached activations")
    ap.add_argument("--layer-dir", default=None,
                    help="split_merge_layers.py 的输出目录（每层一个 layer_NN.safetensors）")
    ap.add_argument("--base-shards", default=None,
                    help="直接吃原始 HF 分片目录（含 *.safetensors + *.index.json），按层懒读；"
                         "用于不预拆层的冒烟，与 --layer-dir 二选一")
    ap.add_argument("--from", dest="frm", type=int, default=48, help="起始层（含）")
    ap.add_argument("--to", dest="to", type=int, default=63, help="结束层（含）")
    ap.add_argument("--head", default=None, help="head.safetensors（默认 <layer-dir>/head.safetensors）")
    ap.add_argument("--act-cache", default=None, help="单源 act-cache 目录（*.pt）")
    ap.add_argument("--data-mix", default="",
                    help='多源加权，path 指 act-cache 目录："re:act-re-train:3,route:act-route-train:2"'
                         '（name:path[:weight]，weight 缺省 1.0，路径含 Windows 盘符也安全）')
    ap.add_argument("--eval-cache", default="",
                    help='验证集 act-cache，同 --data-mix 语法但不带权重："re:act-re-val,route:act-route-val"')
    ap.add_argument("--eval-by-cat", action="store_true",
                    help="训练前后按类别各算一次 train/val loss（§14.8 的可证伪判据）")
    ap.add_argument("--refusal-cache", default="",
                    help="应配合样本的 act-cache（同 --data-mix 语法，算 refusal 投影）")
    ap.add_argument("--refusal-directions", default="",
                    help="refusal_probe.py --mode repr 产出的 *.direction.pt")
    ap.add_argument("--eval-every", type=int, default=10,
                    help="每 N 个 optimizer step 评一次 val loss（默认 10；0=关闭）")
    ap.add_argument("--early-stop-patience", type=int, default=3,
                    help="val loss 连续 N 次不改善即停（默认 3；0=关闭）")
    ap.add_argument("--ctx", type=int, default=512)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--bs", type=int, default=1, help="单步样本数（T 不一，>1 会 pad 到组内最大）")
    ap.add_argument("--ga", type=int, default=8, help="梯度累积步数")
    ap.add_argument("--max-steps", type=int, default=200, help="优化步上限（按 ga 归一后的 optimizer step）")
    ap.add_argument("--epochs", type=float, default=0, help=">0 时按 epoch 跑，覆盖 --max-steps")
    ap.add_argument("--lr", type=float, default=5e-5,
                    help="默认 5e-5：小数据配高 lr = 快速拟合 + 快速遗忘；显式传参仍优先")
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--max-grad-norm", type=float, default=0.3)
    ap.add_argument("--max-vram-gb", type=float, default=10.0,
                    help="加载完层+head 后若显存超过该值立即 FATAL 退出（默认 10 GiB，硬红线）")
    ap.add_argument("--no-grad-checkpoint", action="store_true",
                    help="关闭逐层梯度检查点（默认开启：gdn 的 chunk_gated_delta_rule 走参考实现时会存大量中间激活）")
    ap.add_argument("--ce-chunk", type=int, default=128,
                    help="交叉熵沿 token 维分块大小（默认 128）；vocab=248320 时整块 fp32 单份就 500 MiB")
    ap.add_argument("--dtype", choices=["4bit", "bf16"], default="4bit")
    ap.add_argument("--out", required=True, help="adapter 输出目录")
    ap.add_argument("--resume", default=None, help="从该 adapter 目录续训")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=0, help="只用前 N 个样本（调试）")
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--save-every", type=int, default=0, help="每 N optimizer step 落一次 checkpoint（0=只在结束）")
    ap.add_argument("--dry-run", action="store_true", help="只报计划，不建模型不训练")
    ap.add_argument("--smoke", type=int, default=0,
                    help=">0 时用 tiny 随机模型跑 N 步假数据冒烟（不读 27B、不读 layer 文件）")
    return ap.parse_args()


# --------------------------------------------------------------------------- #
# tiny model for smoke
# --------------------------------------------------------------------------- #
def tiny_config(src_cfg_path=None):
    from transformers import AutoConfig
    if src_cfg_path and os.path.exists(src_cfg_path):
        cfg = AutoConfig.from_pretrained(os.path.dirname(src_cfg_path), trust_remote_code=True)
    else:
        from transformers import Qwen3_5Config as _C  # noqa
        cfg = None
    if cfg is None:
        raise SystemExit("[smoke] 需要 --layer-dir 指向含 config.json 的目录来派生 tiny 配置")
    t = getattr(cfg, "text_config", cfg)
    t.hidden_size = 256
    t.intermediate_size = 512
    t.num_hidden_layers = 2
    t.num_attention_heads = 4
    t.num_key_value_heads = 2
    t.head_dim = 64
    t.vocab_size = 1024
    t.layer_types = ["linear_attention", "full_attention"]
    return cfg


# --------------------------------------------------------------------------- #
# weight loading
# --------------------------------------------------------------------------- #
def read_sd(path):
    from safetensors import safe_open
    sd = {}
    with safe_open(path, framework="pt", device="cpu") as f:
        for k in f.keys():
            sd[k] = f.get_tensor(k)
    return sd


# --------------------------------------------------------------------------- #
# layer sources
#   SplitSource : <dir>/layer_NN.safetensors + head.safetensors   (post-split)
#   ShardSource : original HF shards, located per layer via weight_map
# Both expose the same 5 methods, so the training path is identical -- the
# local-pack directory and the raw base directory are interchangeable.
# --------------------------------------------------------------------------- #
def _is_final_norm(k):
    """The language model's FINAL norm -- not a per-layer norm, not a vision norm.

    Caught the hard way: `model.visual.merger.norm.weight` (hidden 1152) also
    ends with '.norm.weight' and got picked instead of
    `model.language_model.norm.weight` (hidden 5120), which then died inside
    Qwen3_5RMSNorm with 'tensor a (5120) must match tensor b (1152)'.
    """
    if not k.endswith(".norm.weight"):
        return False
    if ".layers." in k:
        return False
    low = k.lower()
    if ".visual." in low or "vision" in low:
        return False
    return True


class SplitSource:
    kind = "split"

    def __init__(self, root):
        self.root = os.path.abspath(root)
        if not os.path.exists(os.path.join(self.root, "config.json")):
            raise SystemExit(f"[FATAL] 缺少 {self.root}/config.json")
        self.layer_prefix = "model.language_model.layers."
        sp = os.path.join(self.root, "layers_index.json")
        if os.path.exists(sp):
            self.layer_prefix = json.load(open(sp, encoding="utf-8")).get(
                "layer_prefix", self.layer_prefix)
        self.head_path = os.path.join(self.root, "head.safetensors")
        if not os.path.exists(self.head_path):
            raise SystemExit(f"[FATAL] 缺少 {self.head_path}")

    def _p(self, i):
        return os.path.join(self.root, f"layer_{i:02d}.safetensors")

    def config(self):
        from transformers import AutoConfig
        return AutoConfig.from_pretrained(self.root, trust_remote_code=True)

    def count_layers(self):
        return len([f for f in os.listdir(self.root)
                    if f.startswith("layer_") and f.endswith(".safetensors")])

    def has_layer(self, i):
        return os.path.exists(self._p(i))

    def bytes_of(self, idxs):
        return sum(os.path.getsize(self._p(i)) for i in idxs if self.has_layer(i))

    def head_bytes(self):
        return os.path.getsize(self.head_path)

    def read_layer(self, i):
        return read_sd(self._p(i)), f"{self.layer_prefix}{i}."

    def head(self):
        sd = read_sd(self.head_path)
        norm_key = next((k for k in sd if _is_final_norm(k)), None)
        head_key = next((k for k in sd if k.endswith("lm_head.weight")), None)
        if not norm_key or not head_key:
            raise SystemExit(f"[FATAL] head.safetensors 缺 norm/lm_head: {list(sd)[:6]}")
        return sd, norm_key, head_key


class ShardSource:
    kind = "shards"

    def __init__(self, root):
        import re
        from safetensors import safe_open
        self.root = os.path.abspath(root)
        if not os.path.exists(os.path.join(self.root, "config.json")):
            raise SystemExit(f"[FATAL] 缺少 {self.root}/config.json")
        idxs = [n for n in os.listdir(self.root) if n.endswith(".safetensors.index.json")]
        if not idxs:
            raise SystemExit(f"[FATAL] {self.root} 下没有 *.index.json（分片目录必需）")
        self.wm = json.load(open(os.path.join(self.root, idxs[0]), encoding="utf-8"))["weight_map"]
        cand = {}
        for k in self.wm:
            if k.startswith("mtp."):
                continue
            m = re.match(r"^(.*\.layers\.)(\d+)\.", k)
            if m:
                cand[m.group(1)] = cand.get(m.group(1), 0) + 1
        if not cand:
            raise SystemExit("[FATAL] 找不到 layer 张量前缀")
        self.layer_prefix = max(cand, key=cand.get)
        self._nbytes = {}
        self._safe = safe_open  # keep the symbol for reuse
        print(f"[src] shards={len(set(self.wm.values()))} keys={len(self.wm)} "
              f"layer_prefix={self.layer_prefix!r}")

    def config(self):
        from transformers import AutoConfig
        return AutoConfig.from_pretrained(self.root, trust_remote_code=True)

    def count_layers(self):
        idx = set()
        for k in self.wm:
            if k.startswith(self.layer_prefix):
                idx.add(int(k[len(self.layer_prefix):].split(".")[0]))
        return len(idx)

    def has_layer(self, i):
        pref = f"{self.layer_prefix}{i}."
        return any(k.startswith(pref) for k in self.wm)

    def _tensor_bytes(self):
        """Exact tensor sizes from safetensors headers (8-byte len + JSON)."""
        if self._nbytes:
            return self._nbytes
        for sh in sorted(set(self.wm.values())):
            p = os.path.join(self.root, sh)
            with open(p, "rb") as fh:
                n = int.from_bytes(fh.read(8), "little")
                hdr = json.loads(fh.read(n))
            for k, v in hdr.items():
                if k == "__metadata__":
                    continue
                off = v.get("data_offsets")
                if off:
                    self._nbytes[k] = int(off[1]) - int(off[0])
        return self._nbytes

    def bytes_of(self, idxs):
        nb = self._tensor_bytes()
        total = 0
        for i in idxs:
            pref = f"{self.layer_prefix}{i}."
            total += sum(v for k, v in nb.items() if k.startswith(pref))
        return total

    def head_bytes(self):
        nb = self._tensor_bytes()
        return sum(v for k, v in nb.items()
                   if _is_final_norm(k) or k.endswith("lm_head.weight"))

    def _read_keys(self, keys):
        sd = {}
        for sh in sorted({self.wm[k] for k in keys}):
            sub = [k for k in keys if self.wm[k] == sh]
            with self._safe(os.path.join(self.root, sh), framework="pt", device="cpu") as f:
                for k in sub:
                    sd[k] = f.get_tensor(k)
        return sd

    def read_layer(self, i):
        pref = f"{self.layer_prefix}{i}."
        keys = [k for k in self.wm if k.startswith(pref)]
        if not keys:
            raise SystemExit(f"[FATAL] shard 里找不到 layer {i}")
        return self._read_keys(keys), pref

    def head(self):
        want = [k for k in self.wm
                if _is_final_norm(k) or k.endswith("lm_head.weight")]
        if not want:
            raise SystemExit("[FATAL] shard 里找不到 norm / lm_head")
        sd = self._read_keys(want)
        norm_key = next((k for k in sd if _is_final_norm(k)), None)
        head_key = next((k for k in sd if k.endswith("lm_head.weight")), None)
        if not norm_key or not head_key:
            raise SystemExit(f"[FATAL] 取到 {list(sd)}，仍缺 norm/lm_head")
        return sd, norm_key, head_key


def make_source(a):
    if a.base_shards:
        return ShardSource(a.base_shards)
    if a.layer_dir:
        return SplitSource(a.layer_dir)
    raise SystemExit("[FATAL] 需要 --layer-dir 或 --base-shards（或用 --smoke N）")


def load_layer(layer, sd, prefix, dev, quant):
    """Fill one decoder layer from `sd` (keys prefixed by `prefix`).

    Two passes, because the skeleton lives on `meta` and *every* parameter must
    be replaced by a real one:
      1) nn.Linear  -> bnb Linear4bit (or plain bf16 Linear when quant=False)
      2) everything else (norms, conv1d, A_log, dt_bias, ...) -> fresh Parameter
    An earlier version skipped every name ending in `.weight`, which silently
    left input_layernorm/post_attention_layernorm/linear_attn.norm/conv1d on
    meta and blew up mid-forward with
    'Tensor on device meta is not on the expected device cuda:0'.
    """
    import torch.nn as nn
    handled = set()
    n_linear = 0

    for name, mod in list(layer.named_modules()):
        if not isinstance(mod, nn.Linear) or not name:
            continue
        wkey = f"{prefix}{name}.weight"
        if wkey not in sd:
            continue
        w = sd[wkey].to(torch.bfloat16)
        bkey = f"{prefix}{name}.bias"
        b = sd.get(bkey)
        parent = layer.get_submodule(name.rsplit(".", 1)[0]) if "." in name else layer
        attr = name.rsplit(".", 1)[-1]
        if quant:
            import bitsandbytes as bnb
            lin = bnb.nn.Linear4bit(mod.in_features, mod.out_features, bias=b is not None,
                                    compute_dtype=torch.bfloat16, quant_type="nf4",
                                    compress_statistics=True, device=dev)
            lin.weight = bnb.nn.Params4bit(w.contiguous(), requires_grad=False,
                                           quant_type="nf4", blocksize=64,
                                           compress_statistics=True).to(dev)
            if b is not None:
                lin.bias = nn.Parameter(b.to(torch.bfloat16).to(dev), requires_grad=False)
            setattr(parent, attr, lin)
        else:
            lin = nn.Linear(mod.in_features, mod.out_features, bias=b is not None,
                            dtype=torch.bfloat16, device=dev)
            with torch.no_grad():
                lin.weight.copy_(w)
                if b is not None:
                    lin.bias.copy_(b.to(torch.bfloat16))
            setattr(parent, attr, lin)
        handled.add(f"{name}.weight")
        if b is not None:
            handled.add(f"{name}.bias")
        n_linear += 1

    n_plain = 0
    missing = []
    for name, p in list(layer.named_parameters(recurse=True)):
        if name in handled:
            continue
        key = f"{prefix}{name}"
        if key not in sd:
            missing.append(name)
            continue
        parent = layer.get_submodule(name.rsplit(".", 1)[0]) if "." in name else layer
        attr = name.rsplit(".", 1)[-1]
        setattr(parent, attr, nn.Parameter(sd[key].to(torch.bfloat16).to(dev),
                                           requires_grad=False))
        n_plain += 1

    if missing:
        print(f"    [warn] {len(missing)} 个参数在 sd 里没有对应键: {missing[:4]}")
    # last safety net: nothing may still live on meta
    still_meta = [n for n, p in layer.named_parameters() if p.device.type == "meta"]
    if still_meta:
        raise SystemExit(f"[FATAL] 仍有 {len(still_meta)} 个参数在 meta 上: {still_meta[:4]}")
    return n_linear, n_plain


def build_skeleton(cfg):
    """Full 64-layer model on the meta device: zero RAM, no weights."""
    from transformers import AutoModelForCausalLM
    with torch.device("meta"):
        model = AutoModelForCausalLM.from_config(cfg, trust_remote_code=True)
    return model


def materialize_rotary(bb, dev):
    """The skeleton lives on `meta`, so `bb.rotary_emb`'s inv_freq buffer has no
    storage -- any attempt to compute position embeddings dies with
    'Cannot copy out of meta tensor; no data!'.  And Qwen3_5DecoderLayer.forward
    takes `position_embeddings` as a REQUIRED parameter, so we cannot skip it.
    Rebuild the (tiny) rotary module on a real device.
    """
    re_ = getattr(bb, "rotary_emb", None)
    if re_ is None:
        print("[warn] backbone 没有 rotary_emb，position_embeddings 将无法构造")
        return None
    cfg = getattr(bb, "config", None)
    cls = type(re_)
    last = None
    for ctor in (lambda: cls(cfg), lambda: cls(config=cfg)):
        try:
            new = ctor().to(dev)
            bb.rotary_emb = new
            print(f"[rotary] materialized {cls.__name__} on {dev}")
            return new
        except Exception as e:
            last = e
    print(f"[warn] rotary 重建失败：{last}")
    return None



def backbone_of(model):
    """Return the text model that owns `.layers` / `.norm` / `.rotary_emb`.

    Measured hierarchy on this build:
        Qwen3_5ForCausalLM
          .model            -> Qwen3_5TextModel   (embed_tokens, layers, norm, rotary_emb)
          .lm_head          -> Linear
    After peft wrapping the chain gains PeftModel/LoraModel hops, so search by
    shape instead of assuming a fixed path.
    """
    for _name, mod in model.named_modules():
        if hasattr(mod, "layers") and hasattr(mod, "norm"):
            return mod
    cur = model
    for _ in range(6):
        nxt = getattr(cur, "model", None) or getattr(cur, "base_model", None)
        if nxt is None or nxt is cur:
            break
        cur = nxt
        if hasattr(cur, "layers") and hasattr(cur, "norm"):
            return cur
    raise SystemExit("[FATAL] 找不到带 layers/norm 的 text backbone")


# --------------------------------------------------------------------------- #
# dataset
# --------------------------------------------------------------------------- #
class ActCache:
    def __init__(self, root, ctx, limit=0):
        self.files = sorted(glob.glob(os.path.join(root, "*.pt")),
                            key=lambda p: (len(os.path.basename(p)), p))
        if limit:
            self.files = self.files[:limit]
        if not self.files:
            raise SystemExit(f"[FATAL] {root} 下没有 *.pt")
        self.ctx = ctx

    def __len__(self):
        return len(self.files)

    def get(self, i):
        d = torch.load(self.files[i], map_location="cpu", weights_only=False)
        h = d["hidden"]
        lab = d["labels"]
        att = d.get("attn")
        if h.dim() == 2:
            h = h.unsqueeze(0)
        if lab.dim() == 1:
            lab = lab.unsqueeze(0)
        T = min(int(h.shape[1]), self.ctx)
        h, lab = h[:, :T], lab[:, :T]
        if att is not None:
            if att.dim() == 1:
                att = att.unsqueeze(0)
            att = att[:, :T]
        else:
            att = torch.ones_like(lab)
        return h.to(torch.bfloat16), lab.long(), att.long()


def parse_mix_item(part, default_weight=1.0):
    """`name:path[:weight]` -> (name, path, weight).

    Splits on the LAST colon for the weight so a Windows path
    (`re:C:\\data\\act-re:3`) survives, and falls back to a single colon for the
    name so plain paths work too.
    """
    part = part.strip()
    w = default_weight
    if ":" in part:
        head, tail = part.rsplit(":", 1)
        try:
            w = float(tail)
            part = head
        except ValueError:
            pass
    if ":" in part:
        name, root = part.split(":", 1)
        name, root = name.strip(), root.strip()
    else:
        root = part
        base = os.path.basename(os.path.normpath(part)) or "src"
        name = base
    if not root:
        raise SystemExit(f"[FATAL] --data-mix 解析失败: {part!r}")
    return name, root, w


def build_specs(mix, act_cache=None, weights=""):
    if mix:
        return [parse_mix_item(p) for p in mix.split(",") if p.strip()]
    if act_cache:
        if weights:
            out = []
            for p in weights.split(","):
                p = p.strip()
                if not p:
                    continue
                out.append(parse_mix_item(p))
            roots = [x.strip() for x in act_cache.split(",") if x.strip()]
            if len(roots) == len(out):
                return [(n, r, w) for (n, _, w), r in zip(out, roots)]
            return [(parse_mix_item(r)[0], r, 1.0) for r in roots]
        return [parse_mix_item(act_cache)]
    raise SystemExit("[FATAL] 需要 --act-cache 或 --data-mix")


class MultiCache:
    """Several act-cache directories with per-source sampling weights.

    Why: reverse-engineering rows are ~9% of the mix (kb-re 194 + action-reverse
    165 out of 3908), so uniform sampling would drown them -- a batch would
    almost never contain one.  Weighting per SOURCE (not per file) lets
    `--data-mix "re:act-re-train:3,route:act-route-train:2"` push their effective
    share to 25-40%, which is §14.4 case 3's prescription.

    Sampling is with replacement, probability proportional to source weight.
    """

    def __init__(self, specs, ctx, limit=0):
        self.specs = []
        for name, root, w in specs:
            files = sorted(glob.glob(os.path.join(root, "*.pt")),
                           key=lambda p: (len(os.path.basename(p)), p))
            if limit:
                files = files[:limit]
            if not files:
                raise SystemExit(f"[FATAL] 源 {name} 下没有 *.pt: {root}")
            self.specs.append({"name": name, "root": os.path.abspath(root),
                               "weight": float(w), "files": files})
        self.ctx = ctx
        tot = sum(s["weight"] for s in self.specs) or 1.0
        self.probs = [s["weight"] / tot for s in self.specs]
        self.names = [s["name"] for s in self.specs]

    def __len__(self):
        return sum(len(s["files"]) for s in self.specs)

    def summary(self):
        tot = sum(len(s["files"]) * s["weight"] for s in self.specs) or 1.0
        return {s["name"]: {"root": s["root"], "files": len(s["files"]),
                            "weight": s["weight"],
                            "effective_share": round(len(s["files"]) * s["weight"] / tot, 4)}
                for s in self.specs}

    @staticmethod
    def _load(path, ctx):
        d = torch.load(path, map_location="cpu", weights_only=False)
        h, lab = d["hidden"], d["labels"]
        att = d.get("attn")
        if h.dim() == 2:
            h = h.unsqueeze(0)
        if lab.dim() == 1:
            lab = lab.unsqueeze(0)
        T = min(int(h.shape[1]), ctx)
        h, lab = h[:, :T], lab[:, :T]
        if att is None:
            att = torch.ones_like(lab)
        elif att.dim() == 1:
            att = att.unsqueeze(0)[:, :T]
        else:
            att = att[:, :T]
        return h.to(torch.bfloat16), lab.long(), att.long()

    def pick(self, rng):
        i = rng.choices(range(len(self.specs)), weights=self.probs)[0]
        s = self.specs[i]
        p = s["files"][rng.randrange(len(s["files"]))]
        return self._load(p, self.ctx), s["name"]

    def of(self, name):
        for s in self.specs:
            if s["name"] == name:
                for p in s["files"]:
                    yield self._load(p, self.ctx)


@torch.no_grad()
def eval_by_cat(forward, train_cache, val_cache, a, dev, max_per_src=24):
    """Per-category train/val loss -- the falsification test of §14.8.

    If val loss does not move in the same direction as train loss, the model
    memorised the subset instead of learning the capability, and the whole
    targeted-training claim fails.  This is the only per-layer attribution we
    can do locally (a 16-layer stub cannot generate 23-answer text).
    """
    out = {}
    names = list(train_cache.names)
    if val_cache is not None:
        names = sorted(set(names) | set(val_cache.names))
    for name in names:
        rec = {}
        for tag, cache in (("train", train_cache), ("val", val_cache)):
            if cache is None or name not in cache.names:
                continue
            losses, n = [], 0
            for h, lab, att in cache.of(name):
                if n >= max_per_src:
                    break
                n += 1
                h = h.to(dev).requires_grad_(False)
                logits = forward(h, att.to(dev), ckpt=False)
                losses.append(float(chunked_ce(logits, lab.to(dev), a.ce_chunk)))
                del logits
            if losses:
                rec[f"{tag}_loss"] = round(sum(losses) / len(losses), 4)
                rec[f"n_{tag}"] = n
        if "train_loss" in rec and "val_loss" in rec and rec["train_loss"] > 0:
            rec["val_vs_train"] = round(rec["val_loss"] / rec["train_loss"], 4)
        out[name] = rec
    return out


def collate(items):
    """Pad to the batch max length; padding positions get label -100."""
    T = max(int(h.shape[1]) for h, _, _ in items)
    H = items[0][0].shape[-1]
    hs, ls, ats = [], [], []
    for h, lab, att in items:
        n = int(h.shape[1])
        pad = T - n
        if pad:
            h = torch.cat([h, torch.zeros(1, pad, H, dtype=h.dtype)], dim=1)
            att = torch.cat([att, torch.zeros(1, pad, dtype=att.dtype)], dim=1)
            lab = torch.cat([lab, torch.full((1, pad), -100, dtype=lab.dtype)], dim=1)
        hs.append(h)
        ls.append(lab)
        ats.append(att)
    return torch.cat(hs, 0), torch.cat(ls, 0), torch.cat(ats, 0)


# --------------------------------------------------------------------------- #
# forward
# --------------------------------------------------------------------------- #
def _run_layer(layer, h, pe, pos):
    out = layer(h, position_embeddings=pe, position_ids=pos, use_cache=False)
    return out[0] if isinstance(out, (tuple, list)) else out


@torch.no_grad()
def refusal_projection(forward, cache, direction_path, a, dev, max_n=24):
    """Mean projection of "should comply" hidden states onto the refusal direction.

    Why this and not refusal_rate: a 16-layer stub cannot generate text, so the
    textual refusal probe is unmeasurable locally.  The projection is the only
    abliteration signal available here: it moves toward the refuse mean even
    while the text still reads polite.

    Lower (more negative) = further from the refusal side = abliteration kept.
    """
    if not os.path.exists(direction_path):
        raise SystemExit(f"[FATAL] 缺 direction 文件: {direction_path}")
    d = torch.load(direction_path, map_location="cpu", weights_only=False)
    dn = d["direction"].float().reshape(-1).to(dev)
    dn = dn / (dn.norm() + 1e-9)
    vals, n = [], 0
    for name in cache.names:
        for h, lab, att in cache.of(name):
            hid = forward(h.to(dev), att.to(dev), ckpt=False, ret="hidden")
            v = hid[0, -1].float()
            if v.numel() != dn.numel():
                raise SystemExit(f"[FATAL] hidden 维度 {v.numel()} != direction {dn.numel()}")
            vals.append(float(v @ dn))
            n += 1
            if n >= max_n:
                break
        if n >= max_n:
            break
    return {"n": n, "proj_mean": round(sum(vals) / max(1, len(vals)), 6),
            "baseline_proj_comply": d.get("proj_comply"),
            "direction_file": os.path.abspath(direction_path)}


def make_forward(bb, head_weight, dev):
    layers = list(bb.layers)
    norm = bb.norm

    def _pos_emb(h, position_ids):
        re_ = getattr(bb, "rotary_emb", None)
        if re_ is None:
            return None
        try:
            return re_(h, position_ids)
        except Exception:
            return None

    def forward(hidden, attn, ckpt=True, ret="logits"):
        """ret="logits" (default) or "hidden" for the refusal-projection probe.

        The projection needs the post-norm hidden state, not the vocabulary
        projection; computing it here avoids a second forward path.
        """
        B, T, _ = hidden.shape
        pos = torch.arange(T, device=dev).unsqueeze(0).expand(B, T)
        pe = _pos_emb(hidden, pos)
        if pe is None:
            raise SystemExit("[FATAL] position_embeddings 不可用（rotary 未 materialize 或签名不匹配）")
        h = hidden
        use_ck = ckpt and h.requires_grad
        for layer in layers:
            if use_ck:
                h = torch.utils.checkpoint.checkpoint(
                    _run_layer, layer, h, pe, pos, use_reentrant=False)
            else:
                h = _run_layer(layer, h, pe, pos)
        h = norm(h)
        if ret == "hidden":
            return h
        return F.linear(h, head_weight)

    return forward


def chunked_ce(logits, labels, chunk=128):
    """Token-chunked cross entropy.

    The full-vocab path materialises [T-1, 248320] fp32 twice (forward logits +
    backward buffer) which alone is ~1 GiB at ctx 512 and was a major part of
    the 13.1 GiB peak.  Chunking keeps only [chunk, V] fp32 alive at a time;
    reduction='sum' + explicit count keeps the value identical.
    """
    V = logits.shape[-1]
    T = logits.shape[1] - 1          # number of predicted positions
    total = torch.zeros((), dtype=torch.float32, device=logits.device)
    cnt = 0
    for i in range(0, T, chunk):
        j = min(i + chunk, T)        # clamp: without this the last chunk sends
        sl = logits[:, i:j, :].float()   # [.., i:j, ..] against labels[i+1:j+1]
        tgt = labels[:, i + 1:j + 1]     # whose slice runs past T (512 vs 511)
        total = total + F.cross_entropy(sl.reshape(-1, V), tgt.reshape(-1),
                                        ignore_index=-100, reduction="sum")
        cnt += int((tgt != -100).sum())
    return total / max(1, cnt)


# --------------------------------------------------------------------------- #
def main():
    a = parse()
    random.seed(a.seed)
    torch.manual_seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cpu":
        print("[warn] 没有 CUDA，将在 CPU 上跑（只适合 smoke/极小模型）")

    # ---------------- smoke: tiny random model, fake cache ----------------
    if a.smoke:
        base_dir = a.base_shards or a.layer_dir
        if not base_dir:
            raise SystemExit("[smoke] 需要 --layer-dir 或 --base-shards 指向含 config.json 的目录")
        cfg = tiny_config(os.path.join(base_dir, "config.json"))
        quant = a.dtype == "4bit"
        print(f"[smoke] tiny cfg: hidden={cfg.text_config.hidden_size} "
              f"layers={cfg.text_config.num_hidden_layers} vocab={cfg.text_config.vocab_size} "
              f"dtype={a.dtype}")
        from transformers import AutoModelForCausalLM
        model = AutoModelForCausalLM.from_config(cfg, trust_remote_code=True).to(dev)
        for p in model.parameters():
            p.requires_grad = False
        head_w = model.lm_head.weight.detach().clone().to(dev)
        model = _attach_lora(model, a)
        forward = make_forward(backbone_of(model), head_w, dev)
        print(f"[smoke] vram_before={torch.cuda.max_memory_allocated() / 2 ** 30:.2f} GiB" if dev == "cuda" else "")
        _fit(model, forward,
             MultiCache(build_specs(a.data_mix, a.act_cache), a.ctx,
                        limit=max(a.bs * 4, 4)), a, dev, steps=a.smoke)
        return 0

    # ---------------- real run ----------------
    src = make_source(a)
    cfg = src.config()
    tcfg = getattr(cfg, "text_config", cfg)
    n_layers = int(getattr(tcfg, "num_hidden_layers", 64))
    cache = MultiCache(build_specs(a.data_mix, a.act_cache), a.ctx, a.limit)
    print(f"[data] 共 {len(cache)} 样本 / {len(cache.names)} 源")
    for nm, s in cache.summary().items():
        print(f"[data]   {nm:10s} files={s['files']:4d} weight={s['weight']:.2f} "
              f"有效占比={s['effective_share'] * 100:.1f}%  {s['root']}")

    missing = [i for i in range(a.frm, a.to + 1) if not src.has_layer(i)]
    if missing:
        raise SystemExit(f"[FATAL] {src.kind} 源缺层 {missing[:8]}（{src.root}）")

    print(f"[plan] source={src.kind}  root={src.root}")
    print(f"[plan] layers {a.frm}..{a.to} of {n_layers}（源内可用 {src.count_layers()} 层）  "
          f"dtype={a.dtype}  samples={len(cache)}  ctx={a.ctx}  bs={a.bs} ga={a.ga}")
    est = src.bytes_of(range(a.frm, a.to + 1))
    hb = src.head_bytes()
    print(f"[plan] 层字节 {human(est)}  head {human(hb)}")
    if a.dry_run:
        print(f"[dry-run] 4bit 后层权重 ≈ {human(est * 0.28)}  + head {human(hb)}"
              f"  ≈ {human(est * 0.28 + hb)}")
        print("[dry-run] 未建模型、未训练")
        return 0

    model = build_skeleton(cfg)
    bb = backbone_of(model)
    if len(bb.layers) != n_layers:
        print(f"[warn] skeleton layers={len(bb.layers)} config={n_layers}，按实际走")
    for i in range(a.frm, a.to + 1):
        t0 = time.time()
        sd, prefix = src.read_layer(i)
        r, p = load_layer(bb.layers[i], sd, prefix, dev, a.dtype == "4bit")
        del sd
        print(f"[load] layer_{i:02d}: linear={r} other={p} {time.time() - t0:.1f}s "
              f"vram={torch.cuda.max_memory_allocated() / 2 ** 30:.2f} GiB")

    sd, norm_key, head_key = src.head()
    with torch.no_grad():
        bb.norm.weight = torch.nn.Parameter(sd[norm_key].to(dev), requires_grad=False)
        head_w = sd[head_key].to(torch.bfloat16).to(dev)
    del sd
    print(f"[load] head ok  norm={norm_key}  head={head_key}  "
          f"vram={torch.cuda.max_memory_allocated() / 2 ** 30:.2f} GiB")

    # drop the layers we do not need (they are meta, so this only frees objects)
    keep = torch.nn.ModuleList([bb.layers[i] for i in range(a.frm, a.to + 1)])
    bb.layers = keep
    print(f"[trim] layers → {len(keep)}（{a.frm}..{a.to}），layer_idx 属性保持原值")
    materialize_rotary(bb, dev)

    if dev == "cuda":
        alloc = torch.cuda.max_memory_allocated() / 2 ** 30
        print(f"[vram] 装载完成 peak={alloc:.2f} GiB  (上限 {a.max_vram_gb} GiB)")
        if alloc > a.max_vram_gb:
            raise SystemExit(f"[FATAL] 显存 {alloc:.2f} GiB 超上限 {a.max_vram_gb} GiB —— 训练前停止，"
                             f"不碰系统")

    for p in model.parameters():
        p.requires_grad = False
    model = _attach_lora(model, a)
    forward = make_forward(backbone_of(model), head_w, dev)

    val_cache = MultiCache(build_specs(a.eval_cache), a.ctx) if a.eval_cache else None
    if val_cache is not None:
        print(f"[data] 验证集 {len(val_cache)} 样本 / {len(val_cache.names)} 源")
    eval_before = None
    if a.eval_by_cat:
        print("[eval] baseline（训前）…")
        eval_before = eval_by_cat(forward, cache, val_cache, a, dev)
        for k, v in eval_before.items():
            print(f"[eval]   before {k:10s} {v}")

    # ---- abliteration probe (§16 measurement, local-only signal) -----------
    ref_cache = None
    ref_before = None
    if a.refusal_cache:
        if not a.refusal_directions:
            print("[refusal][warn] 给了 --refusal-cache 但没给 --refusal-directions，跳过投影")
        else:
            ref_cache = MultiCache(build_specs(a.refusal_cache), a.ctx)
            print(f"[refusal] 应配合集 {len(ref_cache)} 样本 / {len(ref_cache.names)} 源")
            ref_before = refusal_projection(forward, ref_cache, a.refusal_directions, a, dev)
            print(f"[refusal] before proj_mean={ref_before['proj_mean']} "
                  f"(对照 proj_comply={ref_before['baseline_proj_comply']})")

    val_fn = None
    if val_cache is not None and a.eval_every:
        @torch.no_grad()
        def val_fn(max_n=12):
            tot, n = 0.0, 0
            for nm in val_cache.names:
                for h, lab, att in val_cache.of(nm):
                    logits = forward(h.to(dev), att.to(dev), ckpt=False)
                    tot += float(chunked_ce(logits, lab.to(dev), a.ce_chunk))
                    n += 1
                    del logits
                    if n >= max_n:
                        break
                if n >= max_n:
                    break
            return tot / max(1, n)
        print(f"[val] 每 {a.eval_every} 步评一次（≤12 个 val 样本），"
              f"patience={a.early_stop_patience}")

    _fit(model, forward, cache, a, dev, val_fn=val_fn)

    report = None
    if a.eval_by_cat:
        print("[eval] after（训后）…")
        eval_after = eval_by_cat(forward, cache, val_cache, a, dev)
        report = {}
        for name in sorted(set(eval_before) | set(eval_after)):
            b, f = eval_before.get(name, {}), eval_after.get(name, {})
            rec = {"before": b, "after": f}
            bt, at = b.get("train_loss"), f.get("train_loss")
            bv, av = b.get("val_loss"), f.get("val_loss")
            if bt and at:
                rec["train_drop_pct"] = round((bt - at) / bt * 100, 2)
            if bv and av:
                rec["val_drop_pct"] = round((bv - av) / bv * 100, 2)
            if rec.get("train_drop_pct") is not None and rec.get("val_drop_pct") is not None:
                # §14.8 single-stage bar: train -20%, val same direction -10%
                rec["passed_14_8"] = (rec["train_drop_pct"] >= 20
                                      and rec["val_drop_pct"] >= 10)
            # §15 forgetting monitor: the generic replay set must not get WORSE.
            # train_drop_pct is a loss drop, so a negative value means loss rose.
            if name in ("gen", "general") and rec.get("train_drop_pct") is not None:
                rise = -rec["train_drop_pct"]
                rec["forgetting_rise_pct"] = round(rise, 2)
                rec["forgetting_check"] = "WARN" if rise > 5 else "OK"
                if rise > 5:
                    print(f"[eval][WARN] 通用集（{name}）loss 上升 {rise:.1f}% > 5% "
                          f"—— 可能已在灾难性遗忘，收紧 lr / 降 steps / 提高回放比例")
            report[name] = rec
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "eval_by_cat.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        for k, v in report.items():
            print(f"[eval]   {k:10s} train_drop={v.get('train_drop_pct')}% "
                  f"val_drop={v.get('val_drop_pct')}% "
                  f"{'PASS' if v.get('passed_14_8') else ('FAIL' if 'passed_14_8' in v else 'N/A')}")
        print("[eval] → eval_by_cat.json")
        if any(v.get("passed_14_8") is False for v in report.values()):
            print("[eval][warn] 有类别未过 §14.8 单段判据：可能只背下了这批样本，"
                  "不要据此判定方案成功")

    # ---- abliteration probe: after -----------------------------------------
    rp = None
    if ref_cache is not None and ref_before is not None:
        ref_after = refusal_projection(forward, ref_cache, a.refusal_directions, a, dev)
        delta = round(ref_after["proj_mean"] - ref_before["proj_mean"], 6)
        rp = {"before": ref_before, "after": ref_after, "delta": delta,
              "passed": delta < 0,
              "rule": "训练后应配合集在 refusal direction 上的投影必须下降（delta<0）",
              "note": "本地 16 层桩模型无生成能力，这是唯一可测的 abliteration 指标"}
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "refusal_projection.json"), "w", encoding="utf-8") as fh:
            json.dump(rp, fh, ensure_ascii=False, indent=2)
        print(f"[refusal] after proj_mean={ref_after['proj_mean']}  Δ={delta:+.6f}  "
              f"{'✓ 下降（abliteration 保住）' if delta < 0 else '⚠ 未下降 —— 可能被削弱'}")
        print(f"[refusal] → {os.path.join(a.out, 'refusal_projection.json')}")

    _annotate_adapter(a, cache, {"eval_by_cat_summary":
                                 {k: {kk: v.get(kk) for kk in
                                      ("train_drop_pct", "val_drop_pct", "passed_14_8")}
                                  for k, v in (report or {}).items()},
                                 "refusal_projection": (
                                     {kk: rp.get(kk) for kk in ("delta", "passed")}
                                     if rp else None)})
    return 0


def _attach_lora(model, a):
    from peft import LoraConfig, get_peft_model
    tgt = r".*(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"
    got = []
    for n, m in model.named_modules():
        if n.rsplit(".", 1)[-1] in ("q_proj", "k_proj", "v_proj", "o_proj",
                                    "gate_proj", "up_proj", "down_proj"):
            got.append(n)
    lc = LoraConfig(r=a.lora_r, lora_alpha=a.lora_alpha, lora_dropout=a.lora_dropout,
                    bias="none", task_type="CAUSAL_LM", target_modules=tgt)
    pm = get_peft_model(model, lc)
    n_lora = sum(p.numel() for p in pm.parameters() if p.requires_grad)
    kinds = {}
    for n in got:
        kinds[n.rsplit(".", 1)[-1]] = kinds.get(n.rsplit(".", 1)[-1], 0) + 1
    print(f"[lora] attached modules={len(got)} {kinds}  trainable={n_lora / 1e6:.2f} M")
    if len(got) == 0:
        raise SystemExit("[FATAL] 没有任何 LoRA 挂点命中 —— target_modules 正则不对")
    return pm


def _fit(model, forward, cache, a, dev, steps=None, val_fn=None):
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, betas=(0.9, 0.95), weight_decay=0.0)
    probe = params[0] if params else None
    probe0 = probe.detach().float().clone() if probe is not None else None
    n_opt_steps = steps if steps else (int(a.epochs * math.ceil(len(cache) / a.bs / a.ga))
                                       if a.epochs > 0 else a.max_steps)
    print(f"[train] optimizer_steps={n_opt_steps} micro/step={a.ga} bs={a.bs} "
          f"samples={len(cache)} lr={a.lr} "
          f"eval_every={a.eval_every} patience={a.early_stop_patience}")
    rng = random.Random(a.seed)
    per_epoch = max(1, len(cache) // max(1, a.bs))
    epoch, seen = 0, 0
    t0 = time.time()
    running = 0.0
    best_val, bad_evals, stopped_at = float("inf"), 0, None
    opt.zero_grad(set_to_none=True)
    for step in range(1, n_opt_steps + 1):
        for g in range(a.ga):
            if seen >= per_epoch:
                epoch += 1
                seen = 0
            items = []
            for _ in range(a.bs):
                items.append(cache.pick(rng)[0])
                seen += 1
            hidden, labels, attn = collate(items)
            hidden = hidden.to(dev, non_blocking=True)
            labels = labels.to(dev, non_blocking=True)
            # the cache tensor must require grad, otherwise torch.utils.checkpoint
            # refuses to recompute and the LoRA inside the first layers gets no grad
            hidden.requires_grad_(True)
            logits = forward(hidden, attn.to(dev),
                             ckpt=not a.no_grad_checkpoint)
            loss = chunked_ce(logits, labels, a.ce_chunk)
            (loss / a.ga).backward()
            running += float(loss.detach())
            del logits, loss
        torch.nn.utils.clip_grad_norm_(params, a.max_grad_norm)
        opt.step()
        opt.zero_grad(set_to_none=True)
        avg = running / a.ga
        running = 0.0
        if step % a.log_every == 0 or step == 1 or step == n_opt_steps:
            vram = torch.cuda.max_memory_allocated() / 2 ** 30 if dev == "cuda" else 0.0
            print(f"[step {step}/{n_opt_steps}] loss={avg:.4f} epoch={epoch} "
                  f"vram_peak={vram:.2f} GiB {(time.time() - t0) / step:.2f}s/step", flush=True)
        # ---- forgetting guard: val loss must keep falling ------------------
        if val_fn is not None and a.eval_every and step % a.eval_every == 0:
            try:
                vl = float(val_fn())
            except Exception as e:
                print(f"[val] 评估失败（跳过本次）: {e}")
                vl = None
            if vl is not None:
                improved = vl < best_val - 1e-4
                print(f"[val] step {step} val_loss={vl:.4f} "
                      f"{'↓ 改善' if improved else f'无改善 ({bad_evals + 1}/{a.early_stop_patience})'}",
                      flush=True)
                if improved:
                    best_val, bad_evals = vl, 0
                else:
                    bad_evals += 1
                    if a.early_stop_patience and bad_evals >= a.early_stop_patience:
                        stopped_at = step
                        print(f"[early-stop] val loss 连续 {bad_evals} 次未改善"
                              f"（best={best_val:.4f}）→ 停止，防背题")
                        break
        if a.save_every and step % a.save_every == 0:
            _save(model, a, step)
    _save(model, a, stopped_at or n_opt_steps)
    if stopped_at:
        print(f"[train] 提前停止于 step {stopped_at}/{n_opt_steps}")
    if probe is not None and probe0 is not None:
        d = (probe.detach().float() - probe0).norm().item()
        base = probe0.norm().item()
        print(f"[check] 首个可训参数 ||ΔW||={d:.6e}  ||W0||={base:.6e}  "
              f"相对变化={d / max(base, 1e-12):.3e}  "
              f"{'梯度已回流 ✓' if d > 0 else '⚠ 参数未变化 — 反向可能没通'}")
    print(f"[done] {n_opt_steps} steps  {(time.time() - t0) / 60:.1f} min")


def _annotate_adapter(a, cache, extra=None):
    """Write provenance into adapter_config.json's `notes`.

    Required when stacking adapters (re / route / close): without the recorded
    layer span you cannot tell which段 an adapter came from, and peft's
    add_weighted_adapter will happily combine mismatched spans.
    """
    p = os.path.join(a.out, "adapter_config.json")
    if not os.path.exists(p):
        print(f"[notes][warn] {p} 不存在，跳过")
        return
    try:
        cfg = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print(f"[notes][warn] 读 {p} 失败: {e}")
        return
    cfg["notes"] = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "layer_span": [a.frm, a.to],
        "ctx": a.ctx, "lora_r": a.lora_r, "lora_alpha": a.lora_alpha,
        "bs": a.bs, "ga": a.ga, "lr": a.lr,
        "max_steps": a.max_steps, "epochs": a.epochs,
        "dtype": a.dtype, "seed": a.seed,
        "data_sources": cache.summary(),
        "data_mix": a.data_mix or a.act_cache,
        "eval_by_cat": bool(a.eval_by_cat),
        **(extra or {}),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"[notes] adapter_config.json ← 层段 {a.frm}-{a.to} / "
          f"{len(cache.names)} 个数据源 / r={a.lora_r}")


def _save(model, a, step):
    out = a.out if step >= 0 else a.out
    os.makedirs(out, exist_ok=True)
    model.save_pretrained(out)
    with open(os.path.join(out, "train_partial_lora.json"), "w", encoding="utf-8") as f:
        json.dump({"step": step, "from": a.frm, "to": a.to, "ctx": a.ctx,
                   "lora_r": a.lora_r, "lora_alpha": a.lora_alpha,
                   "bs": a.bs, "ga": a.ga, "lr": a.lr, "seed": a.seed,
                   "dtype": a.dtype, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}, f, indent=2)
    n = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out))
    print(f"[save] adapter → {out}  ({human(n)})")


if __name__ == "__main__":
    sys.exit(main())

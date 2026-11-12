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
    python train_partial_lora.py --layer-dir train/lines/27b-kittyrev/local-pack/merged-layers \
        --from 48 --to 63 --act-cache train/lines/27b-kittyrev/local-pack/act-cache --ctx 512 \
        --lora-r 16 --bs 1 --ga 8 --max-steps 200 --out train/lines/27b-kittyrev/kitty-rev/out-local
"""
import argparse
import glob
import json
import math
import os
import random
import re
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
    ap.add_argument("--expect-base-fp", default="",
                    help="期望的 base 指纹（precompute manifest 的 model_fp；JSON 串或 "
                         "config16/index16/first_shard16 十六进制）。不给则只记录不比对")
    ap.add_argument("--allow-cache-base-mismatch", action="store_true",
                    help="显式放行 act-cache 与 base 指纹不符（会打印 WARNING；默认关）")
    ap.add_argument("--data-mix", default="",
                    help='多源加权：name:path[:weight]。name 是标识符、path 是目录，'
                         '两者独立解析 —— name 与目录名不同不会报错 '
                         '（如 forge:act-cache/forge-train:4 完全有效）。'
                         '只有 --eval-by-cat 按【源名】配对 train/val：训练源叫 forge、'
                         '验证源若叫 forge-val，名字不成对则该类只算一侧（N/A）。'
                         '例："re-train:train/lines/27b-kittyrev/local-pack/act-cache/re-train:4,'
                         'rest:train/lines/27b-kittyrev/local-pack/act-cache/rest:1"')
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


_WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_TRAIL_WEIGHT = re.compile(r":(\d+(?:\.\d+)?)$")


def parse_mix_item(part, default_weight=1.0):
    """`name:path[:weight]` -> (name, path, weight).

    Only a TRAILING `:<number>` is treated as a weight, and a drive prefix is
    never split.  The old code did `part.split(":", 1)` for the name, so a bare
    Windows path `C:\\data\\act-re` became name='C' + root='\\data\\act-re' --
    a rooted-but-driveless path, which resolves against the CURRENT drive.  Run
    from D: and it silently reads D:\\data\\act-re instead of C:\\...
    """
    part = part.strip()
    w = default_weight
    m = _TRAIL_WEIGHT.search(part)
    if m:
        w = float(m.group(1))
        part = part[:m.start()].strip()

    if _WIN_DRIVE.match(part):
        root = part
        name = os.path.basename(os.path.normpath(part)) or "src"
    elif ":" in part:
        name, root = part.split(":", 1)
        name, root = name.strip(), root.strip()
        if not name:
            name = os.path.basename(os.path.normpath(root)) or "src"
    else:
        root = part
        name = os.path.basename(os.path.normpath(part)) or "src"
    if not root:
        raise SystemExit(f"[FATAL] --data-mix 解析失败: {part!r}")
    return name, root, w


def build_specs(mix, act_cache=None, weights=""):
    if mix:
        if act_cache:
            print("[data][warn] 同时给了 --data-mix 和 --act-cache：按 --data-mix 走，"
                  "--act-cache 被忽略")
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
            if len(roots) != len(out):
                # old code silently fell back to weight 1.0 -- i.e. every
                # --data-mix weight vanished with no message
                raise SystemExit(
                    f"[FATAL] --act-cache 有 {len(roots)} 个目录，权重串有 {len(out)} 项，"
                    f"对不上；要么逐项写全，要么改用 --data-mix name:path:weight")
            return [(n, r, w) for (n, _, w), r in zip(out, roots)]
        return [parse_mix_item(act_cache)]
    raise SystemExit("[FATAL] 需要 --act-cache 或 --data-mix")


# 回放池在 plan_layers 里是 rest/（训练侧）+ gen-val/（验证侧），同一角色的两个
# 目录名。把它们归到同一 family，否则「遗忘监控」永远配不上对（见下）。
_REPLAY_ALIASES = {"rest": "replay", "gen": "replay", "general": "replay"}


def _src_family(name, root):
    """`re-train` 与 `re-val` 是同一类能力的两侧。

    eval_by_cat 原来按【源名】配对 train/val，而 plan_layers 生成的命令里
    训练源叫 re-train、验证源叫 re-val —— 名字永不成对，于是每个类别只能算到
    一侧，train_drop / val_drop 恒为 None，§14.8 判据永远是 N/A（不报错）。
    按目录名去掉 -train/-val/-test 配对；rest 与 gen 都归到 replay。
    """
    b = os.path.basename(os.path.normpath(root))
    for suf in ("-train", "-val", "-test", "-eval"):
        if b.endswith(suf) and len(b) > len(suf):
            b = b[: -len(suf)]
            break
    return _REPLAY_ALIASES.get(b, _REPLAY_ALIASES.get(name, b if b else name))


# --------------------------------------------------------------------------- #
# 消费侧 base 指纹守卫（v4 起）
#   precompute 侧已有 model_fp + resume 比对（t28 覆盖），但**新目录没有 resume**：
#   把 v3 的 act-cache 拷成 act-cache-v4 传进来，precompute 一次都不会跑。
#   同架构 ⇒ hidden/labels 形状完全一致 ⇒ 不报错、loss 照常下降 ⇒ 静默训错。
#   所以 trainer 这一侧必须再查一次，这是"缓存与 base 逐比特绑定"的唯一兜底。
# --------------------------------------------------------------------------- #
def _fp_diffs(old, new):
    keys = sorted(set(old or {}) | set(new or {}))
    return [f"model_fp.{k}: 期望={ (old or {}).get(k)!r} 实际={ (new or {}).get(k)!r}"
            for k in keys if (old or {}).get(k) != (new or {}).get(k)]


def resolve_expect_fp(a):
    """--expect-base-fp 优先；否则从 --base-shards / --layer-dir 现场算。"""
    raw = (getattr(a, "expect_base_fp", "") or "").strip()
    if raw:
        try:
            return json.loads(raw), "--expect-base-fp"
        except Exception:
            return {"config16": raw}, "--expect-base-fp(raw)"
    for p in (getattr(a, "base_shards", None), getattr(a, "layer_dir", None)):
        if not p:
            continue
        has_index = os.path.exists(os.path.join(p, "model.safetensors.index.json"))
        has_shard = bool(glob.glob(os.path.join(p, "*.safetensors")))
        if not (has_index or has_shard):
            continue
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            if here not in sys.path:
                sys.path.insert(0, here)
            from precompute_activations import model_fingerprint
            return model_fingerprint(p), os.path.abspath(p)
        except Exception as e:                                    # noqa: BLE001
            print(f"[cache-fp][warn] 无法从 {p} 计算指纹（{type(e).__name__}: {e}）")
    return None, ""


def check_cache_base_fp(cache, expect_fp, expect_src, allow_mismatch, label="train"):
    """每个 act-cache 源的 manifest.model_fp 与期望指纹比对。"""
    if cache is None:
        return
    if not expect_fp:
        print(f"[cache-fp][warn] {label}: 未给 --expect-base-fp 且无法从模型目录推导 ——"
              f" 本次不校验缓存与 base 的绑定（只记录各源指纹）")
    n_ok = n_warn = 0
    for s in cache.specs:
        mf = os.path.join(s["root"], "manifest.json")
        if not os.path.exists(mf):
            print(f"[cache-fp][warn] {label}/{s['name']}: 无 manifest.json，无法证明来源")
            n_warn += 1
            continue
        try:
            m = json.load(open(mf, encoding="utf-8"))
        except Exception as e:                                    # noqa: BLE001
            raise SystemExit(f"[FATAL] {mf} 读取失败: {e}")
        got = m.get("model_fp")
        if not got:
            raise SystemExit(
                f"[FATAL] {mf} 没有 model_fp：旧版缓存，无法证明来自哪份权重。\n"
                f"        act-cache 与 base 逐比特绑定（同架构=同形状=不会报错），"
                f"重建该源后再训：\n"
                f"        precompute_activations.py --model <本次 base> ... --out {s['root']}")
        if not expect_fp:
            print(f"[cache-fp] {label}/{s['name']}: config16={got.get('config16')} "
                  f"idx16={got.get('index16')} shard16={got.get('first_shard16')}（未比对）")
            n_ok += 1
            continue
        diffs = _fp_diffs(expect_fp, got)
        if not diffs:
            print(f"[cache-fp] {label}/{s['name']}: 一致（来自 {expect_src}）"
                  f" config16={got.get('config16')} shard16={got.get('first_shard16')}")
            n_ok += 1
            continue
        head = "；".join(diffs[:3])
        if allow_mismatch:
            print(f"[cache-fp][WARNING] {label}/{s['name']} 与 base 指纹不符，"
                  f"因 --allow-cache-base-mismatch 放行：{head}")
            n_warn += 1
            continue
        raise SystemExit(
            f"[FATAL] act-cache 与 base 指纹不符（{label}/{s['name']}，{s['root']}）：\n"
            f"        cache.model_fp = {got}\n"
            f"        期望 base      = {expect_fp}（来源 {expect_src}）\n"
            f"        差异 {len(diffs)} 项，前 3 项：{head}\n"
            f"        形状一致不会报错，训练会静默跑在错误激活上。\n"
            f"        重建该源，或确属实验目的再显式加 --allow-cache-base-mismatch。")
    if n_warn:
        print(f"[cache-fp][warn] {label}: {n_warn} 个源未通过指纹校验")


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
            # manifest cross-check: a stray .pt copied in from another source would
            # pair sample A's hidden with sample B's labels and train silently on
            # garbage -- the loader sorts by filename and never validates content.
            mf_path = os.path.join(root, "manifest.json")
            if os.path.exists(mf_path):
                try:
                    mf = json.load(open(mf_path, encoding="utf-8"))
                    exp = int(mf.get("count") or len(mf.get("samples") or []))
                except Exception as e:
                    raise SystemExit(f"[FATAL] {root}/manifest.json 读取失败: {e}")
                exp_set = set(mf.get("samples") or [])
                got_set = {os.path.basename(p) for p in files}
                if exp and exp != len(files) and not limit:
                    raise SystemExit(
                        f"[FATAL] 源 {name}: 目录 {len(files)} 个 .pt 与 manifest 的 {exp} 不一致"
                        f"（混入其它来源的 .pt 会让 hidden/labels 张冠李戴）")
                if exp_set and not limit and exp_set != got_set:
                    raise SystemExit(
                        f"[FATAL] 源 {name}: 文件集合与 manifest 不符"
                        f"（缺 {len(exp_set - got_set)} / 多 {len(got_set - exp_set)}）")
                print(f"[data]   {name:10s} manifest 校验通过（{len(files)} 样本）")
            self.specs.append({"name": name, "root": os.path.abspath(root),
                               "weight": float(w), "files": files,
                               "family": _src_family(name, root)})
        names = [s["name"] for s in self.specs]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            # of(name) yields only the FIRST spec with that name and summary()
            # is a dict keyed by name, so the second source silently disappears
            # from validation and from the report -- while still being trained on.
            raise SystemExit(
                f"[FATAL] --data-mix 源名重复 {dup}：同一名字下第二个目录会被 "
                f"of()/summary() 静默吞掉（训练仍在抽它，验证不看它）——改个名再跑")
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


def check_val_overlap(train_cache, val_cache):
    """val 抽样与训练抽样撞车时，早停/§14.8 判据量的是训练集本身。

    `eval_by_cat` 拿 train_cache 和 val_cache 各自算一份 loss；如果两者指向同一
    批 .pt，val_loss == train_loss，val_vs_train 恒等于 1.0，"val 也降了" 这句
    话就没有信息量了，而早停也会在训练集上做选择。这里只做判定，不改采样。
    """
    if val_cache is None:
        return {}
    train_roots = {s["root"] for s in train_cache.specs}
    train_names = {s["name"] for s in train_cache.specs}
    train_files = set()
    for s in train_cache.specs:
        train_files |= {os.path.basename(p) for p in s["files"]}

    same_root = sorted({s["root"] for s in val_cache.specs} & train_roots)
    if same_root:
        raise SystemExit(
            f"[FATAL] --eval-cache 与训练源是同一个目录 {same_root}："
            f"val_loss 就是 train_loss，早停与 §14.8 判据全部失效")

    shared = []
    for s in val_cache.specs:
        ov = train_files & {os.path.basename(p) for p in s["files"]}
        if ov:
            shared.append({"val_source": s["name"], "root": s["root"],
                           "overlap": len(ov), "examples": sorted(ov)[:5]})
    same_name = sorted({s["name"] for s in val_cache.specs} & train_names)
    if shared or same_name:
        print(f"[data][WARN] val 与 train 存在同名/同文件样本：{len(shared)} 个 val 源受影响"
              f"{'，且源名重复 ' + str(same_name) if same_name else ''}")
        for r in shared:
            print(f"[data][WARN]   val 源 {r['val_source']} 与训练集重名 {r['overlap']} 个："
                  f"{r['examples']}")
        print("[data][WARN]   早停/§14.8 的 val 部分是这些样本的复算，不是泛化证据")
    return {"same_root": same_root, "shared_files": shared, "shared_names": same_name}


@torch.no_grad()
def eval_by_cat(forward, train_cache, val_cache, a, dev, max_per_src=24):
    """Per-category train/val loss -- the falsification test of §14.8.

    If val loss does not move in the same direction as train loss, the model
    memorised the subset instead of learning the capability, and the whole
    targeted-training claim fails.  This is the only per-layer attribution we
    can do locally (a 16-layer stub cannot generate 23-answer text).
    """
    out = {}
    fams = []
    for s in list(train_cache.specs) + list(val_cache.specs if val_cache else []):
        if s["family"] not in fams:
            fams.append(s["family"])
    for name in sorted(fams):
        rec = {}
        for tag, cache in (("train", train_cache), ("val", val_cache)):
            if cache is None:
                continue
            losses, n = [], 0
            for spec in cache.specs:
                if spec["family"] != name:
                    continue
                for p in spec["files"]:
                    if n >= max_per_src:
                        break
                    h, lab, att = cache._load(p, cache.ctx)
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


def _fmt_cat_row(name, rec):
    """eval_by_cat 的一行报告：样本量与判据放在同一行。

    n_train / n_val 原来只写进 eval_by_cat.json，没有任何下游读者 ——于是 §14.8 的
    PASS/FAIL 可能建立在 1 条样本上，而看报告的人看不到样本量（"打印了但没人读"）。
    这里只把样本量搬到打印行，**不动任何阈值**：判据还是原来那两条。
    """
    aft = rec.get("after") or {}
    verdict = ("PASS" if rec.get("passed_14_8")
               else ("FAIL" if "passed_14_8" in rec else "N/A"))
    return (f"[eval]   {name:10s} "
            f"n(tr/val)={aft.get('n_train', '-')}/{aft.get('n_val', '-')} "
            f"train_drop={rec.get('train_drop_pct')}% "
            f"val_drop={rec.get('val_drop_pct')}% {verdict}")


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
    if logits.dim() != 3:
        raise SystemExit(f"[FATAL] chunked_ce 需要 logits[B,T,V]，拿到 {tuple(logits.shape)}")
    if tuple(labels.shape) != tuple(logits.shape[:2]):
        raise SystemExit(f"[FATAL] labels{tuple(labels.shape)} 与 logits"
                         f"{tuple(logits.shape)} 的前两维不一致：hidden/labels 张冠李戴")
    V = logits.shape[-1]
    T = logits.shape[1] - 1          # number of predicted positions
    if T <= 0:
        # used to return 0.0 silently (cnt=0 -> total/max(1,0)), i.e. a 1-token
        # sample contributed a perfect loss and poisoned val/early-stop
        raise SystemExit(f"[FATAL] 样本只有 {logits.shape[1]} 个位置，shift-CE 无预测位")
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
        if a.dtype == "4bit":
            # 旧写法算了 `quant = a.dtype == "4bit"` 但没人读它，而下面那行打印仍写
            # dtype=4bit —— smoke 走的是 from_config 的 tiny 模型，量化根本没生效。
            # 报告说 4bit、实际跑 bf16，是"打印了但没人验"的典型。
            print("[smoke][warn] --dtype 4bit 在 smoke 下不生效（tiny 模型按默认精度构建，"
                  "只用来跑通链路）")
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
    check_cache_base_fp(cache, *resolve_expect_fp(a), a.allow_cache_base_mismatch, "train")
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
    check_cache_base_fp(val_cache, *resolve_expect_fp(a), a.allow_cache_base_mismatch, "val")
    val_overlap = {}
    if val_cache is not None:
        print(f"[data] 验证集 {len(val_cache)} 样本 / {len(val_cache.names)} 源")
        val_overlap = check_val_overlap(cache, val_cache)
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
            check_cache_base_fp(ref_cache, *resolve_expect_fp(a), a.allow_cache_base_mismatch, "refusal")
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
        forget_seen = False
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
            # 家族名才是真正的键：plan_layers 的回放训练源叫 rest、验证源叫 gen-val，
            # 按旧写法 ("gen","general") 永远匹配不上 → 监控静默失效。
            if name in ("replay", "gen", "general") and rec.get("train_drop_pct") is not None:
                forget_seen = True
                rise = -rec["train_drop_pct"]
                rec["forgetting_rise_pct"] = round(rise, 2)
                rec["forgetting_check"] = "WARN" if rise > 5 else "OK"
                if rise > 5:
                    print(f"[eval][WARN] 通用集（{name}）loss 上升 {rise:.1f}% > 5% "
                          f"—— 可能已在灾难性遗忘，收紧 lr / 降 steps / 提高回放比例")
            report[name] = rec
        if not forget_seen:
            print("[eval][warn] 遗忘监控没有匹配到任何类别：replay 的 train/val 没配对"
                  "（本节不会产出 forgetting_check，别把 N/A 当成没遗忘）")
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "eval_by_cat.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        n_na = 0
        for k, v in report.items():
            print(_fmt_cat_row(k, v))
            if "passed_14_8" not in v:
                n_na += 1
        print("[eval] → eval_by_cat.json")
        if n_na:
            print(f"[eval][warn] {n_na}/{len(report)} 个家族算不出 §14.8（缺 train 或 val 侧）"
                  f"—— 报告里那几行是 N/A，别当成通过：先看 --data-mix 与 --eval-cache "
                  f"是否覆盖同一家族")
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


def _delta_check(ps, p0s, n_show=16):
    """梯度回流的判据：**任一**可训参数动了就算通。

    旧写法只看 params[0]，而 peft 的 LoRA 里 params[0] 通常是 lora_A：
    lora_B 是**零初始化**，所以第一步 ∂L/∂A = Bᵀ(…) = 0 —— lora_A 的梯度
    在 step 1 恒为 0（第二步才有）。于是 `--max-steps 1` 的真实训练会打出
    「⚠ 参数未变化 — 反向可能没通」，把人吓去查反向图，其实一切正常。
    实测：1 step 报 0；同数据 3 step 报相对变化 7.4e-01。
    返回 (msg, any_moved)。
    """
    deltas = [((p.detach().float() - p0).norm().item(), p0.norm().item())
              for p, p0 in zip(ps, p0s)]
    moved = [(d, b) for d, b in deltas if d > 0]
    if not deltas:
        return ("[check] 没有可训参数快照，跳过回流判据", False)
    d_best, b_best = max(deltas, key=lambda t: t[0])
    # lora_B 是零初始化 → ||W0||=0，相对变化没有意义（除以 1e-12 会印出 2.8e9 这种假数）
    rel = f"{d_best / b_best:.3e}" if b_best > 1e-9 else "n/a（该参数零初始化）"
    if moved:
        return (f"[check] 可训参数 {len(moved)}/{len(deltas)} 有变化  "
                f"最大 ||ΔW||={d_best:.3e}  相对={rel}  梯度已回流 ✓"
                f"（只看 lora_A 的单步会误报 0：lora_B 零初始化 → A 在 step1 梯度恒 0）",
                True)
    return (f"[check] ⚠ 全部 {len(deltas)} 个快照参数都没变化 — 反向可能没通", False)


def _fit(model, forward, cache, a, dev, steps=None, val_fn=None):
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, betas=(0.9, 0.95), weight_decay=0.0)
    # 快照前 16 个可训参数（不是只看第 0 个 —— 见 _delta_check 的注释）
    probe_ps = params[:16]
    probe0 = [p.detach().float().clone() for p in probe_ps]
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
    if probe_ps:
        msg, _moved = _delta_check(probe_ps, probe0)
        print(msg)
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

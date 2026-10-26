#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""serve_4bit_base.py -- OpenAI-compatible endpoint for Qwen3.8-27B in 4bit nf4.

One script serves BOTH the base model and base+LoRA, so base-vs-adapter scores
are produced by the same code path on the same day.

Usage
  # pure base
  python serve_4bit_base.py --model /root/autodl-tmp/kitty-rev/base/Qwen3.8-27B --port 18000

  # base + LoRA adapter
  python serve_4bit_base.py --model /root/autodl-tmp/kitty-rev/base/Qwen3.8-27B \
      --adapter /root/autodl-tmp/kitty-rev/out/adapter --port 18000

Endpoints
  GET  /v1/models
  POST /v1/chat/completions      passes `tools` through, returns OpenAI
                                 choices[0].message.tool_calls

Design notes
  - Qwen3.5 chat template emits tool calls as XML:
        <tool_call><function=NAME><parameter=K>V</parameter></function></tool_call>
    JSON style is parsed as a fallback. Without this parsing every judge that
    inspects tool_calls would see calls=0 and fail for the wrong reason.
  - generation is greedy (do_sample=False) to match eval_kitty temperature=0.0.
  - defaults to enable_thinking=False: the template injects a long
    reasoning_effort=xhigh instruction otherwise, which both burns tokens and
    can leak judge keywords into the answer text.
  - heavy imports live in main() so `--help` and ast.parse checks stay instant
    and never allocate VRAM.
"""
import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MODEL = "/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B"

RE_XML_CALL = re.compile(r"<tool_call>\s*<function=([^>\n]+)>(.*?)</function>\s*</tool_call>", re.S)
RE_XML_PARAM = re.compile(r"<parameter=([^>\n]+)>(.*?)</parameter>", re.S)
RE_JSON_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def _coerce(val):
    if val == "":
        return ""
    if val in ("true", "True"):
        return True
    if val in ("false", "False"):
        return False
    if val in ("null", "None"):
        return None
    if re.fullmatch(r"-?\d+", val):
        try:
            return int(val)
        except Exception:
            return val
    if re.fullmatch(r"-?\d+\.\d+", val):
        try:
            return float(val)
        except Exception:
            return val
    return val


def parse_tool_calls(text):
    """Return [(name, arguments_dict), ...]."""
    calls = []
    for m in RE_XML_CALL.finditer(text):
        name = m.group(1).strip()
        if not name:
            continue
        args = {}
        for p in RE_XML_PARAM.finditer(m.group(2)):
            args[p.group(1).strip()] = _coerce(p.group(2).strip())
        calls.append((name, args))
    if calls:
        return calls
    for m in RE_JSON_CALL.finditer(text):
        try:
            obj = json.loads(m.group(1))
        except Exception:
            continue
        name = obj.get("name") or obj.get("function") or ""
        args = obj.get("arguments") or obj.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"_raw": args}
        if isinstance(name, str) and name.strip():
            calls.append((name.strip(), args if isinstance(args, dict) else {"_raw": args}))
    return calls


def strip_specials(text):
    for tok in ("<|im_end|>", "<|endoftext|>", "<|im_start|>"):
        idx = text.find(tok)
        if idx >= 0:
            text = text[:idx]
    return text.strip()


def prose_only(txt):
    return RE_XML_CALL.sub("", RE_JSON_CALL.sub("", txt)).strip()


def build_parser():
    ap = argparse.ArgumentParser(
        prog="serve_4bit_base.py",
        description="OpenAI-compatible 4bit nf4 endpoint for Qwen3.8-27B (base or base+LoRA).")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"checkpoint directory (default {DEFAULT_MODEL})")
    ap.add_argument("--adapter", default=None,
                    help="LoRA adapter directory; omit to serve the pure base model")
    ap.add_argument("--port", type=int, default=18000, help="listen port (default 18000)")
    ap.add_argument("--host", default="0.0.0.0", help="listen host (default 0.0.0.0)")
    ap.add_argument("--name", default=None,
                    help="public model name; defaults to <dir>[-<adapter>]")
    ap.add_argument("--thinking", action="store_true",
                    help="enable the template reasoning preamble (default off)")
    ap.add_argument("--effort", default="medium", choices=["xhigh", "medium", "low"],
                    help="reasoning effort when --thinking is set (default medium)")
    ap.add_argument("--max-new", type=int, default=2048,
                    help="hard cap on max_new_tokens (default 2048)")
    ap.add_argument("--threads", type=int, default=1,
                    help="generate() serialisation slots; keep 1 on a single GPU")
    # ---- 批处理（默认关：--batch 1 = 与旧版逐比特相同的行为）--------------------
    ap.add_argument("--batch", type=int, default=1,
                    help="一次 generate 里并多少条请求（默认 1 = 旧行为不变）。"
                         ">1 时请求先入队，攒满 N 条或等 --batch-wait-ms 后一起前向")
    ap.add_argument("--batch-wait-ms", type=int, default=200,
                    help="凑批最多等多久（毫秒，默认 200）")
    ap.add_argument("--max-batch-tokens", type=int, default=4096,
                    help="单批 prompt+max_new 的 token 预算；超预算的请求单独跑（不拖死整批）")
    ap.add_argument("--selftest", type=int, default=0, metavar="N",
                    help="载入模型后跑 N 条等价性+吞吐自检再退出（0=正常服务）")
    return ap


class Job:
    """一条待生成请求。HTTP 线程 submit 后等 event，批线程填 text/err。"""
    __slots__ = ("ids", "max_new", "event", "text", "n_out", "err", "t0", "prompt_len", "wid")

    def __init__(self, ids, max_new, wid):
        self.ids = ids
        self.max_new = int(max_new)
        self.event = threading.Event()
        self.text = None
        self.n_out = 0
        self.err = None
        self.t0 = time.time()
        self.prompt_len = int(ids.shape[1])
        self.wid = wid


class Batcher(threading.Thread):
    """攒批 → 一次 generate → 按 job 各自回填。

    为什么要它：eager 解码是逐 token 的 Python 循环，单请求只吃 1 个核（实测 CPU 98.5%
    = 1 核，GPU 32%）。把多条 prompt 拼成一个 batch，同一个 kernel 启动就能喂满 GPU。

    等价性要点（错一条就是"看起来更快、结果悄悄变了"）：
      · 左 padding（decoder-only 必须左对齐，否则生成位置错位）+ 显式 attention_mask
      · 每条独立的 max_new：批内按最大值生成，回填时各自截断（greedy 前缀一致）
      · 超长请求单独跑：一条 4k prompt 混进来会把整批的显存和时延都拖爆
      · 批生成抛错 → 整批降级为逐条重跑（一条坏请求不许带走别人）
    """

    def __init__(self, tok, model, size, wait_ms, max_tokens, lock, device="cuda:0"):
        super().__init__(daemon=True, name="batcher")
        self.tok = tok
        self.model = model
        self.size = max(1, int(size))
        self.wait_ms = max(0, int(wait_ms))
        self.max_tokens = max(1, int(max_tokens))
        self.lock = lock
        self.device = device
        self.q = queue.Queue()
        self.wid = 0
        self.stat = {"batches": 0, "jobs": 0, "gen_tok": 0, "sec": 0.0, "solo": 0, "fallback": 0}

    def submit(self, ids, max_new):
        self.wid += 1
        j = Job(ids, max_new, self.wid)
        self.q.put(j)
        return j

    def run(self):
        while True:
            first = self.q.get()
            batch = [first]
            deadline = time.time() + self.wait_ms / 1000.0
            while len(batch) < self.size:
                left = deadline - time.time()
                if left <= 0:
                    break
                try:
                    batch.append(self.q.get(timeout=left))
                except queue.Empty:
                    break
            try:
                self._execute(batch)
            except Exception:
                traceback.print_exc()
                for j in batch:            # 兜底：批级异常不许让请求永久挂住
                    if not j.event.is_set():
                        j.err = j.err or "batcher crashed"
                        j.event.set()

    def _execute(self, batch):
        small, big = [], []
        for j in batch:
            if j.prompt_len + j.max_new <= self.max_tokens:
                small.append(j)
            else:
                big.append(j)
        if small:
            self._generate(small)
        for j in big:                       # 超长请求：独占一次前向
            self.stat["solo"] += 1
            self._generate([j])
        self.stat["batches"] += 1
        self.stat["jobs"] += len(batch)

    def _generate(self, group):
        import torch
        t0 = time.time()
        try:
            with self.lock, torch.no_grad():
                if len(group) == 1:
                    j = group[0]
                    ids = j.ids.to(self.device)
                    out = self.model.generate(
                        ids, max_new_tokens=j.max_new, do_sample=False,
                        pad_token_id=self.tok.pad_token_id,
                        eos_token_id=self.tok.eos_token_id)
                    base = ids.shape[1]
                    rows = [(j, out[0][base:])]
                else:
                    lens = [j.prompt_len for j in group]
                    plen = max(lens)
                    pad = self.tok.pad_token_id
                    ids = torch.full((len(group), plen), pad, dtype=torch.long)
                    am = torch.zeros((len(group), plen), dtype=torch.long)
                    for i, j in enumerate(group):
                        L = j.prompt_len
                        ids[i, plen - L:] = j.ids[0]
                        am[i, plen - L:] = 1
                    mx = max(j.max_new for j in group)
                    out = self.model.generate(
                        ids.to(self.device), attention_mask=am.to(self.device),
                        max_new_tokens=mx, do_sample=False,
                        pad_token_id=pad, eos_token_id=self.tok.eos_token_id)
                    rows = [(j, out[i][plen:]) for i, j in enumerate(group)]
        except Exception:
            if len(group) > 1:
                self.stat["fallback"] += 1
                traceback.print_exc()
                print(f"[batch] 批生成失败 → 降级逐条重跑 n={len(group)}", flush=True)
                for j in group:
                    self._generate([j])          # 单条内部自带 try：一条坏请求不连坐
                return
            # 单条失败：只标这一条，绝不向上抛 —— 向上抛会把整批都变成 "batcher crashed"
            traceback.print_exc()
            j = group[0]
            j.err = f"generate failed: {sys.exc_info()[1]}"
            j.n_out = 0
            j.event.set()
            return

        dt = time.time() - t0
        for j, gen in rows:
            gen = gen[:j.max_new]                    # 每条独立 max_new
            # eos 之后的 pad 不是生成内容：算进 usage/tok·s 会偏乐观（报告要拿它决策）
            ids = gen.tolist()
            eos = self.tok.eos_token_id
            cut = len(ids)
            for k, t in enumerate(ids):
                if t == eos:
                    cut = k
                    break
            gen = gen[:cut]
            j.text = strip_specials(self.tok.decode(gen, skip_special_tokens=True))
            j.n_out = int(gen.shape[0])
            j.event.set()
            self.stat["gen_tok"] += j.n_out
            self.stat["sec"] += dt
        if len(group) > 1:
            print(f"[batch] n={len(group)} prompt_max={max(j.prompt_len for j in group)} "
                  f"out={sum(j.n_out for j in group)}tok {dt:.1f}s "
                  f"({sum(j.n_out for j in group) / max(dt, 1e-6):.1f} tok/s)", flush=True)


class State:
    model = None
    tok = None
    lock = None
    name = ""
    thinking = False
    effort = "medium"
    max_new = 2048
    calls_total = 0
    batch = 1
    batcher = None
    req_timeout = 3600.0


def load(args):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    print(f"[load] model={args.model} adapter={args.adapter or '-'} 4bit nf4", flush=True)
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb,
        device_map={"": 0},
        dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    if args.adapter:
        from peft import PeftModel
        print(f"[load] adapter {args.adapter}", flush=True)
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()
    if tok.pad_token_id is None:
        tok.pad_token_id = tok.eos_token_id
    print(f"[load] done in {time.time() - t0:.1f}s  allocated={torch.cuda.memory_allocated() / 2**30:.2f} GiB "
          f"reserved={torch.cuda.memory_reserved() / 2**30:.2f} GiB", flush=True)
    return tok, model


def build_prompt(tok, messages, tools, thinking, effort):
    """与训练口径严格对齐的 prompt 构建。

    2026-10-22 修复（第 22 例 · 假失败 S6 家族）：
      旧实现 apply_chat_template(add_generation_prompt=True, enable_thinking=False)
      → Qwen3.5 模板在该分支下 **丢掉 system 段**（len 103 vs 299）并插入
        `<think>\\n\\n</think>\\n\\n`（空闭合）。
      而训练侧 train_kitty.py 的 to_text 用 add_generation_prompt=False，
      assistant 段直接是答案正文、没有 think 块。
      两者不匹配 → 模型看到「空闭合 think」立即 EOS（实测 16 字符、eval_re 0/60、kitty 0/23）。

    现做法：用 add_generation_prompt=False 渲染（保留 system、无 think），再手工拼 assistant 头，
    与训练时模型见到的前缀完全一致。

    thinking / effort 参数保留签名但不再生效 —— 训练数据没有 think 块，任何 think 前缀都是分布外。
    """
    kw = dict(tokenize=False, add_generation_prompt=False)
    if tools:
        kw["tools"] = tools
    try:
        text = tok.apply_chat_template(messages, **kw)
    except TypeError:
        kw.pop("tools", None)
        try:
            text = tok.apply_chat_template(messages, **kw)
        except Exception:
            text = "\n\n".join(f"[{m.get('role')}] {m.get('content')}" for m in messages) + "\n"
    except Exception:
        text = "\n\n".join(f"[{m.get('role')}] {m.get('content')}" for m in messages) + "\n"
    if not text.endswith("\n"):
        text += "\n"
    if not text.endswith("<|im_start|>assistant\n"):
        text += "<|im_start|>assistant\n"
    return text


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.rstrip("/")
        if p.endswith("/v1/models"):
            return self._send(200, {"object": "list", "data": [
                {"id": State.name, "object": "model", "owned_by": "local", "created": int(time.time())}]})
        if p in ("/health", "", "/"):
            return self._send(200, {"ok": True, "model": State.name})
        return self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send(404, {"error": {"message": "not found"}})
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            req = json.loads(raw or b"{}")
        except Exception as e:
            return self._send(400, {"error": {"message": f"bad json: {e}"}})

        import torch
        messages = req.get("messages") or []
        tools = req.get("tools") or []
        max_new = min(int(req.get("max_tokens") or 1024), State.max_new)
        t1 = time.time()
        try:
            prompt = build_prompt(State.tok, messages, tools, State.thinking, State.effort)
            ids = State.tok(prompt, return_tensors="pt", add_special_tokens=False).input_ids
            if State.batch > 1 and State.batcher is not None:
                # 批处理：入队后同步等结果（客户端无感；HTTP 层仍是阻塞语义）
                job = State.batcher.submit(ids, max_new)
                if not job.event.wait(timeout=State.req_timeout):
                    return self._send(504, {"error": {"message": "batcher timeout"}})
                if job.err:
                    return self._send(500, {"error": {"message": str(job.err)}})
                txt = job.text
                n_in, n_out = job.prompt_len, job.n_out
            else:
                ids = ids.to("cuda:0")
                with State.lock, torch.no_grad():
                    out = State.model.generate(
                        ids, max_new_tokens=max_new, do_sample=False,
                        pad_token_id=State.tok.pad_token_id, eos_token_id=State.tok.eos_token_id)
                txt = strip_specials(State.tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))
                n_in, n_out = int(ids.shape[1]), int(out.shape[1] - ids.shape[1])
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": {"message": f"{type(e).__name__}: {e}"}})

        calls = parse_tool_calls(txt)
        msg = {"role": "assistant", "content": txt if not calls else prose_only(txt)}
        if calls:
            msg["tool_calls"] = [
                {"id": f"call_{i}", "type": "function",
                 "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                for i, (n, a) in enumerate(calls)]
        dt = time.time() - t1
        State.calls_total += 1
        print(f"[req#{State.calls_total}] in={n_in}tok out={n_out}tok "
              f"calls={len(calls)}{[c[0] for c in calls]} {dt:.1f}s", flush=True)
        return self._send(200, {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": State.name,
            "choices": [{"index": 0, "message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": int(n_in),
                      "completion_tokens": int(n_out),
                      "total_tokens": int(n_in + n_out)},
        })


def selftest(tok, model, lock, n=20, device="cuda:0"):
    """等价性 + 独立 max_new + 超长隔离 + 吞吐，一条命令出全部数字（--selftest N）。"""
    import torch

    def direct(p, max_new=64):
        ids = tok(p, return_tensors="pt", add_special_tokens=False).input_ids.to(device)
        with lock, torch.no_grad():
            out = model.generate(ids, max_new_tokens=max_new, do_sample=False,
                                 pad_token_id=tok.pad_token_id,
                                 eos_token_id=tok.eos_token_id)
        return strip_specials(tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))

    def run_batch(prompts, batch, max_news=None, max_tokens=1 << 20):
        # max_tokens 必须可传：写死 1<<20 会让 ③ 的分流恒不触发（假绿）
        bt = Batcher(tok, model, batch, 0, max_tokens, lock, device=device)
        bt.start()
        jobs = []
        for i, p in enumerate(prompts):
            ids = tok(p, return_tensors="pt", add_special_tokens=False).input_ids
            jobs.append(bt.submit(ids, (max_news[i] if max_news else 64)))
        for j in jobs:
            j.event.wait(timeout=1800)
        return jobs, bt

    base_prompts = [
        "你好",
        "列出三个常用的二进制分析工具，并各用一句话说明用途。",
        "用 kitty_dump 转储 notepad.exe 的 .text 段需要哪几步？只写步骤标题。",
        "解释一下 PE 的 IAT 与 ILT 的区别。",
        "写一个只包含 printf 的 C 程序，输出 ok。",
    ]

    print("[selftest] ① 等价性：直算(bs=1) vs 批处理(bs=4)，greedy 逐字节比对", flush=True)
    refs = [direct(p) for p in base_prompts]
    jobs, _bt1 = run_batch(base_prompts, 4)
    same = 0
    for i, (j, ref) in enumerate(zip(jobs, refs), 1):
        got = j.text if j.text is not None else f"<ERR:{j.err}>"
        if got == ref:
            same += 1
            print(f"  [{i}] identical  len={len(ref)}", flush=True)
        else:
            k = next((k for k in range(min(len(got), len(ref))) if got[k] != ref[k]),
                     min(len(got), len(ref)))
            print(f"  [{i}] DIFF@char{k}  ref_len={len(ref)} got_len={len(got)}", flush=True)
            print(f"      ref={ref[:80]!r}\n      got={got[:80]!r}", flush=True)
    print(f"[selftest] ① 结果：{same}/{len(base_prompts)} 条逐字节相同", flush=True)

    print("[selftest] ② 独立 max_new：批内 32/64/16 各按自己长度停", flush=True)
    ps = base_prompts[:3]
    mn = [32, 64, 16]
    jobs2, _bt2 = run_batch(ps, 3, max_news=mn)
    ok2 = 0
    for i, (j, want) in enumerate(zip(jobs2, mn), 1):
        got_n = int(j.n_out)
        ref = direct(ps[i - 1], want)
        good = (got_n <= want) and (j.text == ref)
        ok2 += good
        print(f"  [{i}] want={want} got_n={got_n} text_match={j.text == ref}", flush=True)
    print(f"[selftest] ② 结果：{ok2}/{len(ps)} 条独立 max_new 正确", flush=True)

    print("[selftest] ③ 超长隔离：1 条超预算请求 + 3 条短，同批不得影响短请求", flush=True)
    long_p = ("请逐条解释下面的汇编指令。" * 600)[:8000]
    long_ids = tok(long_p, return_tensors="pt", add_special_tokens=False).input_ids
    L = int(long_ids.shape[1])
    budget = max(256, L)          # 让长请求必然超预算（L+64 > L），分流才会真的触发
    shorts = base_prompts[1:4]
    refs_s = [direct(p) for p in shorts]
    jobs3, bt3 = run_batch([long_p] + shorts, 4, max_tokens=budget)
    solo = int(bt3.stat["solo"])
    long_ok = jobs3[0].text is not None and len(jobs3[0].text) > 0
    short_same = sum(1 for j, r in zip(jobs3[1:], refs_s) if j.text == r)
    print(f"  long_tokens={L} budget={budget} solo_triggered={solo} "
          f"long_completed={long_ok} shorts_identical={short_same}/{len(shorts)}", flush=True)
    ok3 = long_ok and short_same == len(shorts) and solo >= 1
    if solo < 1:
        print("  [FAIL] solo_triggered==0：分流没触发，这条 ③ 是假绿", flush=True)
    print(f"[selftest] ③ 结果：{'PASS' if ok3 else 'FAIL'}", flush=True)

    print(f"[selftest] ④ 吞吐：{n} 条 × batch 1/2/4", flush=True)
    tp = [base_prompts[i % len(base_prompts)] for i in range(n)]
    for b in (1, 2, 4):
        t0 = time.time()
        jobs4, _bt4 = run_batch(tp, b)
        dt = time.time() - t0
        gtok = sum(j.n_out for j in jobs4)
        try:
            import subprocess
            util = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                                   "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            util = "n/a"
        print(f"  batch={b}: {dt:.1f}s  out={gtok}tok  {gtok / max(dt, 1e-6):.1f} tok/s  "
              f"GPU(util,mem)={util}", flush=True)
    ok_all = (same == len(base_prompts)) and (ok2 == len(ps)) and ok3
    print(f"[selftest] 总判定：等价性 {same}/{len(base_prompts)} · max_new {ok2}/{len(ps)} · "
          f"超长隔离 {'PASS' if ok3 else 'FAIL'} → {'PASS' if ok_all else 'FAIL'}", flush=True)
    print("[selftest] done", flush=True)
    return 0 if ok_all else 1


def main(argv=None):
    args = build_parser().parse_args(argv)

    if not os.path.isdir(args.model):
        print(f"[FATAL] --model 目录不存在: {args.model}", file=sys.stderr)
        return 2
    if args.adapter and not os.path.isdir(args.adapter):
        print(f"[FATAL] --adapter 目录不存在: {args.adapter}", file=sys.stderr)
        return 2

    State.tok, State.model = load(args)
    State.lock = threading.Lock()
    State.thinking = bool(args.thinking)
    State.effort = args.effort
    State.max_new = int(args.max_new)
    State.name = args.name or (
        os.path.basename(os.path.normpath(args.model)) +
        ("-" + os.path.basename(os.path.normpath(args.adapter)) if args.adapter else ""))
    State.batch = max(1, int(args.batch))

    if args.selftest:
        return selftest(State.tok, State.model, State.lock, n=int(args.selftest))

    if State.batch > 1:
        State.batcher = Batcher(State.tok, State.model, State.batch,
                                args.batch_wait_ms, args.max_batch_tokens, State.lock)
        State.batcher.start()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[serve] {State.name} on http://{args.host}:{args.port} "
          f"thinking={State.thinking} max_new={State.max_new} adapter={args.adapter or '-'} "
          f"batch={State.batch}"
          + (f" wait={args.batch_wait_ms}ms tokens<={args.max_batch_tokens}"
             if State.batch > 1 else " (串行，旧行为)"), flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

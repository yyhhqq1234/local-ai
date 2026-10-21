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
    return ap


class State:
    model = None
    tok = None
    lock = None
    name = ""
    thinking = False
    effort = "medium"
    max_new = 2048
    calls_total = 0


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
    kw = dict(add_generation_prompt=True, tokenize=False)
    if tools:
        kw["tools"] = tools
    if thinking:
        kw["enable_thinking"] = True
        kw["reasoning_effort"] = effort
    else:
        kw["enable_thinking"] = False
    for attempt in (kw, {k: v for k, v in kw.items() if k != "enable_thinking"}):
        try:
            return tok.apply_chat_template(messages, **attempt)
        except TypeError:
            continue
        except Exception:
            continue
    flat = "\n\n".join(f"[{m.get('role')}] {m.get('content')}" for m in messages)
    return flat + "\n[assistant] "


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
            ids = State.tok(prompt, return_tensors="pt", add_special_tokens=False).input_ids.to("cuda:0")
            with State.lock, torch.no_grad():
                out = State.model.generate(
                    ids, max_new_tokens=max_new, do_sample=False,
                    pad_token_id=State.tok.pad_token_id, eos_token_id=State.tok.eos_token_id)
            txt = strip_specials(State.tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))
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
        print(f"[req#{State.calls_total}] in={ids.shape[1]}tok out={out.shape[1] - ids.shape[1]}tok "
              f"calls={len(calls)}{[c[0] for c in calls]} {dt:.1f}s", flush=True)
        return self._send(200, {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": State.name,
            "choices": [{"index": 0, "message": msg,
                         "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": int(ids.shape[1]),
                      "completion_tokens": int(out.shape[1] - ids.shape[1]),
                      "total_tokens": int(out.shape[1])},
        })


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

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[serve] {State.name} on http://{args.host}:{args.port} "
          f"thinking={State.thinking} max_new={State.max_new} adapter={args.adapter or '-'}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

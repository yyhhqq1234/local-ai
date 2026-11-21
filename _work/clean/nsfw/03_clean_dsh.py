# -*- coding: utf-8 -*-
"""03 DSH 适配集清洗 + 工具调用修正。

输入（只读）：train/lines/9b-oxcoder/data/dsh-adapt/train-dsh.jsonl（1909）
对照：_work/rebuild/kitty-adapt/manifest.json（65 个 kitty_*/reverse_* 工具 + 动作面）
      _work/rebuild/manifest.json（空文件 0B，按缺失处理）
输出：data/nsfw-gated/cleaned/dsh-clean.jsonl
      _work/clean/nsfw/dsh-repair-log.jsonl · dsh-run.json

修的东西：
  T1 未知工具名            → 丢记录（改名映射表内则改名）
  T2 动作当参数键（"status":"<值>" 这类）→ 重写为规范参数
  T3 占位符 "<值>"         → 按字段类型换 <action>/<op>/<path> 等
  T4 缺必填（action/op/path 等）→ 补齐规范必填
  T5 "动作面：X" 里 X 非法 → 按 manifest 重写为"可用动作：…"
  T6 计划清单 / [STAGE] / 收口行 → 删（与 system 契约冲突）
  D  模板前缀 user（这个怎么搞：/帮我看下：…）→ 归一后去重
"""
import collections
import json
import os
import re

from common import (
    IN_DSH, OUT_DIR, WORK, KITTY_MANIFEST, REBUILD_MANIFEST,
    read_jsonl, write_jsonl, norm_text, jaccard, shingle_hashes,
)

BASE_TOOLS = {
    "read": ["file_path"],
    "write": ["file_path", "content"],
    "edit": ["file_path", "old_string", "new_string"],
    "ops_bash": ["command", "description"],
    "ops_glob": ["pattern"],
    "ops_grep": ["pattern"],
    "skill": ["name"],
}

# 真实参数面与 manifest 的 actions 列表不一致的工具（以真实 schema 为准）
SCHEMA_OVERRIDE = {
    "kitty_ce": {"op": "<op>"},
    "kitty_status": {"probe": True},
    "kitty_dump": {"module": "<module>"},
    "kitty_inject": {"dll": "<dll>"},
    "kitty_dualview": {"addr": "<addr>"},
    "kitty_pchain": {"target": "<addr>"},
    "kitty_engines": {"path": "<path>"},
    "kitty_selftest": {"group": "a"},
    "kitty_loop": {"mode": "round"},
    "kitty_trail": {"action": "append"},
    "reverse_add_target": {"uri": "<uri>"},
    "reverse_add_intent": {"target": "<target>"},
    "reverse_add_obs": {"text": "<text>"},
    "reverse_add_patch": {"text": "<text>"},
    "reverse_add_asset": {"ref": "<ref>"},
    "reverse_submit": {"intentId": "<intentId>"},
    "kitty_rea_binary": {"path": "<path>"},
    "kitty_rea_function": {"procedure": "<proc>"},
    "kitty_rea_javascript": {"input_path": "<dir>"},
    "kitty_rea_trace": {"query": "<literal>"},
    "kitty_rea_android": {"path": "<apk>"},
    "kitty_rea_compare": {"left": "<evidence>", "right": "<evidence>"},
    "kitty_rea_method": {"path": "<apk>", "class_name": "<class>", "method_name": "<method>"},
    "kitty_rea_callpath": {"start": "<symbol>"},
    "kitty_rea_recover_js": {"path": "<bundle>", "output_directory": "<out>"},
}

TEMPLATE_PREFIX = ["这个怎么搞：", "帮我看下：", "场景是多少？", "按这个来：", "继续："]
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
VIOL_PATTERNS = {
    "stage": re.compile(r"\[STAGE\]"),
    "shoukou": re.compile(r"当前[:：].{0,40}结果[:：]"),
    "plan_words": re.compile(r"计划清单|判据|交付物"),
    "numbered_plan": re.compile(r"^\s*\d+[.、)]\s", re.M),
}


def load_manifest():
    tools = {}
    with open(KITTY_MANIFEST, encoding="utf-8") as f:
        for m in json.load(f):
            tools[m["name"]] = {
                "actions": [a for a in (m.get("actions") or []) if a != "*"],
                "desc": m.get("description", ""),
            }
    return tools


def canon_user(u):
    for p in TEMPLATE_PREFIX:
        if u.startswith(p):
            return u[len(p):]
    return u


def canonical_args(name, manifest):
    if name in SCHEMA_OVERRIDE:
        return dict(SCHEMA_OVERRIDE[name])
    actions = manifest.get(name, {}).get("actions") or []
    if actions:
        return {"action": actions[0]}
    return {}


def validate_call(obj, manifest):
    """返回 (ok: bool, problems: list[str])。"""
    problems = []
    name = obj.get("name")
    args = obj.get("arguments")
    if not isinstance(name, str) or not name:
        return False, ["no_name"]
    if name not in BASE_TOOLS and name not in manifest:
        return False, [f"unknown_tool:{name}"]
    if not isinstance(args, dict):
        return False, ["args_not_object"]
    if any(v == "<值>" for v in args.values()):
        problems.append("placeholder_value")
    need = BASE_TOOLS.get(name) or list(SCHEMA_OVERRIDE.get(name, {}).keys())
    if name in BASE_TOOLS:
        for k in need:
            if k not in args or args[k] in (None, ""):
                problems.append(f"missing:{k}")
    elif name in SCHEMA_OVERRIDE:
        for k in need:
            if k not in args or args[k] in (None, ""):
                problems.append(f"missing:{k}")
    else:
        actions = manifest[name]["actions"]
        act = args.get("action")
        if act is None:
            problems.append("missing:action")
        elif actions and act not in actions:
            problems.append(f"bad_action:{act}")
    return (len(problems) == 0), problems


def repair_args(name, args, manifest):
    """把畸形参数修成规范参数；返回 (new_args, note)。"""
    if not isinstance(args, dict):
        return canonical_args(name, manifest), "args_rebuilt"
    if name in BASE_TOOLS:
        out = {k: (args.get(k) if args.get(k) not in (None, "", "<值>") else f"<{k}>")
               for k in BASE_TOOLS[name]}
        if name == "ops_bash" and out.get("description", "") in ("<description>",):
            out["description"] = "跑命令"
        return out, ("placeholder_filled" if "<值>" in args.values() else "ok")
    if name in SCHEMA_OVERRIDE:
        canon = dict(SCHEMA_OVERRIDE[name])
        out = {}
        for k, dv in canon.items():
            v = args.get(k)
            if v in (None, "", "<值>"):
                v = dv
            out[k] = v
        return out, "schema_override"
    actions = manifest.get(name, {}).get("actions") or []
    act = args.get("action")
    if act in actions:
        return {"action": act}, "ok"
    # 动作被写成参数键：{"status":"<值>"} → {"action":"status"}
    if len(args) == 1:
        k = next(iter(args))
        if k in actions:
            return {"action": k}, "action_as_key"
        if k in ("op", "ops") and name == "kitty_ce":
            return {"op": "<op>"}, "action_as_key"
    if actions:
        return {"action": actions[0]}, "default_action"
    return {}, "empty"


def fix_desc(text, manifest, name):
    """改写 '动作面：…' 这类伪字段。返回 (new_text, note)。"""
    if "动作面：" not in text:
        return text, ""
    actions = manifest.get(name, {}).get("actions") or []
    m = re.search(r"动作面：([^\n]*)", text)
    listed = [x.strip() for x in re.split(r"[|｜,，/]", m.group(1)) if x.strip()]
    bad = [x for x in listed if actions and x not in actions]
    if actions:
        repl = "可用动作：" + " / ".join(actions)
    else:
        repl = ""
    new = text[:m.start()] + repl + text[m.end():]
    return new, ("desc_actions_fixed" if bad else "desc_actions_ok")


def main():
    rows = read_jsonl(IN_DSH)
    manifest = load_manifest()
    rb = os.path.getsize(REBUILD_MANIFEST) if os.path.exists(REBUILD_MANIFEST) else 0
    print(f"[in] dsh={len(rows)} manifest_tools={len(manifest)} rebuild_manifest_bytes={rb}")

    stats = collections.Counter()
    log = []
    stage1 = []

    for i, r in enumerate(rows):
        msgs = r["messages"]
        u = next(m["content"] for m in msgs if m["role"] == "user")
        a = next(m["content"] for m in msgs if m["role"] == "assistant")

        # T6 契约违例
        viol = [k for k, rx in VIOL_PATTERNS.items() if rx.search(a)]
        if viol:
            stats["drop_contract_violation"] += 1
            log.append({"i": i, "kind": "drop", "why": ",".join(viol)})
            continue

        fixed_a = a
        repaired = 0
        bad_tool = False
        for m in TOOL_CALL_RE.finditer(a):
            try:
                obj = json.loads(m.group(1))
            except Exception:
                stats["drop_unparsable_toolcall"] += 1
                bad_tool = True
                break
            ok, problems = validate_call(obj, manifest)
            name = obj.get("name")
            if ok:
                continue
            if any(p.startswith("unknown_tool") for p in problems):
                stats["drop_unknown_tool"] += 1
                log.append({"i": i, "kind": "drop", "why": problems[0]})
                bad_tool = True
                break
            new_args, note = repair_args(name, obj.get("arguments"), manifest)
            stats["repair_" + note] += 1
            repaired += 1
            fixed_call = json.dumps({"name": name, "arguments": new_args},
                                    ensure_ascii=False, separators=(",", ":"))
            fixed_a = fixed_a.replace(m.group(0), f"<tool_call>{fixed_call}</tool_call>")
            log.append({"i": i, "kind": "repair", "tool": name, "note": note,
                        "before_keys": sorted((obj.get("arguments") or {}).keys()),
                        "after": new_args})

        if bad_tool:
            continue

        # T5 伪字段
        _names = [json.loads(x).get("name") for x in TOOL_CALL_RE.findall(fixed_a)]
        fixed_a, note = fix_desc(fixed_a, manifest, _names[0] if _names else "")
        if note:
            stats[note] += 1

        stage1.append({"messages": [{"role": "system", "content": next(m["content"] for m in msgs if m["role"] == "system")},
                                    {"role": "user", "content": u},
                                    {"role": "assistant", "content": fixed_a}],
                       "_cu": canon_user(u), "_tpl": u != canon_user(u), "_rep": repaired})

    print(f"[gate] 过门 {len(stage1)}，删 {len(rows)-len(stage1)} {dict(stats)}")

    # D 去重：先精确（canon user + assistant），再近似（assistant 5-gram Jaccard ≥0.9）
    seen = set()
    stage2 = []
    for rec in stage1:
        k = (norm_text(rec["_cu"]), norm_text(rec["messages"][2]["content"]))
        if k in seen:
            stats["dedup_exact"] += 1
            log.append({"i": -1, "kind": "dedup", "why": "exact", "user": rec["_cu"][:30]})
            continue
        seen.add(k)
        stage2.append(rec)

    # 近重阈值取 0.95：assistant 近乎逐字相同才合并，避免把"同一工具不同问法"一并压掉
    NEAR_T = 0.95
    reps = []
    final = []
    near09 = 0
    for rec in stage2:
        h = {int(x) for x in shingle_hashes(rec["messages"][2]["content"])}
        dup = False
        close = False
        for rh in reps:
            j = jaccard(h, rh)
            if j >= 0.9:
                close = True
            if j >= NEAR_T:
                dup = True
                break
        if close:
            near09 += 1
        if dup:
            stats["dedup_near"] += 1
            log.append({"i": -1, "kind": "dedup", "why": f"near>={NEAR_T}", "user": rec["_cu"][:30]})
            continue
        reps.append(h)
        final.append({"messages": rec["messages"]})
    stats["near_dup_would_be_at_0.90"] = near09

    # 复核：修正后逐条重验
    reverify = collections.Counter()
    for r in final:
        a = r["messages"][2]["content"]
        for m in TOOL_CALL_RE.finditer(a):
            obj = json.loads(m.group(1))
            ok, probs = validate_call(obj, manifest)
            reverify["ok" if ok else "bad"] += 1
    names = collections.Counter()
    for r in final:
        for m in TOOL_CALL_RE.finditer(r["messages"][2]["content"]):
            names[json.loads(m.group(1)).get("name")] += 1

    out_stats = {
        "input": len(rows),
        "rebuild_manifest_bytes": rb,
        "manifest_tools": len(manifest),
        "after_gate": len(stage1),
        "final": len(final),
        "drops": {k: v for k, v in stats.items() if k.startswith("drop")},
        "repairs": {k: v for k, v in stats.items() if k.startswith("repair") or k.startswith("desc")},
        "dedup": {k: v for k, v in stats.items() if k.startswith("dedup") or k.startswith("near_dup")},
        "near_dup_threshold": NEAR_T,
        "template_prefix_rows": sum(1 for r in stage1 if r["_tpl"]),
        "tool_calls_final": dict(names),
        "reverify": dict(reverify),
    }
    print(json.dumps(out_stats, ensure_ascii=False, indent=1))

    os.makedirs(OUT_DIR, exist_ok=True)
    write_jsonl(os.path.join(OUT_DIR, "dsh-clean.jsonl"), final)
    write_jsonl(os.path.join(WORK, "dsh-repair-log.jsonl"), log[:5000])
    with open(os.path.join(WORK, "dsh-run.json"), "w", encoding="utf-8") as f:
        json.dump(out_stats, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

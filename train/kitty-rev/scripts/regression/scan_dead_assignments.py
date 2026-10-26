#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scan_dead_assignments.py -- P6 反扫：赋值后从未被读取的局部变量 + 恒定值报告字段。

为什么非 ast 不可
    grep 分不清「赋值」和「读取」：`x = 1` / `x += 1` / f-string 里的 `{x}` /
    `return x` / 闭包里读 `x`，正则看到的都是同一个标识符。只有作用域树才判得准，
    所以这一层用 ast，不用 grep（§14.4 指定的第二把扫描器）。

两类命中
  D1 dead_local    函数内被赋值、但该作用域（含内层闭包）从未被读取的局部名
                   → 典型形态：算了但没用（`x = f(...)` 后面全靠另一个变量），
                     或拼错名（`n_vall` vs `n_val`）后静默落空。
  D2 const_field   字典字面量里 `"key": <常量>`（0 / None / False / "" / "-" / 空容器）
                   → 报告装饰候选：写进 json 但永远是同一个值，却让人以为某项检查跑过了
                     （第 8 例 merge_forge `collisions: 0` 就是这个机制）。

用法
    python scripts/regression/scan_dead_assignments.py            # 人读
    python scripts/regression/scan_dead_assignments.py --json     # 机器读
    python scripts/regression/scan_dead_assignments.py --all      # 连 for/with/except 绑定一起列
    python scripts/regression/scan_dead_assignments.py --strict   # 有未判定的命中就 rc=1

只报告，不改文件。每一条都要人判；判「非缺陷」的写进
`scripts/regression/dead_assignments_allow.json`（带理由），数字才不会逼后人乱改。
"""
import argparse
import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(KITTY, "scripts")
ALLOW = os.path.join(HERE, "dead_assignments_allow.json")
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "tmp"}

CONST_VALUES = (0, 0.0, None, False, "", "-", "N/A", "n/a")
CONST_REPR = {0: "0", 0.0: "0.0", None: "None", False: "False", "": '""',
              "-": '"-"', "N/A": '"N/A"', "n/a": '"n/a"'}
# D2 只收「会被写成 json 的那张表」：变量名像报告，或直接喂给 json.dump(s)。
# 不收请求体/初始化模板（"stream": False、setdefault 的默认值）——那不是缺陷。
REPORT_NAME = re.compile(r"(report|manifest|stats|summary|result|probe|audit|"
                         r"isolation|record|rec)", re.I)


def py_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py") and fn != os.path.basename(__file__):
                out.append(os.path.join(dirpath, fn))
    return out


def rel(path):
    return os.path.relpath(path, KITTY).replace("\\", "/")


class _StoreCollector(ast.NodeVisitor):
    """只收「本作用域」的绑定，不钻进内层函数体（那是内层的局部）。"""

    def __init__(self):
        self.stores = []            # (name, lineno, kind)
        self.structural = set()     # (name, lineno) —— for / with / except 的绑定
        self.declared = set()       # global / nonlocal 名

    def _target_names(self, node):
        for t in ast.walk(node):
            if isinstance(t, ast.Name):
                self.structural.add((t.id, t.lineno))

    def visit_For(self, node):
        self._target_names(node.target)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None:
                self._target_names(item.optional_vars)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node):
        if node.name:
            self.structural.add((node.name, node.lineno))
        self.generic_visit(node)

    def visit_Global(self, node):
        self.declared.update(node.names)

    def visit_Nonlocal(self, node):
        self.declared.update(node.names)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.stores.append((node.id, node.lineno, "assign"))
        self.generic_visit(node)

    def _skip_nested(self, node):
        # 默认值/注解/装饰器是外层表达式，要走；函数体是内层作用域，不走。
        for d in getattr(node, "decorator_list", []) or []:
            self.visit(d)
        a = getattr(node, "args", None)
        if a is not None:
            for d in list(a.defaults) + [x for x in a.kw_defaults if x is not None]:
                self.visit(d)
        for n in ("returns",):
            if getattr(node, n, None) is not None:
                self.visit(getattr(node, n))
        for b in getattr(node, "bases", []) or []:
            self.visit(b)

    def visit_FunctionDef(self, node):
        self._skip_nested(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        for d in list(node.args.defaults) + [x for x in node.args.kw_defaults
                                             if x is not None]:
            self.visit(d)

    def visit_ClassDef(self, node):
        self._skip_nested(node)


def _arg_names(fn):
    a = fn.args
    names = {x.arg for x in list(getattr(a, "posonlyargs", [])) + list(a.args)
             + list(a.kwonlyargs)}
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names


def dead_locals(tree, lines):
    """D1：[(func, name, lineno, kind, snippet)]"""
    hits = []

    def walk_fn(fn):
        c = _StoreCollector()
        for stmt in fn.body:
            c.visit(stmt)
        loads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                 and isinstance(n.ctx, ast.Load)}
        params = _arg_names(fn)
        for name, ln, kind in c.stores:
            if kind == "assign" and (name, ln) in c.structural:
                kind = "bound"
            if name.startswith("_") or name in params or name in c.declared:
                continue
            if name in loads:
                continue
            hits.append((fn.name, name, ln, kind, lines[ln - 1].strip()[:90]))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            walk_fn(node)
    return hits


def const_fields(tree, lines):
    """D2：只在「报告型」字典里找恒定字段 —— [(key, lineno, repr, snippet)]

    全库所有 `"k": 0` 里绝大多数是请求体/初始化模板（`"stream": False`、
    `turns.setdefault(..., {"user": ""})`），不是缺陷。真正值得看的是会被写成 json
    的那张表：赋给 report/manifest/stats/summary/… 的字典，或直接进 json.dump(s) 的。
    """
    hits = []

    def scan_dicts(root):
        for node in ast.walk(root):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                    continue
                ln = getattr(v, "lineno", node.lineno)
                snip = lines[ln - 1].strip()[:90] if 0 < ln <= len(lines) else ""
                if isinstance(v, ast.Constant) and v.value in CONST_VALUES:
                    hits.append((k.value, ln, CONST_REPR.get(v.value, repr(v.value)), snip))
                elif isinstance(v, (ast.List, ast.Dict, ast.Tuple)) \
                        and not getattr(v, "elts", None) and not getattr(v, "keys", None):
                    hits.append((k.value, v.lineno, "空容器", snip))

    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        for t in targets:
            if REPORT_NAME.search(t):
                scan_dicts(node.value)
        if isinstance(node, ast.Call):
            f = node.func
            fn = getattr(f, "attr", "")
            owner = getattr(getattr(f, "value", None), "id", "")
            if (owner == "json" and fn in ("dump", "dumps")) or fn == "jdump":
                for arg in node.args[:1]:
                    scan_dicts(arg)

    seen, out = set(), []
    for h in hits:
        if (h[0], h[1]) in seen:
            continue
        seen.add((h[0], h[1]))
        out.append(h)
    return out


def load_allow():
    if not os.path.exists(ALLOW):
        return {"D1": [], "D2": []}
    try:
        d = json.load(open(ALLOW, encoding="utf-8"))
    except Exception as e:
        print(f"[warn] 白名单解析失败（{e}），按空处理")
        return {"D1": [], "D2": []}
    return {"D1": d.get("D1", []), "D2": d.get("D2", [])}


def main():
    ap = argparse.ArgumentParser(description="P6：死赋值 + 恒定报告字段")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="连 for/with/except 绑定一起列")
    ap.add_argument("--strict", action="store_true", help="有未判定命中则 rc=1")
    ap.add_argument("--show-suppressed", action="store_true",
                    help="连白名单条目与理由一起列（0/0 时先看这里，别以为真干净）")
    ap.add_argument("--root", default=SCRIPTS, help="扫描根（默认 scripts/）")
    a = ap.parse_args()

    allow = load_allow()
    a1 = {(e.get("file"), e.get("name")): e for e in allow["D1"]}
    a2 = {(e.get("file"), e.get("key")): e for e in allow["D2"]}

    files = py_files(a.root)
    rows, n_supp = [], 0
    for path in files:
        src = open(path, encoding="utf-8", errors="replace").read()
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError as e:
            rows.append({"file": rel(path), "kind": "SYNTAX", "line": e.lineno,
                         "name": "-", "snippet": str(e)})
            continue
        lines = src.splitlines()
        for fn, name, ln, kind, snip in dead_locals(tree, lines):
            if kind != "assign" and not a.all:
                continue
            if (rel(path), name) in a1:
                n_supp += 1
                continue
            rows.append({"file": rel(path), "kind": "D1", "bind": kind, "line": ln,
                         "name": name, "func": fn, "snippet": snip})
        for key, ln, val, snip in const_fields(tree, lines):
            if (rel(path), key) in a2:
                n_supp += 1
                continue
            rows.append({"file": rel(path), "kind": "D2", "line": ln,
                         "name": key, "value": val, "snippet": snip})

    d1 = [r for r in rows if r["kind"] == "D1"]
    d2 = [r for r in rows if r["kind"] == "D2"]
    bad = [r for r in rows if r["kind"] == "SYNTAX"]

    if a.json:
        print(json.dumps({"files": len(files), "D1": d1, "D2": d2,
                          "SYNTAX": bad, "suppressed": n_supp},
                         ensure_ascii=False, indent=2))
        return 1 if (a.strict and rows) else 0

    print(f"扫描 {len(files)} 个脚本：D1(赋值未读)={len(d1)}  "
          f"D2(恒定字段)={len(d2)}  语法失败={len(bad)}  白名单抑制={n_supp}")
    cur = None
    for r in rows:
        if r["file"] != cur:
            cur = r["file"]
            print(f"\n== {cur}")
        if r["kind"] == "D1":
            bind = "" if r.get("bind") == "assign" else f" [{r['bind']}]"
            print(f"   [D1]{bind} L{r['line']:<5} {r['name']:<22} in {r.get('func')}()"
                  f"  | {r['snippet']}")
        elif r["kind"] == "D2":
            print(f"   [D2] L{r['line']:<5} {r['name']:<22} = {r['value']:<8} | {r['snippet']}")
        else:
            print(f"   [SYNTAX] L{r['line']} {r['snippet']}")
    print("\n提示：D1 只标「本作用域赋值、含闭包在内从未读取」；写进报告但不进 json 的"
          "中间量是合理的 → 判非缺陷请写进 dead_assignments_allow.json 并给理由。")
    if n_supp:
        print(f"注意：有 {n_supp} 条被白名单吸收 —— 用 --show-suppressed 看它们和理由，"
              f"别把 0/0 当成真的干净。")
    if a.show_suppressed:
        print("\n---- 白名单（判非缺陷） ----")
        for kind in ("D1", "D2"):
            for e in allow[kind]:
                label = e.get("name") or e.get("key")
                print(f"[{kind}] {e.get('file')}:{e.get('line')} {label}\n      {e.get('reason')}")
    return 1 if (a.strict and rows) else 0


if __name__ == "__main__":
    sys.exit(main())

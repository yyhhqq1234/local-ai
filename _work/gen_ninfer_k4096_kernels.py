#!/usr/bin/env python
"""为 NInfer 引擎生成 Qwen3.5-9B (H=4096) 缺失的投影 kernel

背景
    src/ops/linear/projection/bf16/shapes/ 里每个 .cu 是「一个 (n,k) 形状的 schedule 表」，
    bf16_dispatch.cpp 用 kShapes 数组按 (n,k) 精确匹配，匹配不到就抛
    "bf16 linear: unsupported shape"。
    Qwen3.5-9B 的 k 全是 4096（或 12288），21 个已注册形状里一个都没有。

做法
    n2560_k2560.cu 是 46 行的模板：
      10 个 Bf16ScheduleInstance<..., K>（最后一个模板参数就是 k）
      select_bf16_nXXX_kYYY(tokens) 按 token 数分档
    照抄它、把 k 常量与函数名换掉，即可得到一个形状的完整 schedule 表。

目标形状（9B 需要的，去重后 6 个）
    n248320_k4096   embed / lm_head
    n12288_k4096    mlp gate / up
    n8192_k4096     gdn in_proj_qkv / attn q_proj
    n4096_k4096     gdn in_proj_z / out_proj / attn o_proj
    n1024_k4096     attn k_proj / v_proj
    n4096_k12288    mlp down

用法
    python _work/gen_ninfer_k4096_kernels.py --dry     # 只打印将生成什么
    python _work/gen_ninfer_k4096_kernels.py           # 真写文件
    python _work/gen_ninfer_k4096_kernels.py --revert  # 撤销（按 .bak 还原）
"""
import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "train", "lines", "_shared", "tools", "ninfer-master",
                   "src", "ops", "linear", "projection", "bf16")
SHAPES = os.path.join(SRC, "shapes")
TEMPLATE = os.path.join(SHAPES, "n2560_k2560.cu")
HEADER = os.path.join(SRC, "bf16_shapes.h")
DISPATCH = os.path.join(SRC, "bf16_dispatch.cpp")
CMAKE = os.path.join(SHAPES, "sources.cmake")

# (n, k, 用途说明)
TARGETS = [
    (248320, 4096, "embed / lm_head"),
    (12288, 4096, "mlp gate / up"),
    (8192, 4096, "gdn in_proj_qkv / attn q_proj"),
    (4096, 4096, "gdn in_proj_z / out_proj / attn o_proj"),
    (1024, 4096, "attn k_proj / v_proj"),
    (4096, 12288, "mlp down"),
]


def gen_one(n: int, k: int, tmpl: str) -> str:
    """把模板里的 k 换成目标值，函数名换成目标 (n,k)

    模板里 k 出现 12 次：10 次是 schedule 的模板参数（3 处跨行、格式为 ",<换行><缩进>2560>"），
    2 次在函数名 select_bf16_n2560_k2560 里。
    顺序很关键：**先**改函数名（消除其中的 2560），**再**全局替换剩余的 2560，
    否则函数名里的 2560 会被误改。
    """
    out = tmpl
    # ① 函数名（含其中的 2560）
    out = out.replace("select_bf16_n2560_k2560", f"select_bf16_n{n}_k{k}")
    # ② 剩下所有 2560 都是 schedule 的 K 模板参数（含跨行写法），全部替换
    out = out.replace("2560", str(k))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(TEMPLATE):
        sys.exit(f"[FATAL] 模板不存在: {TEMPLATE}")

    if a.revert:
        n = 0
        for n_, k_, _ in TARGETS:
            p = os.path.join(SHAPES, f"n{n_}_k{k_}.cu")
            if os.path.exists(p):
                os.remove(p); n += 1
        for p in (HEADER, DISPATCH, CMAKE):
            b = p + ".bak-k4096"
            if os.path.exists(b):
                shutil.move(b, p); print(f"  还原 {p}")
        print(f"[revert] 删除 {n} 个 kernel 文件")
        return

    tmpl = open(TEMPLATE, encoding="utf-8").read()
    print(f"[template] {os.path.basename(TEMPLATE)}  {len(tmpl.splitlines())} 行")
    print(f"{'shape':>18} {'用途':<34} {'替换次数':>8}")
    print("-" * 70)

    for n, k, use in TARGETS:
        code = gen_one(n, k, tmpl)
        cnt = code.count(f", {k}>")
        print(f"{f'n{n}_k{k}':>18} {use:<34} {cnt:>8}")
        if not a.dry:
            path = os.path.join(SHAPES, f"n{n}_k{k}.cu")
            open(path, "w", encoding="utf-8").write(code)

    if a.dry:
        print("\n[dry] 未写文件")
        return

    # ── 1) bf16_shapes.h 加声明 ──
    shutil.copy2(HEADER, HEADER + ".bak-k4096")
    h = open(HEADER, encoding="utf-8").read()
    decls = "".join(
        f"[[nodiscard]] Bf16Launch select_bf16_n{n}_k{k}(std::int32_t tokens);\n"
        for n, k, _ in TARGETS if f"select_bf16_n{n}_k{k}" not in h
    )
    marker = "} // namespace ninfer::ops::detail"
    h = h.replace(marker, decls + "\n" + marker)
    open(HEADER, "w", encoding="utf-8").write(h)
    print(f"[header] 加 {len(decls.splitlines())} 条声明")

    # ── 2) bf16_dispatch.cpp 加 kShapes 条目 ──
    shutil.copy2(DISPATCH, DISPATCH + ".bak-k4096")
    d = open(DISPATCH, encoding="utf-8").read()
    entries = "".join(
        f"    ShapeEntry{{{n}, {k}, select_bf16_n{n}_k{k}}},\n"
        for n, k, _ in TARGETS if f"ShapeEntry{{{n}, {k}," not in d
    )
    # 插在 kShapes 数组的收尾 `};` 之前
    idx = d.find("};", d.find("constexpr std::array kShapes{"))
    if idx < 0:
        sys.exit("[FATAL] 找不到 kShapes 数组结尾")
    d = d[:idx] + entries + d[idx:]
    open(DISPATCH, "w", encoding="utf-8").write(d)
    print(f"[dispatch] 加 {len(entries.splitlines())} 条 ShapeEntry")

    # ── 3) sources.cmake 加编译单元 ──
    if os.path.exists(CMAKE):
        shutil.copy2(CMAKE, CMAKE + ".bak-k4096")
        c = open(CMAKE, encoding="utf-8").read()
        adds = "".join(
            f"    n{n}_k{k}.cu\n"
            for n, k, _ in TARGETS if f"n{n}_k{k}.cu" not in c
        )
        if adds:
            c = c.rstrip() + "\n" + adds
            open(CMAKE, "w", encoding="utf-8").write(c)
            print(f"[cmake] 加 {len(adds.splitlines())} 个编译单元")
        else:
            print("[cmake] 已在列表中，跳过")
    else:
        print("[cmake] sources.cmake 不存在，需手工确认构建系统如何收集 .cu")

    print("\n[DONE] 备份后缀 .bak-k4096；撤销用 --revert")


if __name__ == "__main__":
    main()

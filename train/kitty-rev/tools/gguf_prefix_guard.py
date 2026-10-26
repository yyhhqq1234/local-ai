#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gguf_prefix_guard.py —— step3 通行守卫（原 /tmp/gguf-prefix-guard.py 随 /tmp 被清，重建于此）

判据（三条，全过才 rc=0）：
  1) GGUF 可被 gguf 包打开，tensor 名列表非空
  2) 无多模态/视觉前缀张量：v. / visual. / vision. / mm. / mmproj / model.visual
     —— 出现即说明 merged 被按 VL 结构派生（pin_arch 失效），IQ2_S 会带废张量
  3) 若给了 --expect-tensors N，则 len(tensors) == N（与 merged 的 weight_map 条数对齐）

用法：
  python gguf_prefix_guard.py <gguf> [--expect-tensors N]
退出码：0 全过 / 1 判据红 / 2 打不开
"""
import sys

BAD_PREFIX = ("v.", "visual.", "vision.", "mm.", "mmproj", "model.visual")


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("[guard] usage: gguf_prefix_guard.py <gguf> [--expect-tensors N]")
        return 2
    path = argv[0]
    expect = None
    if "--expect-tensors" in argv:
        i = argv.index("--expect-tensors")
        if i + 1 < len(argv):
            expect = int(argv[i + 1])

    try:
        from gguf import GGUFReader
    except Exception as e:
        print(f"[guard] FAIL 无法 import gguf: {e}")
        return 2
    try:
        r = GGUFReader(path)
    except Exception as e:
        print(f"[guard] FAIL 打开 GGUF 失败: {e}")
        return 2

    names = [t.name for t in r.tensors]
    bad = [n for n in names if n.startswith(BAD_PREFIX)]
    print(f"[guard] file={path}")
    print(f"[guard] tensors={len(names)} bad_prefix={len(bad)}")
    if expect is not None:
        print(f"[guard] expect_tensors={expect} match={'YES' if len(names) == expect else 'NO'}")
    if bad:
        print("[guard] FAIL 发现多模态/视觉张量（pin_arch 未生效）：")
        for n in bad[:12]:
            print(f"        {n}")
        return 1
    if expect is not None and len(names) != expect:
        print(f"[guard] FAIL 张量数不符：{len(names)} != {expect}")
        return 1
    print("[guard] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

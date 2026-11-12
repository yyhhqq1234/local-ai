#!/usr/bin/env python
"""heretic_auto.py — 无 TTY 环境下跑 Heretic 的自动应答包装器。

问题：Heretic 用 questionary/prompt_toolkit 做交互选择。后台运行（无 Windows
console）时 prompt_toolkit 走 Win32Output，抛 NoConsoleScreenBufferError。
即使 CLI 已提供 --trial-index / --model-action / --export-strategy /
--save-directory，仍会有一处残留 select 触发该异常。

做法：在 import heretic.main 之前，把 questionary.select / .path / .text
替换为按 CLI 已给值自动应答的版本。任何未被 CLI 覆盖的选择取第一个非空项。

用法（参数原样透传给 heretic）：
  train/.venv/Scripts/python.exe train/lines/_shared/scripts/heretic_auto.py --model ... --n-trials 1 ...
"""
import sys

import questionary as _q

_SAVE_DIR = None
for i, a in enumerate(sys.argv):
    if a == "--save-directory" and i + 1 < len(sys.argv):
        _SAVE_DIR = sys.argv[i + 1]
    elif a.startswith("--save-directory="):
        _SAVE_DIR = a.split("=", 1)[1]


class _Auto:
    """Mimics a questionary prompt result: ask_if_unset() calls .ask()."""

    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value

    def unsafe_ask(self):
        return self.value


def _first_choice(message, choices, **_kw):
    for c in choices:
        value = getattr(c, "value", None)
        if value not in (None, ""):
            print(f"[auto] {message} -> {value!r}")
            return _Auto(value)
    print(f"[auto] {message} -> (empty)")
    return _Auto(None)


def _path(message, **_kw):
    print(f"[auto] {message} -> {_SAVE_DIR!r}")
    return _Auto(_SAVE_DIR)


def _text(message, default="", **_kw):
    print(f"[auto] {message} -> {default!r}")
    return _Auto(default)


def _confirm(message, default=True, **_kw):
    print(f"[auto] {message} -> {default}")
    return _Auto(default)


_q.select = _first_choice
_q.path = _path
_q.text = _text
_q.confirm = _confirm

from heretic.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

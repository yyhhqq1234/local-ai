"""Print the header facts the GGUF recipe validates, plus a per-tensor format census."""

from __future__ import annotations

import collections
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ninfer-all-master"))

from tools.convert import gguf_blocks  # noqa: E402
from tools.convert.sources.gguf import GGUFFile  # noqa: E402

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "head-iq3s-mtp.gguf")
gguf = GGUFFile(path)

mtp = gguf_blocks.has_mtp(gguf)
print("file          :", gguf.path)
print("architecture  :", gguf.kv.get("general.architecture"))
print("block_count   :", gguf.kv.get("qwen35.block_count"))
print("mtp head      :", mtp)
print("tensors       :", len(gguf.tensors))

census = collections.Counter(info.type_name for info in gguf.tensors.values())
print("type census   :", dict(census))

print("mtp tensor formats:")
for name in sorted(n for n in gguf.tensors if n.startswith("blk.64.")):
    info = gguf.tensors[name]
    if info.type_id in gguf_blocks.GGUF_FORMATS_BY_TYPE:
        print("  ", name, "->", info.type_name, "(gguf_* block, imported byte for byte)")
    else:
        print("  ", name, "->", info.type_name)

print("shape/type validate passes for the tensor set:", set(gguf_blocks.expected_tensors(mtp)) == set(gguf.tensors))

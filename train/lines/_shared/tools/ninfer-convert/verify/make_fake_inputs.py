"""Build minimal fake inputs for converter link verification (no real weights).

Produces:
  verify/metadata/{config.json,generation_config.json,tokenizer.json,tokenizer_config.json}
  verify/fake.gguf   (Qwen3.8-27B dense header KVs + one dummy F32 tensor)

The GGUF deliberately carries no real tensor set: the converter must recognise the
file, accept the header, and then fail on the missing tensors -- that failure is the
proof that the GGUF source path is live end to end.
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ninfer-all-master"))

from gguf import GGUFWriter  # noqa: E402

from tools.convert.gguf_blocks import EXPECTED_HEADER  # noqa: E402
from tools.convert.ternary import HIDDEN, INTERMEDIATE, LAYERS, VOCABULARY  # noqa: E402


def build_metadata(root: pathlib.Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    config = {
        "architectures": ["Qwen3_5ForCausalLM"],
        "model_type": "qwen3_5",
        "hidden_size": HIDDEN,
        "intermediate_size": INTERMEDIATE,
        "num_hidden_layers": LAYERS,
        "num_attention_heads": 24,
        "num_key_value_heads": 4,
        "head_dim": 256,
        "vocab_size": VOCABULARY,
        "torch_dtype": "bfloat16",
    }
    (root / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (root / "generation_config.json").write_text(
        json.dumps({"bos_token_id": 1, "eos_token_id": [2, 3], "do_sample": True}, indent=2),
        encoding="utf-8",
    )
    # Minimal but structurally valid tokenizer files.
    (root / "tokenizer_config.json").write_text(
        json.dumps(
            {
                "tokenizer_class": "Qwen2Tokenizer",
                "model_max_length": 262144,
                "chat_template": "{{ messages }}",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / "tokenizer.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "truncation": None,
                "padding": None,
                "added_tokens": [],
                "normalizer": None,
                "pre_tokenizer": {"type": "Whitespace"},
                "post_processor": None,
                "decoder": None,
                "model": {"type": "BPE", "vocab": {"<unk>": 0}, "merges": []},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def build_gguf(path: pathlib.Path) -> None:
    writer = GGUFWriter(str(path), "qwen35")
    for key, value in EXPECTED_HEADER.items():
        if key == "general.architecture":
            continue
        writer.add_uint32(key, int(value))
    writer.add_tensor("token_embd.weight", np.zeros((8, 8), dtype=np.float32))
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()


def main() -> None:
    build_metadata(HERE / "metadata")
    build_gguf(HERE / "fake.gguf")
    print("metadata:", HERE / "metadata")
    print("gguf    :", HERE / "fake.gguf", (HERE / "fake.gguf").stat().st_size, "bytes")


if __name__ == "__main__":
    main()

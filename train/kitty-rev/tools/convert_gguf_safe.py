import os, sys, runpy

sys.path.insert(0, "/root/autodl-tmp/lc")
sys.path.insert(0, "/root/autodl-tmp/lc/gguf-py")
import numpy as np
import gguf.gguf_writer as gw

CH = 8 << 20
SAMPLE_SUFFIX = ("token_embd.weight", "output.weight", "blk.0.attn_qkv.weight", "blk.63.ffn_down.weight")
ratios = {}


def _eager(t):
    """lazy 张量必须先材料化；否则 memoryview 拿到零-stride 占位 ⇒ 写出全零权重。

    注意 gguf 的 `LazyNumpyTensor.to_eager` 是 **classmethod**：签名 to_eager(cls, t)，
    所以必须 f(t) 而不是 t.to_eager()。
    """
    f = getattr(type(t), "to_eager", None)
    if callable(f):
        try:
            t = f(t)
        except TypeError:
            t = f()
    arr = np.ascontiguousarray(t)
    if arr.dtype == object:
        raise SystemExit("[FAIL] eager 后仍是 object dtype：%r" % (type(t),))
    return arr


def _send(fout, arr):
    mv = memoryview(arr).cast("B")
    total = 0
    n = len(mv)
    while total < n:
        fout.write(mv[total:total + CH])
        total += min(CH, n - total)
    return total


def _nonzero_ratio(arr):
    b = np.frombuffer(np.ascontiguousarray(arr).tobytes(), dtype=np.uint8)
    if b.size == 0:
        return 0.0
    # 采样上限 4 MiB，避免大张量全量扫描拖时间
    if b.size > (4 << 20):
        b = b[:(4 << 20)]
    return float(np.count_nonzero(b)) / float(b.size)


def write_tensors_to_file(self, *, progress=False):
    self.write_ti_data_to_file()
    assert self.fout is not None
    for fout in self.fout:
        self.write_padding(fout, fout.tell())
    assert self.temp_file is None, "unexpected temp_file path"
    done = 0
    mark = 2 << 30
    for i, (fout, tensors) in enumerate(zip(self.fout, self.tensors)):
        for name, ti in tensors.items():
            assert ti.tensor is not None
            arr = _eager(ti.tensor)
            if arr.nbytes != ti.nbytes:
                raise SystemExit("[FAIL] %s eager 字节 %d != 声明 %d" % (name, arr.nbytes, ti.nbytes))
            if name.endswith(SAMPLE_SUFFIX):
                ratios[name] = _nonzero_ratio(arr)
            start = fout.tell()
            try:
                _send(fout, arr)
            except OSError as e:
                print("WRITE-FAIL tensor=%s nbytes=%d tell=%d err=%r" % (name, ti.nbytes, start, e), flush=True)
                raise
            if fout.tell() - start != ti.nbytes:
                raise ValueError("short write %s: %d != %d" % (name, fout.tell() - start, ti.nbytes))
            self.write_padding(fout, ti.nbytes)
            ti.tensor = None
            done += ti.nbytes
            if done >= mark:
                print("PROGRESS %.2fG shard=%d" % (done / 1e9, i + 1), flush=True)
                mark += (2 << 30)
    self.state = gw.WriterState.WEIGHTS
    print("[judge8] 抽样 nonzero 占比：" + ", ".join("%s=%.3f" % (k, v) for k, v in sorted(ratios.items())), flush=True)
    bad = [k for k, v in ratios.items() if v <= 0.9]
    if not ratios:
        print("[judge8] FAIL 未命中任何抽样张量（名字口径变了？）", flush=True)
        sys.exit(1)
    if bad:
        print("[judge8] FAIL 全零/近零张量：%s" % bad, flush=True)
        sys.exit(1)
    print("[judge8] PASS", flush=True)


gw.GGUFWriter.write_tensors_to_file = write_tensors_to_file
sys.argv = ["convert_hf_to_gguf.py"] + sys.argv[1:]
runpy.run_path("/root/autodl-tmp/lc/convert_hf_to_gguf.py", run_name="__main__")

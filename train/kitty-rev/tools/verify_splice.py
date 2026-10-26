import hashlib, sys
import gguf

out = sys.argv[1] if len(sys.argv) > 1 else "/root/autodl-tmp/kitty-rev/gguf/mtp-spliced/v4_mtp.gguf"
ref = sys.argv[2] if len(sys.argv) > 2 else "/root/autodl-tmp/ref/ref_sparse.gguf"

o = gguf.GGUFReader(out)
r = gguf.GGUFReader(ref)
ot = {t.name: t for t in o.tensors}
rt = {t.name: t for t in r.tensors}
m64 = [n for n in ot if n.startswith("blk.64.")]
r64 = [n for n in rt if n.startswith("blk.64.")]
print("out_tensors=", len(ot), " blk64_in_out=", len(m64), " blk64_in_ref=", len(r64))
print("block_count=", o.get_key("qwen35.block_count").contents() if o.get_key("qwen35.block_count") else "NA",
      "arch=", o.get_key("general.architecture").contents() if o.get_key("general.architecture") else "NA")
print("missing_in_out=", sorted(set(r64) - set(m64)))


def sha(t):
    return hashlib.sha256(t.data.tobytes()).hexdigest()[:16]


samples = sorted(m64)[:3] + [n for n in sorted(m64) if "nextn" in n][:2]
for n in samples:
    a, b = sha(ot[n]), sha(rt[n])
    print(f"  {n:42s} out={a} ref={b} {'MATCH' if a == b else 'DIFF'}")
ok = len(ot) == 866 and len(m64) == 15 and all(sha(ot[n]) == sha(rt[n]) for n in samples)
print("VERDICT =", "PASS" if ok else "FAIL")

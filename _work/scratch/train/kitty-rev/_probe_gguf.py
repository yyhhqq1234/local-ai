import sys, collections
sys.path.insert(0, "/root/autodl-tmp/lc/gguf-py")
from gguf import GGUFReader
p = "/root/autodl-tmp/kitty-rev/gguf/v5-iq2s.gguf"
r = GGUFReader(p)
c = collections.Counter(t.tensor_type.name for t in r.tensors)
print("PATH", p)
print("TOTAL_TENSORS", len(r.tensors))
for k, v in c.most_common():
    print("TYPE %-12s %d" % (k, v))
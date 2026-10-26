import sys, os
from gguf import GGUFReader

p = sys.argv[1]
r = GGUFReader(p)
print(len(r.tensors), os.path.getsize(p))

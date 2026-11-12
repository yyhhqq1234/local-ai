import sys
import numpy as np
import gguf

p = sys.argv[1] if len(sys.argv) > 1 else '/root/autodl-tmp/kitty-rev/gguf/gen2-iq2s.gguf'
r = gguf.GGUFReader(p)
bad = []
for t in r.tensors:
    if t.name.endswith('.ssm_a'):
        a = np.array(t.data).astype('float32').ravel()
        nn = int((a >= 0).sum())
        mx = float(a.max())
        if nn or mx >= 0:
            bad.append((t.name, a.size, float(a.min()), mx, nn))
        print('%-16s n=%3d min=%.5g max=%.5g nonneg=%d %s' %
              (t.name, a.size, a.min(), mx, nn, 'BAD' if nn else ''))
print('=== BAD ssm_a count =', len(bad))
for b in bad:
    print('   ', b)

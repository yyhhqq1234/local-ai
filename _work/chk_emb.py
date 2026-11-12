import sys
sys.path.insert(0, r'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert\ninfer-all-master')
from tools.artifact import reader
import numpy as np

p = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\oxcoder9b-merged.ninfer'
art = reader.open_artifact(p)
names = art.tensor_names()
print('total tensors:', len(names))
emb = [n for n in names if 'embed' in n.lower()]
print('embedding:', emb[:6])
if emb:
    t = art.tensor(emb[0])
    print('shape:', t.shape, 'dtype:', t.dtype)
    data = t.read()
    a = np.frombuffer(data, dtype=np.uint16)
    rows = t.shape[0]
    ks = 1 if len(t.shape) == 1 else t.shape[1]
    print('rows:', rows, 'cols:', ks)
    for tok in (0, 1, 248069, 248070, 248076, 248077, 248319):
        if tok < rows:
            seg = a[tok*ks:(tok+1)*ks]
            nan = int((seg & 0x7fff) == 0x7fff).sum()
            zero = int((seg == 0).sum())
            print(f'  token {tok}: nan={nan} zero={zero} first8={[hex(int(x)) for x in seg[:8]]}')

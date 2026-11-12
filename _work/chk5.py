import sys
sys.path.insert(0, r'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert\ninfer-all-master')
from tools.artifact import reader
import numpy as np

p = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\oxcoder9b-merged.ninfer'
art = reader.Artifact.open(p)
objs = art.objects          # tuple 属性，不是方法
print('object count:', len(objs))
print('sample names:', [o.name for o in objs[:5]])
emb_objs = [o for o in objs if 'embed' in o.name.lower()]
print('embedding:', [(o.name, getattr(o,'shape',None)) for o in emb_objs[:3]])
if emb_objs:
    o = emb_objs[0]
    raw = art.read_object(o)
    a = np.frombuffer(raw, dtype=np.uint16)
    shape = getattr(o, 'shape', None)
    print('name:', o.name, 'shape:', shape, 'bytes:', len(raw))
    rows = shape[0] if shape else 0
    cols = int(len(a)//rows) if rows else 0
    print('rows:', rows, 'cols:', cols)
    for tok in (0, 1, 248069, 248070, 248076, 248077, 248319):
        if 0 <= tok < rows and cols:
            seg = a[tok*cols:(tok+1)*cols]
            nan = int((seg & 0x7fff) == 0x7fff).sum()
            zero = int((seg == 0).sum())
            print(f'  token {tok}: nan={nan} zero={zero} first6={[hex(int(x)) for x in seg[:6]]}')

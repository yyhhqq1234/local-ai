import sys
sys.path.insert(0, r'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert\ninfer-all-master')
from tools.artifact import reader
import numpy as np

p = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\oxcoder9b-merged.ninfer'
art = reader.Artifact.open(p)
objs = list(art.objects())
print('object count:', len(objs))
# 找 embedding
emb_objs = [o for o in objs if 'embed' in getattr(o, 'name', '').lower()]
print('embedding objects:', [(o.name, getattr(o,'shape',None), getattr(o,'dtype',None)) for o in emb_objs[:3]])
if emb_objs:
    o = emb_objs[0]
    print('name:', o.name, 'shape:', getattr(o,'shape',None), 'dtype:', getattr(o,'dtype',None))
    raw = art.read_object(o)
    a = np.frombuffer(raw, dtype=np.uint16)
    rows = o.shape[0] if hasattr(o,'shape') else 0
    cols = o.shape[1] if hasattr(o,'shape') and len(o.shape)>1 else (len(a)//rows if rows else 0)
    print('rows:', rows, 'cols:', cols, 'total u16:', len(a))
    for tok in (0, 1, 248069, 248070, 248076, 248077, 248319):
        if 0 <= tok < rows and cols:
            seg = a[tok*cols:(tok+1)*cols]
            nan = int((seg & 0x7fff) == 0x7fff).sum()
            zero = int((seg == 0).sum())
            print(f'  token {tok}: nan={nan} zero={zero} first6={[hex(int(x)) for x in seg[:6]]}')

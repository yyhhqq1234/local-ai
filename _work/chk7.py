import sys
sys.path.insert(0, r'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert\ninfer-all-master')
from tools.artifact import reader
import numpy as np

p = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\oxcoder9b-merged.ninfer'
art = reader.Artifact.open(p)
objs = art.objects
tobjs = [o for o in objs if type(o).__name__ == 'TensorObject']
# 找 248320 行的 tensor（embedding / lm_head）
big = [o for o in tobjs if o.shape and o.shape[0] == 248320]
print('248320-row tensors:', [(o.id, o.shape, o.format) for o in big])
for o in big[:2]:
    raw = art.read_object(o)
    a = np.frombuffer(raw, dtype=np.uint16)
    rows, cols = o.shape
    print(f'--- {o.id} shape={o.shape} format={o.format} bytes={len(raw)} cols={cols} ---')
    for tok in (0, 1, 248069, 248076, 248077, 248319):
        if 0 <= tok < rows:
            seg = a[tok*cols:(tok+1)*cols] if len(a) >= (tok+1)*cols else None
            if seg is None: continue
            nan = int((seg & 0x7fff) == 0x7fff).sum()
            zero = int((seg == 0).sum())
            print(f'  token {tok}: nan={nan}/{cols} zero={zero} first6={[hex(int(x)) for x in seg[:6]]}')

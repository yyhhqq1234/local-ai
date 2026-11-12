import sys
sys.path.insert(0, r'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert\ninfer-all-master')
from tools.artifact import reader
import numpy as np

p = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\oxcoder9b-merged.ninfer'
art = reader.Artifact.open(p)
objs = art.objects
print('object count:', len(objs))
o0 = objs[0]
print('type:', type(o0).__name__)
print('attrs:', [a for a in dir(o0) if not a.startswith('_')][:20])
# TensorObject 的属性
tobjs = [o for o in objs if type(o).__name__ == 'TensorObject']
print('tensor objects:', len(tobjs))
if tobjs:
    t0 = tobjs[0]
    print('tensor attrs:', [a for a in dir(t0) if not a.startswith('_')][:20])
    print('first tensor:', {a: getattr(t0, a) for a in ('shape','dtype','name','id') if hasattr(t0, a)})

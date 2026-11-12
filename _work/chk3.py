import sys
sys.path.insert(0, r'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert\ninfer-all-master')
from tools.artifact import reader
import numpy as np

p = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\oxcoder9b-merged.ninfer'
art = reader.Artifact.open(p) if hasattr(reader.Artifact, 'open') else reader.Artifact(p)
print('Artifact methods:', [a for a in dir(art) if not a.startswith('_')][:15])

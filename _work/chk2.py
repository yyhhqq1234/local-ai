import sys
sys.path.insert(0, r'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert\ninfer-all-master')
from tools.artifact import reader
print('reader attrs:', [a for a in dir(reader) if not a.startswith('_')][:20])

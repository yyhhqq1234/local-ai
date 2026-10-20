#!/usr/bin/env python3
"""多线程分片下载器：hf-mirror 镜像，跟随 302，断点续传，sha256 校验。"""
import os,sys,ssl,json,time,threading,hashlib,urllib.request,urllib.error
from queue import Queue

BASE="https://hf-mirror.com"
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
UA={'User-Agent':'curl/8'}

def resolve(repo,f):
    return f"{BASE}/{repo}/resolve/main/{f}"

def head(url):
    r=urllib.request.Request(url,headers=UA,method='HEAD')
    with urllib.request.urlopen(r,context=ctx,timeout=60) as resp:
        return resp.geturl(), int(resp.headers.get('Content-Length',0)), resp.headers.get('Accept-Ranges','')

def download(url,out,nthreads=16,chunk=32*1024*1024):
    real,size,ar=head(url)
    print(f"[dl] size={size} bytes ({size/2**30:.2f} GiB) ranges={ar}",flush=True)
    if size==0: raise SystemExit("size=0")
    parts=[]
    n=max(1,(size+chunk-1)//chunk)
    for i in range(n):
        a=i*chunk; b=min(size-1,(i+1)*chunk-1)
        parts.append((a,b,f"{out}.part{i:04d}"))
    todo=[p for p in parts if not (os.path.exists(p[2]) and os.path.getsize(p[2])==p[1]-p[0]+1)]
    print(f"[dl] chunks={n} done={n-len(todo)} todo={len(todo)}",flush=True)
    lock=threading.Lock(); done_bytes=sum(p[1]-p[0]+1 for p in parts if p not in todo)
    total=size; t0=time.time(); errs=[]
    q=Queue()
    for p in todo: q.put(p)
    def worker():
        nonlocal done_bytes
        while True:
            try: a,b,path=q.get_nowait()
            except Exception: return
            for attempt in range(4):
                try:
                    r=urllib.request.Request(real,headers={**UA,'Range':f'bytes={a}-{b}'})
                    with urllib.request.urlopen(r,context=ctx,timeout=180) as resp:
                        data=resp.read()
                    if len(data)!=b-a+1: raise IOError(f"short {len(data)}!={b-a+1}")
                    with open(path,'wb') as f: f.write(data)
                    with lock:
                        done_bytes+=len(data)
                        el=time.time()-t0; sp=done_bytes/el if el else 0
                        print(f"[dl] {done_bytes/2**30:6.2f}/{total/2**30:.2f} GiB  {sp/2**20:5.1f} MiB/s  eta={(total-done_bytes)/sp/60 if sp else 0:4.1f}min",flush=True)
                    break
                except Exception as e:
                    if attempt==3:
                        with lock: errs.append(f"{a}-{b}: {e}")
                        print(f"[dl] FAIL chunk {a}-{b}: {e}",flush=True)
                    else: time.sleep(1+attempt)
    ths=[threading.Thread(target=worker,daemon=True) for _ in range(nthreads)]
    [t.start() for t in ths]; [t.join() for t in ths]
    if errs: raise SystemExit(f"failed chunks: {errs[:3]}")
    # merge
    print("[dl] merging...",flush=True)
    h=hashlib.sha256()
    tmp=out+".merging"
    with open(tmp,'wb') as w:
        for a,b,path in parts:
            with open(path,'rb') as r:
                while True:
                    buf=r.read(1<<22)
                    if not buf: break
                    w.write(buf); h.update(buf)
    os.replace(tmp,out)
    for _,_,p in parts:
        try: os.remove(p)
        except: pass
    print(f"[dl] sha256={h.hexdigest()}",flush=True)
    return h.hexdigest()

if __name__=="__main__":
    repo,f,out=sys.argv[1],sys.argv[2],sys.argv[3]
    nt=int(sys.argv[4]) if len(sys.argv)>4 else 16
    download(resolve(repo,f),out,nt)

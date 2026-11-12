import socket, sys, time, datetime, json, os

HOST = "connect.bjb1.seetacloud.com"
PORT = 45062
cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)))
for name, key in ((".autodl_host", "HOST"), (".autodl_port", "PORT")):
    p = os.path.join(cfg, name)
    if os.path.exists(p):
        v = open(p).read().strip()
        if v:
            if key == "HOST":
                HOST = v
            else:
                PORT = int(v)

rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
gap = int(sys.argv[2]) if len(sys.argv) > 2 else 120
for i in range(rounds):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    t0 = time.time()
    ok = False
    try:
        s = socket.create_connection((HOST, PORT), timeout=8)
        ok = True
        s.close()
    except Exception as e:
        err = type(e).__name__
    dt = int((time.time() - t0) * 1000)
    print(json.dumps({"round": i + 1, "ts": ts, "host": HOST, "port": PORT,
                      "tcp": ok, "ms": dt,
                      "err": "" if ok else err}, ensure_ascii=False), flush=True)
    if ok:
        print("RECOVERED", flush=True)
        sys.exit(0)
    if i < rounds - 1:
        time.sleep(gap)
print("STILL_DOWN", flush=True)
sys.exit(2)

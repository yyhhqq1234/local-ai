#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_get_multi_resume.py -- get_multi.py 的离线续传/完整性回归（不联网、不用 paramiko）。

为什么要有它：get_multi.py 是 22.7 GiB 训练包的唯一入口，中断概率不低，而它的
「续传」路径此前只被真机跑过一半。本测试把 SSH 换成内存里的假 SFTP，注入
三种真实会发生的故障，断言「要么续对，要么显式报错」，不许静默出错。

三个场景（都与 §14 的签名对应）：
  S1 中断后续传      断在第 4 段的 9 MiB 处 → 重跑必须**从断点开始读**（不是从头），
                     且最终 md5 必须等于源文件
  S2 远端提前 EOF    SFTP 读到一半返回空（文件名对、大小对、内容被截断）
                     当前实现会 `break` 并当成成功 → 合并后 truncate 补零 → 只有 md5 能发现
                     （--skip-md5 下就是**静默损坏**，S1 类）→ 期望：显式 FATAL
  S3 分片布局变化     8 流下了一半，改用 4 流重跑：旧 part 的字节边界与新 slot 不符
                     → 期望：显式识别（布局指纹不匹配），清掉旧 part 重下，不许混用

用法（必须用带 paramiko 的解释器，与真跑一致）：
  C:/ProgramData/anaconda3/python.exe deploy/test_get_multi_resume.py
"""
import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# --- 没有 paramiko 时给个空壳：本测试从不真的连网，只是为了让 import 过 ---
try:
    import paramiko  # noqa: F401
except Exception:
    shell = types.ModuleType("paramiko")
    shell.SSHClient = object
    shell.AutoAddPolicy = object
    sys.modules["paramiko"] = shell

spec = importlib.util.spec_from_file_location("gm", os.path.join(HERE, "get_multi.py"))
GM = importlib.util.module_from_spec(spec)
sys.modules["gm"] = GM
spec.loader.exec_module(GM)

MB = 1 << 20
fails = []
OPEN_LOG = []          # (open_index, start_offset, bytes_read)


class FakeRemoteFile:
    """按绝对偏移注入故障的只读文件对象（模拟 SFTP 的 read/seek）。"""

    def __init__(self, path, fault, idx):
        self.f = open(path, "rb")
        self.pos = 0
        self.fault = fault or {}
        self.idx = idx
        self.nread = 0

    def seek(self, off, whence=0):
        if whence != 0:
            raise ValueError("fake 只支持绝对 seek")
        self.pos = off
        self.f.seek(off)
        return off

    def read(self, n):
        mode = self.fault.get("mode")
        at, until = self.fault.get("at"), self.fault.get("until")
        if at is not None and until is not None:
            if self.pos < at and self.pos + n > at:
                n = at - self.pos                  # 先补齐到故障窗边界
            elif at <= self.pos < until:
                if mode == "timeout":
                    raise IOError("simulated socket timeout")
                return b""                         # 提前 EOF：不抛异常，静默短读
        data = self.f.read(n)
        self.pos += len(data)
        self.nread += len(data)
        return data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.f.close()
        OPEN_LOG.append((self.idx, self._start, self.nread))
        return False


class FakeSFTP:
    def __init__(self, path, fault):
        self.path = path
        self.fault = fault
        self.n = 0

    def stat(self, remote):
        return types.SimpleNamespace(st_size=os.path.getsize(self.path))

    def open(self, remote, mode="rb"):
        assert mode == "rb", mode
        self.n += 1
        f = FakeRemoteFile(self.path, self.fault, self.n)
        f._start = None                            # 由 seek 填（get_multi 一定先 seek）
        orig_seek = f.seek

        def seek(off, whence=0):
            r = orig_seek(off, whence)
            if f._start is None:
                f._start = off
            return r
        f.seek = seek
        return f

    def close(self):
        pass


class FakeClient:
    def __init__(self, path, fault):
        self.sftp = FakeSFTP(path, fault)

    def open_sftp(self):
        return self.sftp

    def close(self):
        pass


def run_download(src, dst, streams, fault=None, extra=()):
    """跑一次 get_multi.main()，返回 rc。"""
    OPEN_LOG.clear()
    GM.connect = lambda: FakeClient(src, fault)
    GM.remote_size_and_md5 = lambda remote: (
        os.path.getsize(src),
        hashlib.md5(open(src, "rb").read()).hexdigest(),
    )
    argv = ["get_multi.py", "--remote", "/fake/remote.bin", "--local", dst,
            "--streams", str(streams), *extra]
    old, sys.argv = sys.argv, argv
    try:
        return GM.main()
    finally:
        sys.argv = old


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    tmp = tempfile.mkdtemp(prefix="gm-resume-")
    src = os.path.join(tmp, "src.bin")
    # 24 MiB 随机源：8 流 → slot 3 MiB，第 4 段覆盖 9–12 MiB
    with open(src, "wb") as f:
        f.write(os.urandom(24 * MB))
    want_md5 = md5(src)

    # ---------------- S1 中断 → 续传 ----------------
    print("=== S1 断点续传（8 流，第 4 段在 9 MiB 处超时直到重试耗尽）===")
    dst = os.path.join(tmp, "s1.bin")
    rc1 = run_download(src, dst, 8, fault={"mode": "timeout", "at": 10 * MB, "until": 12 * MB})
    parts1 = sorted(f for f in os.listdir(tmp) if f.startswith("s1.bin.part"))
    sizes1 = {f: os.path.getsize(os.path.join(tmp, f)) for f in parts1}
    print(f"  rc1={rc1}  残留 part={len(parts1)}  段3 已有 "
          f"{sizes1.get('s1.bin.part003', 0)} 字节")
    if rc1 == 0:
        fails.append("S1 第一次应失败（故障注入未被触发？）")

    rc2 = run_download(src, dst, 8)
    seg3 = [e for e in OPEN_LOG if e[1] is not None and 9 * MB <= e[1] <= 12 * MB]
    ok = (rc2 == 0 and os.path.isfile(dst) and md5(dst) == want_md5)
    print(f"  rc2={rc2}  最终 md5 {'一致' if ok else '不一致'}  续传起点={[e[1] for e in seg3]}")
    if not ok:
        fails.append("S1 续传后 md5 不符或 rc!=0")
    if not seg3:
        fails.append("S1 第 4 段（9-12 MiB）在第二次没有重新打开：无法判断是否续传")
    elif seg3[0][1] < 10 * MB:
        fails.append(f"S1 没有从断点续：第 4 段起点 {seg3[0][1]/MB:.1f} MiB，应 >= 10 MiB（9 MiB + 已存 1 MiB）")
    transferred2 = sum(e[2] for e in OPEN_LOG)
    print(f"  第二次实际传输 {transferred2 / MB:.1f} MiB（源 {24} MiB，续传应明显更少）")
    if transferred2 >= 24 * MB:
        fails.append("S1 第二次仍然全量重传（续传没生效）")
    if not os.path.exists(os.path.join(tmp, "s1.bin.part000")):
        print("  [✓] 合并后 part 已清理")
    else:
        fails.append("S1 合并后 part 没清理")

    # ---------------- S2 远端提前 EOF ----------------
    print("\n=== S2 远端提前 EOF（第 1 段 2 MiB 后返回空，不抛异常）===")
    dst2 = os.path.join(tmp, "s2.bin")
    rc = run_download(src, dst2, 8, fault={"mode": "eof", "at": 2 * MB, "until": 3 * MB}, extra=("--skip-md5",))
    bad = os.path.isfile(dst2) and md5(dst2) != want_md5
    print(f"  rc={rc}  目标文件存在={os.path.isfile(dst2)}  内容损坏={bad}")
    if rc == 0 and bad:
        fails.append("S2 短读被当成成功且 --skip-md5 下静默产出损坏文件（S1 式静默错）")
        print("  [✗] 静默损坏：rc=0 却内容不对")
    elif rc != 0:
        print("  [✓] 显式失败（没有静默损坏）")

    # ---------------- S3 布局变化 ----------------
    print("\n=== S3 8 流残留 part → 改 4 流重跑 ===")
    dst3 = os.path.join(tmp, "s3.bin")
    rc_a = run_download(src, dst3, 8, fault={"mode": "timeout", "at": 10 * MB, "until": 12 * MB})
    left = sorted(f for f in os.listdir(tmp) if f.startswith("s3.bin.part"))
    print(f"  rc_a={rc_a}（预期非 0）  残留 part={len(left)}")
    rc_b = run_download(src, dst3, 4)
    bad3 = os.path.isfile(dst3) and md5(dst3) != want_md5
    print(f"  rc_b={rc_b}  最终文件={'有' if os.path.isfile(dst3) else '无'}  "
          f"md5 {'一致' if not bad3 else '不一致'}")
    if rc_b == 0 and bad3:
        fails.append("S3 布局变化后混用旧 part，产出损坏文件却 rc=0")
        print("  [✗] 静默损坏：旧布局 part 被直接续用")
    elif rc_b != 0:
        print("  [✓] 显式拒绝（不混用旧布局；按提示 --reset-parts 重来）")
    elif not bad3:
        print("  [✓] 结果正确（识别布局变化并重置了旧 part）")

    # ---------------- S4 --reset-parts 之后必须能下对 ----------------
    print("\n=== S4 同上残留 + --reset-parts → 应成功且 md5 一致 ===")
    rc_c = run_download(src, dst3, 4, extra=("--reset-parts",))
    okc = rc_c == 0 and os.path.isfile(dst3) and md5(dst3) == want_md5
    print(f"  rc_c={rc_c}  md5 {'一致' if okc else '不一致'}")
    if not okc:
        fails.append(f"S4 --reset-parts 后没下对（rc={rc_c}）")

    print("\nPASS: 续传/短读/布局三种情形都「要么续对、要么显式报错」"
          if not fails else f"\nFAIL: {fails}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""adopt_instance.py —— 控制台换机/克隆后，一键接管新实例（写 .autodl_* 连接文件）

用途
  实例被迁移/克隆/重建后 uuid、ssh_host、ssh_port、密码全变，
  本脚本从 AutoDL API 列出所有实例，挑出 running 的那台，把连接参数写到本目录：
    .autodl_uuid / .autodl_host / .autodl_port
  密码 API 不返回，需手工写 .autodl_pass（或用 --pass 传入）。

用法
  python adopt_instance.py                 # 列出全部实例并自动接管唯一 running 的
  python adopt_instance.py --pass XXX      # 同时写密码
  python adopt_instance.py --uuid <uuid>   # 指定实例
  python adopt_instance.py --list          # 只看不写
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autodl_power as ap  # noqa: E402


def main():
    g = argparse.ArgumentParser()
    g.add_argument("--pass", dest="pw", default="")
    g.add_argument("--uuid", default="")
    g.add_argument("--list", action="store_true")
    a = g.parse_args()

    j = ap.api("/instance", {"page_index": 1, "page_size": 50})
    if j.get("code") != "Success":
        print(f"[FATAL] 列表查询失败: {j}", file=sys.stderr)
        return 2
    arr = (j.get("data") or {}).get("list") or []
    if not arr:
        print("[FATAL] 账号下没有实例", file=sys.stderr)
        return 2

    print(f"{'uuid':<26} {'status':<12} {'gpu':<22} ssh")
    for it in arr:
        print(f"{it.get('uuid',''):<26} {str(it.get('status','')):<12} "
              f"{str(it.get('gpu_spec_uuid') or it.get('machine_id') or ''):<22} "
              f"{it.get('ssh_host')}:{it.get('ssh_port')}")

    if a.list:
        return 0

    pick = None
    if a.uuid:
        pick = next((x for x in arr if x.get("uuid") == a.uuid), None)
    else:
        run = [x for x in arr if x.get("status") == "running"]
        if len(run) == 1:
            pick = run[0]
        elif len(run) > 1:
            print("[warn] 多台 running，请用 --uuid 指定")
            return 3
        else:
            print("[FATAL] 没有 running 实例（先在控制台开机/迁移）", file=sys.stderr)
            return 4
    if not pick:
        print("[FATAL] 找不到指定实例", file=sys.stderr)
        return 4

    open(os.path.join(HERE, ".autodl_uuid"), "w").write(pick.get("uuid", ""))
    open(os.path.join(HERE, ".autodl_host"), "w").write(pick.get("ssh_host") or "")
    open(os.path.join(HERE, ".autodl_port"), "w").write(str(pick.get("ssh_port") or ""))
    if a.pw:
        open(os.path.join(HERE, ".autodl_pass"), "w").write(a.pw)
    print(f"[ok] 已接管 uuid={pick.get('uuid')} ssh={pick.get('ssh_host')}:{pick.get('ssh_port')}"
          + ("（密码已写）" if a.pw else "（密码未写：--pass 或手工写 .autodl_pass）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

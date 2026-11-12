# -*- coding: utf-8 -*-
"""budget_transfer.py -- 回传时间预算（两条通道并行时，总时长由谁决定）。

输入是实测带宽（不是理论值）：
  SSH 每连接 ~0.70 MiB/s（AutoDL 限速）；汇总实测 4/8/16/32 流 = 2.49/5.13/8.8/18 MiB/s
  夸克网盘：上传取决于会员档（18-37 min/22.7 GiB），下载本机实测 30-40 MB/s
"""
import argparse

GB = 1024.0


def mins(mib, mib_s):
    return mib / mib_s / 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ninfer-gib", type=float, default=10.0)
    ap.add_argument("--pack-gib", type=float, default=22.7)
    ap.add_argument("--adapter-mib", type=float, default=160.0)
    ap.add_argument("--ssh-mib-s", type=float, default=18.0, help="32 流实测汇总")
    ap.add_argument("--single-mib-s", type=float, default=0.70)
    ap.add_argument("--md5-mib-s", type=float, default=150.0, help="本地顺序读 md5")
    ap.add_argument("--quark-up-min", type=float, nargs=2, default=(18, 37))
    ap.add_argument("--quark-down-mib-s", type=float, nargs=2, default=(20, 35))
    a = ap.parse_args()

    ninfer = a.ninfer_gib * GB
    pack = a.pack_gib * GB
    print("=== 通道 A：SSH 多流（.ninfer + adapter）===")
    t_n = mins(ninfer, a.ssh_mib_s)
    t_md5 = mins(ninfer, a.md5_mib_s)
    t_a = mins(a.adapter_mib, a.single_mib_s)
    print(f"  .ninfer {a.ninfer_gib:.1f} GiB / {a.ssh_mib_s:.0f} MiB/s = {t_n:.1f} min")
    print(f"  本地 md5 校验（{a.md5_mib_s:.0f} MiB/s）= {t_md5:.1f} min  ← 别忘，22.7G 的包也要算")
    print(f"  adapter {a.adapter_mib:.0f} MiB 单流 {a.single_mib_s:.2f} MiB/s = {t_a:.1f} min")
    print(f"  合计 ≈ {t_n + t_md5 + t_a:.0f} min")

    print("\n=== 通道 B：夸克网盘（训练包）===")
    lo, hi = a.quark_up_min
    dlo, dhi = a.quark_down_mib_s
    print(f"  上传（操作者侧 AutoPanel）：{lo:.0f}–{hi:.0f} min")
    print(f"  本地下载 {a.pack_gib:.1f} GiB："
          f"{mins(pack, dhi):.0f} min（{dhi:.0f} MiB/s）– {mins(pack, dlo):.0f} min（{dlo:.0f} MiB/s）")
    print(f"  小计 ≈ {lo + mins(pack, dhi):.0f} – {hi + mins(pack, dlo):.0f} min")

    print("\n=== 总时长（两通道并行）===")
    wall_lo = max(t_n + t_md5 + t_a, lo + mins(pack, dhi))
    wall_hi = max(t_n + t_md5 + t_a, hi + mins(pack, dlo))
    print(f"  墙钟 ≈ {wall_lo:.0f} – {wall_hi:.0f} min（瓶颈在夸克上传，不在 SSH）")

    print("\n=== 若夸克不可用（全走 SSH）===")
    fallback = t_n + t_md5 + t_a + mins(pack, a.ssh_mib_s)
    print(f"  22.7 GiB / {a.ssh_mib_s:.0f} MiB/s = {mins(pack, a.ssh_mib_s):.0f} min → 合计 ≈ {fallback:.0f} min")
    print(f"  ⚠ 32 流是 10 GiB 档位的实测；22.7 GiB 长时间跑到后段可能降到 12-15 MiB/s，"
          f"留 30% 余量 ≈ {fallback * 1.3:.0f} min")

    print("\n=== 校验固定成本（与通道无关）===")
    for name, gib, mibs in ((".ninfer", a.ninfer_gib, 300), ("trainpack", a.pack_gib, 300)):
        print(f"  md5 {name:9s} {gib:5.1f} GiB @ {mibs} MiB/s = {mins(gib * GB, mibs):.1f} min")
    print("  建议：边下边算（get_multi 已内置合并后 md5），不要「全部下完再统一验」")


if __name__ == "__main__":
    main()

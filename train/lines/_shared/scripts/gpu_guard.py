"""GPU / CPU 资源防护 —— 所有评测脚本的统一入口（防系统卡顿）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么必须
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PITFALLS D1 记录过的坑：显存 reserved 触顶后，Windows WDDM（不支持
expandable_segments）会把系统内存当显存后备，数据经 PCIe 往返 ——
表现是 **GPU util 100% 但 power 只有 53W（假忙），整个系统间歇性卡顿**。

评测脚本原来完全没有防护：
  · 没有 `set_per_process_memory_fraction`（显存无上限）
  · 没有 `set_num_threads`（OMP/MKL 默认吃满 20 核）
  · 没有 BelowNormal 优先级（和前台程序抢 CPU）

batch 生成会同时抬高显存峰值与 CPU 占用，不加防护比逐条跑更容易卡。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法（必须在模型加载前调用）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    import gpu_guard
    gpu_guard.apply()          # 默认 0.88 显存上限 / 6 线程 / BelowNormal
    model, tok = load_model(...)

环境变量可覆盖：
    GUARD_VRAM_FRAC   默认 0.88（训练用 0.93；评测留更多余量给系统）
    GUARD_THREADS     默认 6
    GUARD_PRIORITY    默认 1（0=不改优先级）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os
import sys


def apply(vram_frac=None, threads=None, priority=None, verbose=True):
    frac = float(os.environ.get("GUARD_VRAM_FRAC", "0.88")) if vram_frac is None else vram_frac
    th = int(os.environ.get("GUARD_THREADS", "6")) if threads is None else threads
    pri = (os.environ.get("GUARD_PRIORITY", "1") == "1") if priority is None else priority

    msgs = []

    # ① CPU 线程限制：必须在 torch 首次运算前设，否则被库覆盖
    try:
        import torch
        torch.set_num_threads(th)
        try:
            torch.set_num_interop_threads(1)
        except Exception:
            pass   # 已初始化过会抛，忽略
        msgs.append("CPU threads=%d" % th)
    except Exception as e:
        msgs.append("CPU threads 设置失败: %s" % e)

    # ② 显存硬上限：必须在第一次 CUDA 分配前调用
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.set_per_process_memory_fraction(frac)
            msgs.append("VRAM 上限=%.2f×物理" % frac)
        else:
            msgs.append("CUDA 不可用，跳过 VRAM 限制")
    except Exception as e:
        msgs.append("VRAM 限制失败: %s" % e)

    # ③ 进程优先级降到 BelowNormal：让 GUI / 前台程序优先拿 CPU
    if pri:
        try:
            import psutil
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            msgs.append("优先级 BelowNormal")
        except Exception as e:
            msgs.append("优先级设置失败: %s" % e)

    if verbose:
        print("[guard] " + " | ".join(msgs))
    return msgs


def vram_report(tag=""):
    """打印当前显存占用（排查卡顿时用）"""
    try:
        import torch
        alloc = torch.cuda.memory_allocated() / 2 ** 30
        resv = torch.cuda.memory_reserved() / 2 ** 30
        free, total = torch.cuda.mem_get_info()
        print("[guard] %s alloc=%.2f reserved=%.2f free=%.2f/%.2f GiB"
              % (tag, alloc, resv, free / 2 ** 30, total / 2 ** 30))
        # reserved 超过 90% 物理显存 → 有 WDDM 换页风险
        if resv > total / 2 ** 30 * 0.90:
            print("[guard] ⚠ reserved 已超物理的 90%%，有换页卡顿风险，降 batch")
    except Exception:
        pass


if __name__ == "__main__":
    apply()
    try:
        import torch
        if torch.cuda.is_available():
            print("device:", torch.cuda.get_device_name(0))
            vram_report("当前")
    except Exception as e:
        print("torch 不可用:", e)

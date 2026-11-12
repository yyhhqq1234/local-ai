# -*- coding: utf-8 -*-
"""把本轮新增的 7 条坑插入 train/PITFALLS.md（G 段），并在自检清单追加 3 项。"""
import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "train", "PITFALLS.md")

G = """## G 外部下载 / 云实例类（7 条，2026-10-29 新增）

### G1 「尺寸对」不等于「内容对」：truncate 预分配的稀疏文件把整轮校验骗过去 ★★★★
```text
现象 18 个 safetensors 片，磁盘尺寸与 HF API 清单逐个一致 → 我判定「18/18 全齐、0 不符」；
     实际 5 片（07/08/13/14/18）内容全零，头 8 字节（header length）= 0。
     真跑 merge 才炸：SafetensorError: invalid JSON in header: EOF while parsing a value at line 1 column 0
根因 首轮下载用 truncate 预分配（NTFS 稀疏：尺寸立刻到位、内容全 0），线程超时静默死；
     第二轮 skip 判据写成 head_size(url) == getsize(out) → 稀疏件被判已完成直接跳过。
判据 size 相等 + safetensors 头可解析(0<len<200MB) + 中部 4KB 非全零，三条缺一不可。
工具 scripts/dl_base_local.py:is_complete() / --verify（退出码 1 = 有坏片）
```

### G2 残留 `.part` 也是零内容满尺寸，续传逻辑见 `pos>=need` 立刻返回 ★★★★
```text
现象 18 号片按 G1 判据删掉重下，[done] 尺寸一致=True，但头仍是 0 —— 二次踩坑。
根因 fetch_range 以 part 当前大小做续传起点：首轮死掉留下的 part 尺寸已满且内容全零，
     pos >= need 直接 return，合并出来还是零文件。
修复 [redo] 必须连 out + 全部 out.part* 一起删；[done] 之后再跑一次 is_complete 兜底。
```

### G3 AutoDL 按量实例「关机 = 释放」，不保证抢回同一台机 ★★★
```text
现象 15:12 主动 off 止损，之后 15:54~16:13 连续 18 次 on 全返回 BadRequest 无可用 GPU 资源（bj-B1）。
结论 省钱与保机互斥。关机前先算：剩余工作量值多少钱 vs 抢不回来的风险（含重传 50GB 的时间成本）。
```

### G4 市场机的 `max_instance_disk_size` 普遍是 54GB，锁死「云上 merge+gguf」路线 ★★★
```text
74 台空闲 >=24G 显存机器，数据盘上限全 54GB；而 base 52 + merged 52 + gguf 52 = 156GB 峰值。
等价路径 把 merge/gguf/quantize 搬回本机（分片 merge 峰值 RAM<6GB），云端只剩 tools.convert 打包。
```

### G5 GitHub 直连报 schannel `CRYPT_E_NO_REVOCATION_CHECK`，不是网络不通 ★★
```text
curl: (35) schannel: next InitializeSecurityContext failed: CRYPT_E_NO_REVOCATION_CHECK (0x80092012)
所有 curl 加 --ssl-no-revoke 即通（api.github.com / raw.githubusercontent.com / release 下载均适用）。
hf-mirror 不需要。
```

### G6 `runpy.run_path` 不把目标脚本目录塞进 sys.path → `from conversion import` 失败 ★★
```text
现象 用 runpy 包一层跑 convert_hf_to_gguf.py，报 ModuleNotFoundError: No module named 'conversion'
根因 python script.py 会把脚本目录放 sys.path[0]，runpy.run_path 不会（sys.path[0] 仍是调用者目录）
修复 sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
（顺带：路径参数化 —— CONVERT_PY 环境变量，别硬编码 /root/autodl-tmp/...）
```

### G7 监控子 agent 会把「主动关机」误判成「通道异常」，且 subagent 无消息通道 ★★
```text
现象 [MONITOR] 连续 5 条「35299 仍拒绝 / 状态=黄-通道异常」，实际是 15:12 主动关的机。
根因 监控判据是「SSH 不通 = 黄/红」，不含「实例是否被主动 shutdown」；
     subagent 收不到 send_message（list_agents 里只有 lead）→ 无法纠正。
处置 关机后监控报告一律视为噪声，以 run-notes 记录为准；重要状态变更要靠主 agent 侧判定。
```

"""

with io.open(P, encoding="utf-8") as f:
    txt = f.read()

anchor = "## 快速自检清单（开训前逐条打勾）"
assert anchor in txt, "anchor missing"
if "## G 外部下载 / 云实例类" in txt:
    print("[skip] G 段已存在")
else:
    txt = txt.replace(anchor, G + anchor)
    txt = txt.replace(
        "```\n",
        "```\n", 1)
    # 清单追加
    add = (
        "[ ] 基座完整性走内容级校验（size + safetensors 头 + 中部非零），不信裸 size（见 G1/G2）\n"
        "[ ] 重下坏片时 out 与 .part* 一并删除（见 G2）\n"
        "[ ] 云实例关机前确认能抢回 / 或本地已有完整基座与量化链（见 G3/G4）\n"
    )
    marker = "```\n"
    idx = txt.rfind(marker)
    txt = txt[:idx] + add + txt[idx:]
    with io.open(P, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    print("[ok] G 段 7 条 + 清单 3 项已写入", P)

with io.open(P, encoding="utf-8") as f:
    t = f.read()
print("条目总数:", t.count("\n### "))
print("含 G1..G7:", all(f"G{i}" in t for i in range(1, 8)))

# kitty-reverse 清理台账（删除前记录）

- 生成时间: 2026-10-27T12:20:10.799Z
- 删除 27 个文件，合计 168.4 MB
- 核心保护: train-kitty-core.jsonl 已收录全部训练内容（5602 条唯一，源 8448 行零丢失）

| # | 文件 | 行 | MB | sha256(前16) | 判定 |
|---|---|---|---|---|---|
| 1 | final-re.jsonl | 1608 | 1.57 | 99ad9b153efa6c93 | 内容已全部进入 train-kitty-core.jsonl（1608/1608 覆盖） |
| 2 | final-re-final.jsonl | 1842 | 2.45 | ad238a1cdf0fddd2 | 同上（1796 新增已并入，46 重复） |
| 3 | final-re-refined.jsonl | 1815 | 2.42 | c679478c12484091 | 同上（1269 新增已并入，546 重复） |
| 4 | final-re-dedup.jsonl | 2493 | 2.68 | 6bb5d237bda5732b | 同上（645 新增已并入，1848 重复） |
| 5 | mix-re.jsonl | 690 | 0.65 | 440988f12623eea2 | 同上（284 新增已并入，406 重复） |
| 6 | re-qc/gold.jsonl | 1811 | 2.40 | 112a1c3327b4dd0c | 413 唯一对 100% 已在 core（经 final-re），此行文件为重复档 |
| 7 | kitty-contracts/sft-kitty.jsonl | 483 | 0.41 | 0361c87f0abe2d3d | 391 唯一对 100% 已在 core，契约样本已吸收 |
| 8 | re-iter/iter-all.jsonl | 804 | 0.73 | 03284084aac216b5 | 804 条 100% 已在 core |
| 9 | re-qc/reject.jsonl | 20427 | 154.24 | 02afd14fd1742070 | 评分 reject 档 20427 行，训练不使用，占 161MB |
| 10 | re-iter/batch-r28-r31.jsonl | 62 | 0.05 | 9ffac7faf32092e4 | 批次分片，100% 已汇总进 iter-all → core |
| 11 | re-iter/batch-r32-r35.jsonl | 64 | 0.05 | bf69c05177441008 | 批次分片，100% 已汇总进 iter-all → core |
| 12 | re-iter/r01-tools.jsonl | 273 | 0.28 | fb4e1a3ab52841bf | 批次分片，100% 已汇总进 iter-all → core |
| 13 | re-iter/r02-pitfalls.jsonl | 31 | 0.03 | 57e379b7cf3abd54 | 批次分片，100% 已汇总进 iter-all → core |
| 14 | re-iter/r03-criteria.jsonl | 31 | 0.03 | ef5a098a38ab51d1 | 批次分片，100% 已汇总进 iter-all → core |
| 15 | re-iter/r06-scan-r07-pchain.jsonl | 22 | 0.02 | d287513f18022613 | 批次分片，100% 已汇总进 iter-all → core |
| 16 | re-iter/r08-r10-internal.jsonl | 30 | 0.03 | 08c3d413c26b4026 | 批次分片，100% 已汇总进 iter-all → core |
| 17 | re-iter/r11-r14-adv.jsonl | 42 | 0.04 | c385f2e3a10e8d69 | 批次分片，100% 已汇总进 iter-all → core |
| 18 | re-iter/r15-r20-final.jsonl | 61 | 0.05 | b435e5326055324c | 批次分片，100% 已汇总进 iter-all → core |
| 19 | re-iter/r21-pitfalls.jsonl | 66 | 0.06 | 67e2e728a3a0085c | 批次分片，100% 已汇总进 iter-all → core |
| 20 | re-iter/r22-r27-discipline.jsonl | 45 | 0.04 | 7c7d404ad21af7d7 | 批次分片，100% 已汇总进 iter-all → core |
| 21 | re-iter/r28-r30-gates.jsonl | 41 | 0.03 | 0f8c9cbb814cba5e | 批次分片，100% 已汇总进 iter-all → core |
| 22 | re-iter/r31-drvfail.jsonl | 21 | 0.02 | 8b91fa083a8f9672 | 批次分片，100% 已汇总进 iter-all → core |
| 23 | re-iter/r32-r34-ops.jsonl | 43 | 0.03 | ea51cf5a90732f6c | 批次分片，100% 已汇总进 iter-all → core |
| 24 | re-iter/r35-dbvm2.jsonl | 21 | 0.02 | 32283701c96d4e30 | 批次分片，100% 已汇总进 iter-all → core |
| 25 | re-iter/r36-miscops.jsonl | 22 | 0.02 | 35484f70732a2326 | 批次分片，100% 已汇总进 iter-all → core |
| 26 | re-iter/r37-pe-elf.jsonl | 27 | 0.02 | 247fc4656b112c0a | 批次分片，100% 已汇总进 iter-all → core |
| 27 | re-iter/r38-pe-deep.jsonl | 28 | 0.03 | 0746e8a83ce7ed1c | 批次分片，100% 已汇总进 iter-all → core |

## 保留
```
train-kitty-core.jsonl        训练核心（5 份源去重并集 5602 条，统一 system）
re-qc/silver.jsonl            银样本候选池 8815 行（2046 唯一，未采用，保留备用）
re-qc/scored.jsonl            评分台账 31053 行（reject 档已清理）
kitty-contracts/              tools.json / ops.json / tool-tasks.json / STATS.json（工具契约）
re-iter/                      COVERAGE.json / PLAN.json / drce-*.json（构建溯源）
```

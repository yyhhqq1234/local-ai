# -*- coding: utf-8 -*-
"""KV 容量估算（决定 64K/256K 是否装得下）"""
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Qwen3.5-9B: 32 层，layer_types 每 4 层一个 full_attention → 8 个 full 层；linear 层常量状态
FULL_LAYERS = 8
KV_HEADS = 4
HEAD_DIM = 256
WEIGHTS = {'Q5_K_M': 6.19, 'Q6_K': 7.2, 'IQ4_XS': 4.8, 'Q5_K_M+imx': 6.3}
VRAM = 12.2

print('每 token KV 体积')
per = {}
for name, b in (('f16', 2), ('q8_0', 1)):
    per[name] = FULL_LAYERS * 2 * KV_HEADS * HEAD_DIM * b
    print('  %-5s %.1f KB/token' % (name, per[name] / 1024))

print('\n各上下文下的 KV（GiB）')
for ctx in (65536, 131072, 262144):
    row = '  ctx %3dK : ' % (ctx // 1024)
    for name in ('f16', 'q8_0'):
        row += '%s=%.2f  ' % (name, per[name] * ctx / 1024 ** 3)
    print(row)

print('\n组合可行性（权重 + KV + 预留 0.8 GiB 给 CUDA/compute）')
for wname, wgb in WEIGHTS.items():
    for ctx in (65536, 262144):
        for kvname in ('f16', 'q8_0'):
            need = wgb + per[kvname] * ctx / 1024 ** 3 + 0.8
            flag = 'OK' if need <= VRAM else '超'
            print('  %-10s ctx %3dK kv %-5s 需 %.2f GiB  → %s' % (wname, ctx // 1024, kvname, need, flag))

import json
p = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\config.json'
with open(p, encoding='utf-8') as f: c = json.load(f)
print('=== 全部顶层 key ===')
for k in c: 
    v = c[k]
    if isinstance(v, (int, float, str, bool)) or v is None:
        print(f'  {k}: {v}')
print()
print('=== 关键字段 ===')
for k in ('num_hidden_layers','layer_types','full_attention_interval','num_attention_heads','num_key_value_heads','head_dim','hidden_size','attn_output_gate','linear_conv_kernel_dim','linear_key_head_dim','linear_value_head_dim','linear_num_key_heads','linear_num_value_heads','vocab_size','tie_word_embeddings','num_experts'):
    v = c.get(k, '<MISSING>')
    if isinstance(v, list): print(f'  {k}: [{len(v)}] {v[:10]}')
    else: print(f'  {k}: {v}')
    # 也看嵌套
    if v == '<MISSING>':
        for k2 in c:
            if isinstance(c[k2], dict) and k in c[k2]:
                print(f'    └ nested in {k2}: {c[k2][k]}')

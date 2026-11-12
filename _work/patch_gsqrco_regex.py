# -*- coding: utf-8 -*-
"""一次性修补 gsq_rco_plan.py：
1) 把 gguf 侧 A_log 的真实名字（blk.N.ssm_a / ssm_conv1d.weight）纳入结构保护
2) 输出改成锚定+转义的 regex（^...$）：llama.cpp 用 std::regex_search 匹配，
   裸名字里的 '.' 是通配符，且 "blk.0.ssm_a" 会前缀命中 "blk.0.ssm_alpha.weight"，
   导致 Q8_0 被后面的 Q2_K 覆盖 —— 这是 blk.0.ssm_alpha 变 Q2_K 的真因。
"""
import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'train', 'scripts', 'gsq_rco_plan.py')
t = io.open(P, encoding='utf-8').read()

# 1) 保护：A_log 在 gguf 里叫 ssm_a（无 .weight），另有 ssm_conv1d.weight
if 'ssm_a' not in t:
    old_prot = '    (r"\\.A_log$", "Q8_0"),'
    new_prot = ('    (r"\\.A_log$", "Q8_0"),\n'
                '    (r"\\.ssm_a$", "Q8_0"),            # gguf 侧 A_log 的真实名字（无 .weight 后缀）\n'
                '    (r"\\.ssm_conv1d\\.weight$", "Q8_0"),')
    assert old_prot in t, 'protect anchor missing'
    t = t.replace(old_prot, new_prot)

# 2) 输出锚定正则
old_out = ('    with open(a.out, "w", encoding="utf-8") as f:\n'
           '        for nm in sorted(plan):\n'
           '            f.write(f"--tensor-type {nm}={plan[nm]}\\n")')
new_out = ('    import re as _re\n'
           '    with open(a.out, "w", encoding="utf-8") as f:\n'
           '        for nm in sorted(plan):\n'
           '            pat = "^" + _re.escape(nm) + "$"\n'
           '            f.write(f"--tensor-type {pat}={plan[nm]}\\n")')
assert old_out in t, 'output anchor missing'
t = t.replace(old_out, new_out)

io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('[ok] patched', P)

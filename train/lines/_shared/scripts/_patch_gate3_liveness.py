# -*- coding: utf-8 -*-
"""patch_gate3_liveness.py — 给 eval_gate3 加「引擎存活检查 + INVALID 判定」

事故（2026-11-02 22:00）
  gen7-600 评测跑到 req#35 时引擎崩溃，后续 chat() 全部抛 ConnectionRefused，
  被 except 吞成 out=""，最后统计出「空回复率 82%」——把引擎崩溃伪装成模型不写。
修法
  ① 每条题目前 GET /v1/models 探活（3s 超时），不可达即判 INVALID 并中止
  ② 中止时不出分层表（避免误读），只打印已完成的条数与失败点
  ③ 退出码：0=全绿 / 1=指标未达标 / 3=INVALID（引擎不可用或中途死亡）
"""
p = 'train/lines/_shared/scripts/eval_gate3.py'
s = open(p, encoding='utf-8').read()

# 1) 增加探活函数
if 'def engine_alive' not in s:
    s = s.replace('''EVAL_DIR = ROOT / "train/lines/27b-kittyrev/data/eval"''',
'''EVAL_DIR = ROOT / "train/lines/27b-kittyrev/data/eval"


def engine_alive(endpoint, timeout=3):
    """GET /models 探活：引擎崩了要判 INVALID，不能把连接失败记成"模型空回复"。"""
    import urllib.request
    try:
        url = endpoint.rstrip("/") + "/models"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return b'"id"' in r.read(4096)
    except Exception:  # noqa: BLE001
        return False''')
    print('added engine_alive')

# 2) 每轮前探活 + 中止逻辑
old_loop = '''    terms = load_terms()
    rows = []
    t0 = time.time()
    for n, it in enumerate(items, 1):
        out, used = "", 0'''
new_loop = '''    terms = load_terms()
    rows = []
    t0 = time.time()
    aborted = None
    for n, it in enumerate(items, 1):
        if not engine_alive(a.endpoint):
            aborted = f"第 {n} 条（{it['id']}）前探活失败：{a.endpoint} 不可达"
            print(f"\\n[INVALID] {aborted}", flush=True)
            break
        out, used = "", 0'''
assert old_loop in s
s = s.replace(old_loop, new_loop)

# 3) 请求异常也标记为引擎问题（连续 2 次异常即中止）
old_exc = '''            except Exception as e:  # noqa: BLE001
                print(f"[FAIL] {it['id']} {type(e).__name__} {e}", flush=True)
                out = ""'''
new_exc = '''            except Exception as e:  # noqa: BLE001
                print(f"[FAIL] {it['id']} {type(e).__name__} {e}", flush=True)
                if not engine_alive(a.endpoint):
                    aborted = f"{it['id']} 请求异常且引擎不可达：{type(e).__name__}"
                    print(f"[INVALID] {aborted}", flush=True)
                    break
                out = ""'''
if old_exc in s:
    s = s.replace(old_exc, new_exc)
    print('patched exception path')

# 4) 结尾：INVALID 优先，不打印分层表
old_tail = '''    # ── 分层统计 ──'''
new_tail = '''    if aborted:
        print("=" * 74)
        print(f"[INVALID] 评测作废：{aborted}")
        print(f"已完成 {len(rows)}/{len(items)} 条；后面的空回复是连接失败，不是模型行为。")
        print("处置：重启引擎后重跑（本次不产出指标，也不落 responses 文件）")
        print("=" * 74)
        return 3

    # ── 分层统计 ──'''
assert old_tail in s
s = s.replace(old_tail, new_tail, 1)

open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('gate3 liveness patched')

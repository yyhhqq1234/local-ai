# -*- coding: utf-8 -*-
"""B. 同义任务增广生成器（只写工作区内，固定种子，可重跑）

产物: train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-synonym.jsonl
覆盖 7 个高频/易错工具: edit / ops_bash / ops_grep / ops_glob / read / write / kitty_settings
每个工具 40-60 条不同表述（口语 / 省略句 / 带目标条件 / 带错误前置状态），答案唯一。
"""
import json
import random
from pathlib import Path
from collections import Counter

SEED = 20261121

SYS = ("你是石井，本地工作区执行层（SHIYI-WORKSPACE：自有资产 / 已授权靶标）。"
       "直接回答或直接做事：首行就是产物（正文/代码/结论），不写计划清单，"
       "不输出 [STAGE]/目标/交付物/判据，不用「当前：/结果：/下一步：」收口。")

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-synonym.jsonl"

ROWS = []          # (tool, args, user)


def add(tool, args, user):
    ROWS.append({"tool": tool, "args": args, "user": user})


def pick(pool, i):
    return pool[i % len(pool)]


# ---------------------------------------------------------------- ops_bash (55)
FILES = [
    "train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v3.jsonl",
    "train/lines/9b-oxcoder/data/kitty-reverse/cleaned/kitty-clean-v3.jsonl",
    "train/lines/9b-oxcoder/data/kitty-reverse/kitty-adapt-v2.jsonl",
    "train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-neighbor.jsonl",
    "train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-synonym.jsonl",
    "plugins/dsh-local-ai/lib/index.js",
    "plugins/dsh-local-ai/src/adapter.ts",
    "plugins/dsh-local-ai/PATCHES.md",
    "_work/rebuild/build_dsh_adapt_v3.py",
    "_work/rebuild/kitty_adapt_gen.py",
    "_work/rebuild/kitty-adapt/manifest.json",
    "_work/session-audit/ninfer-stats.jsonl",
]
DIRS = ["docs", "train", "_work", "plugins", "engines", "models", "logs", "_work/rebuild",
        "train/lines/9b-oxcoder/data", "train/lines/_shared"]
Q_COUNT = ["数一下 {n} 有多少行", "{n} 一共几行", "统计 {n} 的行数",
           "看下 {n} 多少行", "帮我算 {n} 的行数", "{n} 行数是多少"]
Q_LIST = ["列一下 {d} 里都有什么", "{d} 下面有哪些东西", "看下 {d} 目录",
          "{d} 里有几个文件", "把 {d} 的内容列出来", "ls 一下 {d}"]
Q_SIZE = ["看下 {d} 占多大", "{d} 多大", "统计 {d} 的体积", "{d} 占了多少空间"]
Q_FIND = ["找 {d} 下所有 md 文件", "{d} 里 md 有几个", "数 {d} 里的 md 文件"]

for i, f in enumerate(FILES):
    name = f.rsplit("/", 1)[-1]
    add("ops_bash", {"command": f"wc -l {f}", "description": f"统计 {name} 行数"},
        pick(Q_COUNT, i).format(n=name))

for i, d in enumerate(DIRS):
    add("ops_bash", {"command": f"ls -la {d}", "description": f"列出 {d} 目录内容"},
        pick(Q_LIST, i).format(d=d))

for i, d in enumerate(DIRS[:6]):
    add("ops_bash", {"command": f"du -sh {d}", "description": f"统计 {d} 体积"},
        pick(Q_SIZE, i).format(d=d))

for i, d in enumerate(["docs", "train", "_work", "plugins"]):
    add("ops_bash", {"command": f"find {d} -name '*.md' | wc -l", "description": f"数 {d} 下 md 个数"},
        pick(Q_FIND, i).format(d=d))

# 带错误前置状态 / 管道 / git / python 的追加条目
add("ops_bash", {"command": "git status --short", "description": "查看工作区改动"},
    "刚才提交失败了，先看下现在有哪些改动没提交")
add("ops_bash", {"command": "git log --oneline -5", "description": "看最近 5 条提交"},
    "最近五个提交都改了什么，列一下")
add("ops_bash", {"command": "git diff --stat HEAD", "description": "看本次改动统计"},
    "这次改动涉及哪些文件、各改了多少行")
add("ops_bash", {"command": "grep -c '<tool_call>' train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v3.jsonl",
                 "description": "数 v3 里的 tool_call 条数"},
    "v3 数据里一共嵌了多少个 tool_call")
add("ops_bash", {"command": "python -c \"import json;print(len(open('_work/rebuild/kitty-adapt/manifest.json',encoding='utf-8').read()))\"",
                 "description": "算 manifest 字符数"},
    "manifest.json 一共有多少个字符")
add("ops_bash", {"command": "find . -name '*.jsonl' -size +1M -printf '%s %p\\n' | sort -rn | head -5",
                 "description": "找 1MB 以上的 jsonl"},
    "仓库里超过 1MB 的 jsonl 前五个是哪几个")
add("ops_bash", {"command": "ls -t train/lines/9b-oxcoder/out | head -5", "description": "看最近产出"},
    "训练产物目录里最新的五个文件")
add("ops_bash", {"command": "tail -n 3 _work/session-audit/ninfer-stats.jsonl", "description": "看最近三条统计"},
    "每请求统计的最后三条给我看下")
add("ops_bash", {"command": "nvidia-smi --query-gpu=memory.used,memory.total --format=csv",
                 "description": "查显存占用"},
    "现在显卡显存占了多少")
add("ops_bash", {"command": "curl -s http://127.0.0.1:8080/v1/models", "description": "探本地引擎模型接口"},
    "8080 那个本地引擎活着没，看下模型列表")
add("ops_bash", {"command": "ps -W | grep -i python | head", "description": "看 python 进程"},
    "现在跑着几个 python 进程")
add("ops_bash", {"command": "ls -S logs | head -3", "description": "logs 里最大的三个"},
    "logs 目录最大的三个文件是哪几个")
add("ops_bash", {"command": "wc -l logs/*.log | tail -1", "description": "统计日志总行数"},
    "logs 下所有 log 加起来多少行")
add("ops_bash", {"command": "python -m json.tool _work/rebuild/kitty-adapt/manifest.json > /dev/null && echo OK",
                 "description": "校验 manifest JSON"},
    "manifest.json 格式有没有坏，校验一下")
add("ops_bash", {"command": "ls _work/rebuild/tool-opt", "description": "看 tool-opt 产物目录"},
    "tool-opt 目录下现在有哪些脚本")

# ---------------------------------------------------------------- ops_glob (45)
GP = [
    ("**/*.md", "docs"), ("**/*.py", "."), ("**/*.json", "_work"), ("**/*.jsonl", "train"),
    ("**/*.gguf", "models"), ("**/*.bat", "engines"), ("**/*.ts", "plugins"),
    ("**/*.log", "logs"), ("*rebuild*", "_work"), ("**/*.sh", "train"),
    ("**/*.txt", "."), ("**/*.ps1", "_work"), ("**/*.md", "train"), ("**/*.py", "_work"),
    ("**/*.jsonl", "train/lines/9b-oxcoder/data"), ("**/*.md", "plugins"),
    ("**/adapter.ts", "."), ("**/index.js", "plugins"), ("**/manifest.json", "."),
    ("**/*.gguf", "."), ("**/*.md", "."), ("**/*.py", "train"),
    ("**/*.jsonl", "_work"), ("**/*.bat", "."), ("**/*.md", "_work"),
    ("**/*.json", "train"), ("**/*.ts", "."), ("**/*.ps1", "."),
    ("**/*.sh", "."), ("**/*.txt", "docs"), ("**/*.log", "."),
    ("*.py", "_work/rebuild/tool-opt"), ("*.jsonl", "train/lines/9b-oxcoder/data/kitty-reverse/opt"),
    ("**/*.jsonl", "train/lines/9b-oxcoder/data/dsh-adapt"), ("**/*.md", "train/lines"),
    ("**/*.py", "plugins"), ("**/*.js", "plugins"), ("**/*.json", "plugins"),
    ("**/*.gguf", "engines"), ("**/*.bat", "train"), ("**/*.txt", "train"),
    ("**/*.log", "_work"), ("**/*.jsonl", "logs"), ("**/*.md", "engines"),
]
QL = ["把 {p} 下所有 {g} 列出来", "{p} 里的 {g} 都有哪些", "找 {p} 下的 {g}",
      "列一下 {p} 下的 {g} 清单", "{p} 下的 {g} 给我列出来", "帮我找 {p} 里的 {g}",
      "{p} 里有哪些 {g}"]
for i, (pat, path) in enumerate(GP):
    add("ops_glob", {"pattern": pat, "path": path},
        pick(QL, i).format(p=path, g=pat.replace("**/", "").replace("*", "")))

# ---------------------------------------------------------------- ops_grep (50)
TOK = ["nsfwGate", "offloadToolResultMaxChars", "toolAllowlist", "DBG_ATTACH", "P_WALK",
       "SYNC_STAT", "MODENUM", "kitty_dualview", "reverse_add_intent", "infer-stats",
       "sparse attention", "0x7FF6A0000000", "P_BACK", "S_NEW", "KM_ATTACH",
       "draftTokens", "maxContext", "deviceKV", "kv_capacity", "prefillChunk",
       "ops_grep", "ops_glob", "kitty_settings", "kitty_trail", "kitty_patch",
       "think9", "is_playing", "sessionGoal", "target-set", "confirm=true",
       "EXPECT", "rollback", "dump.bin", "unmap", "fix_iat", "expect"]
PATHS = [".", "docs", "train", "plugins", "plugins/dsh-local-ai",
         "_work", "_work/rebuild", "train/lines/9b-oxcoder/data", "logs", "engines"]
QG = ["搜一下 {t} 在 {p} 里哪儿出现过", "grep 一下 {t}", "{p} 里搜 {t}",
      "找 {t} 的所有命中", "{p} 下有哪些文件写了 {t}", "查一下 {t} 的引用位置",
      "{t} 在仓库里还出现吗"]
INC = ["*.md", "*.py", "*.jsonl", "*.ts", "*.json"]
for i in range(50):
    tok = TOK[i % len(TOK)]
    path = PATHS[i % len(PATHS)]
    args = {"pattern": tok, "path": path}
    if i % 4 == 3:
        args["include"] = INC[(i // 4) % len(INC)]
    add("ops_grep", args, pick(QG, i).format(t=tok, p=path))

# ---------------------------------------------------------------- read (50)
RF = FILES + ["README.md", "AGENTS.md", "CLAUDE.md", "docs/architecture.md", "docs/plans.md",
              "docs/training.md", "docs/operations.md", "docs/v6-rebuild.md",
              "train/EVAL-PROTOCOL.md", "train/PITFALLS.md", "train/PREFLIGHT.md",
              "train/lines/README.md", "train/lines/9b-oxcoder/README.md",
              "engines/switch-model.py", "engines/llama-cpp/serve.bat",
              "train/lines/9b-oxcoder/data/eval/MANIFEST.json"]
QR = ["看 {f} 第 {o} 行往后 {l} 行", "{f} 从第 {o} 行起读 {l} 行", "读 {f} 的 {o}-{e} 行",
      "{f} 第 {o} 行开始给我 {l} 行", "把 {f} 第 {o} 行往后 {l} 行拿出来",
      "只看 {f} 的 {o} 到 {e} 行"]
for i in range(50):
    f = RF[i % len(RF)]
    off = 1 + (i * 7) % 120
    lim = 20 + (i * 3) % 60
    add("read", {"file_path": f, "offset": off, "limit": lim},
        pick(QR, i).format(f=f.rsplit("/", 1)[-1], o=off, l=lim, e=off + lim - 1))

# ---------------------------------------------------------------- write (50)
WQ = ["新建 {f}，写三行说明", "把 {f} 生成出来", "建个 {f} 放这轮结论",
      "{f} 不存在，创建并写入摘要", "落一个 {f}", "写到 {f} 里，内容就一句话"]
WDIRS = ["_work/rebuild/tool-opt", "docs", "_work/rebuild", "train/logs", "_work"]
for i in range(50):
    d = WDIRS[i % len(WDIRS)]
    fn = f"tool-opt-note-{i:02d}.md"
    f = f"{d}/{fn}"
    content = (f"# 记录 {i:02d}\n- 目标：工具调用数据校正\n- 轮次：r{i}\n- 结论：样本 {i * 7 % 97} 条\n")
    add("write", {"file_path": f, "content": content}, pick(WQ, i).format(f=fn))

# ---------------------------------------------------------------- edit (50)
EDITS = [
    ("1200", "1600"), ("8080", "8081"), ("think3", "think4"), ("四阶段", "五阶段"),
    ("三条硬约束", "四条硬约束"), ("12 个", "13 个"), ("maxSig >= 6", "maxSig >= 7"),
    ("v3", "v4"), ("prefillChunk=1024", "prefillChunk=2048"), ("draftTokens=3", "draftTokens=4"),
    ("maxContext", "max_context"), ("kv_capacity", "kvCapacity"), ("true", "false"),
    ("top_k", "topK"), ("0.7", "0.8"), ("8192", "16384"), ("f16", "q8_0"),
    ("q4_0", "q5_1"), ("ngl", "n_gpu_layers"), ("batch", "n_batch"),
    ("ubatch", "n_ubatch"), ("flash_attn", "flashAttn"), ("temp", "temperature"),
    ("repeat_penalty", "repetition_penalty"), ("stop", "stop_sequences"),
]
EF = ["README.md", "CLAUDE.md", "docs/architecture.md", "docs/plans.md", "docs/training.md",
      "docs/operations.md", "train/EVAL-PROTOCOL.md", "train/PITFALLS.md", "train/PREFLIGHT.md",
      "plugins/dsh-local-ai/PATCHES.md"]
QE = ["把 {f} 里的 {a} 改成 {b}", "{f} 里 {a} 换成 {b}", "改一下 {f}：{a} -> {b}",
      "{f} 中的 {a} 全部替换成 {b}", "把 {f} 的 {a} 修正为 {b}", "{f} 里搜 {a} 然后改成 {b}"]
for i in range(50):
    a, b = EDITS[i % len(EDITS)]
    f = EF[(i * 3) % len(EF)]
    args = {"file_path": f, "old_string": a, "new_string": b}
    if i % 5 == 4:
        args["replace_all"] = True
    add("edit", args, pick(QE, i).format(f=f.rsplit("/", 1)[-1], a=a, b=b))

# ---------------------------------------------------------------- kitty_settings (55)
GOALS = ["定位血量指针链", "ACE 三视图门禁一轮", "反编译 kitty-target.exe 看函数",
         "追 CreateFileW 到 WriteFile 的调用链", "dump 主模块并重建镜像",
         "把 kitty-target.exe 的静态面跑一遍", "校验 ops_grep 参数契约",
         "对 0x7FF6A0000000 做三视图对账", "一轮夜跑回归", "补丁回滚验证",
         "会话目标：先把工具路由修对", "目标：把 P_BACK 命中缩到 50 以内"]
QSET = ["锁定目标并写会话目标", "把目标和会话目标落一下", "这个会话就干 {g}，目标进程 kitty-target.exe",
        "锁 kitty-target.exe，会话目标写：{g}", "开始干活，目标 {g}", "落双字段：target=kitty-target.exe，goal={g}"]
for i, g in enumerate(GOALS):
    add("kitty_settings", {"action": "target-set", "target": "kitty-target.exe", "sessionGoal": g},
        pick(QSET, i).format(g=g))
add("kitty_settings", {"action": "target-get"}, "现在锁的是哪个目标，会话目标是什么")
add("kitty_settings", {"action": "target-get", "top": 5}, "把目标字段和最近五条 trail 一起看下")
add("kitty_settings", {"action": "mode-get"}, "当前是任务态还是待命态")
add("kitty_settings", {"action": "mode-set", "mode": "standby"}, "先待命，别开跑")
add("kitty_settings", {"action": "mode-set", "mode": "task"}, "恢复任务态")
add("kitty_settings", {"action": "trail-get", "top": 20}, "这两步的轨迹调出来看")
add("kitty_settings", {"action": "trail-get", "top": 50}, "按会话拉 50 条轨迹")
add("kitty_settings", {"action": "trail-get", "target": "kitty-target.exe", "top": 10},
    "只看 kitty-target.exe 最近十条")
add("kitty_settings", {"action": "root-get"}, "工作台根目录现在指哪")
add("kitty_settings", {"action": "host-rebind", "keepLock": True}, "换宿主，目标锁别动")
add("kitty_settings", {"action": "host-rebind"}, "宿主和状态一起重绑")
add("kitty_settings", {"action": "task-open", "target": "kitty-target.exe", "sessionGoal": "定位血量指针链"},
    "开个任务：定位血量指针链")
add("kitty_settings", {"action": "task-get"}, "这轮任务现在什么状态")
add("kitty_settings", {"action": "task-close"}, "这一轮收口，关任务")
add("kitty_settings", {"action": "task-inherit", "from": "session-cbab1a96"}, "继承上个会话的任务")
add("kitty_settings", {"action": "task-new", "target": "kitty-target.exe"}, "开新任务，目标 kitty-target.exe")
add("kitty_settings", {"action": "reverse-init", "confirm": "no"}, "先回显逆向初始化计划，别写盘")
add("kitty_settings", {"action": "reverse-init", "confirm": "yes"}, "逆向初始化，直接落盘")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "stage-start", "stage": "定位"}, ensure_ascii=False)},
    "进定位阶段")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "stage-complete", "stage": "静态",
                                                     "evidence": ["strings 命中 3 条"]}, ensure_ascii=False)},
    "静态阶段做完了，带证据")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "stage-fail", "stage": "对抗"}, ensure_ascii=False)},
    "对抗阶段失败了，记一下")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "retry-stage", "stage": "定位"}, ensure_ascii=False)},
    "定位重试一次")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "block", "stage": "还原",
                                                     "question": "要不要重启宿主"}, ensure_ascii=False)},
    "卡住了：还原阶段需要人决定要不要重启宿主")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "answer", "questionId": "q1",
                                                     "answer": "重启"}, ensure_ascii=False)},
    "问题 q1 回答：重启")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "complete",
                                                     "evidence": ["三视图 3/3 一致", "补丁回滚通过"]},
                                                    ensure_ascii=False)},
    "全部完成，交两条证据")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "finish",
                                                     "evidence": ["报告已落盘"]}, ensure_ascii=False)},
    "收口 finish，证据是报告已落盘")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "abandon", "reason": "靶标被换掉"},
                                                    ensure_ascii=False)},
    "这轮放弃，原因是靶标被换掉")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "set-consent", "consent": "yes"}, ensure_ascii=False)},
    "授权位设成同意")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "enter-standby"}, ensure_ascii=False)},
    "迁移到待命态")
add("kitty_settings", {"action": "task-dispatch",
                       "taskTransition": json.dumps({"type": "enter-task", "sessionGoal": "ACE 门禁",
                                                     "targetProcess": "kitty-target.exe",
                                                     "targetKind": "exe"}, ensure_ascii=False)},
    "进任务态：会话目标 ACE 门禁，目标进程 kitty-target.exe")
for i, g in enumerate(["零样本路由校正", "近邻工具判别", "下采样后再跑一次", "验收 10 题"]):
    add("kitty_settings", {"action": "target-set", "target": "kitty-target.exe",
                           "sessionGoal": g, "shape": "exe"}, f"锁 exe 形态，会话目标：{g}")
add("kitty_settings", {"action": "target-set", "target": "kitty-target.exe",
                       "sessionGoal": "UE 引擎模块还原", "engine": "ue"}, "引擎给 ue，目标还是 kitty-target.exe")

# ---------------------------------------------------------------- emit
def sig(tool, args):
    return tool + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    seen, dups = {}, []
    for r in ROWS:
        s = sig(r["tool"], r["args"])
        seen[s] = seen.get(s, 0) + 1
        if seen[s] > 1:
            dups.append((r["tool"], r["user"]))
    assert not dups, f"重复答案: {dups[:5]}"

    rows = []
    for r in ROWS:
        body = json.dumps({"name": r["tool"], "arguments": r["args"]},
                          ensure_ascii=False, separators=(",", ":"))
        rows.append({"messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": r["user"]},
            {"role": "assistant", "content": f"<tool_call>{body}</tool_call>"},
        ]})
    random.Random(SEED).shuffle(rows)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    t = Counter(r["tool"] for r in ROWS)
    uniq = len({sig(r["tool"], r["args"]) for r in ROWS}) / len(ROWS)
    print(f"OK {OUT}  lines={len(ROWS)}  unique_answer_rate={uniq:.3f}")
    for k, v in t.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

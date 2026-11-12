#!/usr/bin/env python
"""
build_val_test.py — 额外生成验证集 / 测试集（不动任何训练集数据）

原则
  · 训练集（kitty core 5602 / traj 2263 / nsfw 13668）一个字节都不改
  · val/test 全部"额外生成"：
      - 轨迹：从 Nemotron 未用过的 offset 拉（train 用 0-1500 与 2000-2500）
      - NSFW：从结构化词表 v9 生成释义/用法题（词条与 train 的 glossary 不重复）
      - 中文逆向探针：手工写，train 里没有
  · 生成后做重叠校验：val/test 的 user 文本与 train 全量比对，必须 0 命中

产出
  train/lines/9b-oxcoder/data/eval/val/*.jsonl
  train/lines/9b-oxcoder/data/eval/test/*.jsonl
  train/lines/9b-oxcoder/data/eval/MANIFEST.json
"""
from __future__ import annotations
import argparse, json, os, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "train" / "data"
EVAL = DATA / "eval"

NEMOTRON = "nvidia/Nemotron-SWE-v1"
TRAIN_OFFSETS = {0, 1500, 2000, 2500}       # 训练已用区间起点（禁止重叠）


# ───────────────────────── 中文逆向探针（手写） ─────────────────────────

PROBES = [
    # (问, 期望关键词[], 归类)
    ("KM_R 和 R 读同一个地址，值不一样。哪个是对的？", ["dualview", "分叉", "视图"], "re-judge"),
    ("S_NEW 扫描报错说区间太大，怎么改？", ["MODENUM", "窗口", "分段"], "re-tool"),
    ("注入 DLL 后回包 OK 但 MODENUM 里看不到模块，先查什么？", ["位数", "DllMain", "MODENUM"], "re-debug"),
    ("要读 0x7FF6A0000000 开始的 8 字节，用哪条指令？", ["R|", "qword", "kitty_ce"], "re-tool"),
    ("ASLR 开着，每次重启基址都变。写脚本怎么办？", ["MODBASE", "运行时", "不硬编码"], "re-design"),
    ("kitty_patch 的 expect 是干什么的？", ["校验", "原字节", "防错位"], "re-tool"),
    ("宿主 PING 通了但 LP 超时，说明什么？", ["通道", "宿主", "分层"], "re-debug"),
    ("想找血量地址，只知道当前值 100。步骤？", ["S_NEW", "S_CHANGED", "快照"], "re-tool"),
    ("P_BACK 命中超过 200 条怎么办？", ["缩小窗口", "模块窗口", "过滤"], "re-tool"),
    ("MODENUM 里某个模块 size=0，还能取窗口吗？", ["镜像头", "pchain", "兜底"], "re-debug"),
    ("反作弊把 R 和 KM_R 分叉了，怎么确认？", ["三视图", "KM_PR", "物理"], "re-judge"),
    ("要 dump 一个模块的完整镜像，用哪个工具？", ["kitty_dump", "module", "unmap"], "re-tool"),
    ("x64dbg 下断在 CreateFileW，怎么把路径存下来？", ["seed", "savedata", "rcx"], "re-tool"),
    ("Frida spawn 和 attach 的区别？什么时候用 spawn？", ["启动就 hook", "spawn", "暂停"], "re-judge"),
    ("IDA 批量导出函数列表和字符串，一条命令怎么做？", ["kitty_ida", "analyze", "functions"], "re-tool"),
    ("想确认一个 DLL 的对外入口，看哪里？", ["exports", "DllRegisterServer", "kitty_sym"], "re-tool"),
    ("Unity Mono 游戏想运行时看对象，用什么？", ["uexplorer", "Mono", "注入"], "re-tool"),
    ("IL2CPP 的 Unity 游戏，和 Mono 的分析路径差在哪？", ["dump.cs", "il2cppdumper", "无 dll"], "re-judge"),
    ("补丁写完要回滚，命令是什么？", ["rollback", "bak", "kitty_patch"], "re-tool"),
    ("怎么确认一份 PE 有没有加壳，但不看节表？", ["熵", "导入表", "入口点"], "re-judge"),
    ("弯针要写一段汇编变成机器码，用哪个工具？", ["kitty_asm", "assemble", "jump"], "re-tool"),
    ("要把跳转改成永远跳，字节怎么写？", ["EB", "E9", "jmp"], "re-tool"),
    ("内核面读物理内存，VA→PA 之后用什么？", ["KM_PA", "pread", "pwrite 拒绝"], "re-tool"),
    ("PVM 保护和写保护，哪个能绕？", ["wpb", "PTE", "accept_protection_bypass"], "re-judge"),
    ("夜跑一轮看哪些指标？", ["loop_status", "红线", "特征库"], "re-tool"),
    ("一键反作弊对抗，怎么判断有没有拦截面？", ["acescan", "gate", "写回"], "re-tool"),
    ("页面保护改成 RWX，用哪条？", ["kitty_prot", "rwx", "confirm"], "re-tool"),
    ("目标进程有多个同名实例，OPEN 怎么指定？", ["pid", "LP", "OPEN|"], "re-tool"),
    ("读到的值是 0，但我知道它不该是 0。查什么顺序？", ["基址", "映射", "CUR"], "re-debug"),
    ("扫描结果要不要 FREE？不 FREE 会怎样？", ["S_FREE", "驻留", "内存"], "re-tool"),
    ("怎么确认当前 OPEN 的是不是我想要的那个进程？", ["CUR", "pid", "校验"], "re-tool"),
    ("一句话说清 kitty 三视图门禁是干什么的？", ["R", "KM_R", "一致"], "re-judge"),
    ("模块基址读到 0x00400000，是 32 位还是 64 位？", ["32 位", "映像基址", "判据"], "re-judge"),
    ("要抓某个 app 的 http 流量，三步是什么？", ["status", "capture", "decode"], "re-tool"),
    ("x64dbg 脚本里下断、跑、存参、再跑，怎么写？", ["program", "steps", "savedata"], "re-tool"),
    ("宿主挂了怎么看、怎么自愈？", ["status", "drv host", "PING"], "re-debug"),
    ("怎么确认一个地址是模块内的，不是堆上的？", ["MODENUM", "窗口", "区间"], "re-judge"),
    ("补丁前后怎么证明文件真的变了？", ["hash", "kitty_patch", "校验和"], "re-tool"),
    ("同类工具里，为什么用 km 读而不是用户态读？", ["绕过", "保护", "物理"], "re-judge"),
    ("把一份 1.2 GB 的模块 dump 出来，要注意什么？", ["分块", "路径 ASCII", "超时"], "re-tool"),
]

NSFW_TPL = [
    ("在 NSFW 小说写作中，「{w}」是什么意思？请给出释义和用法示例。",
     "【类别】", "nsfw-glossary"),
]


# ───────────────────────── 生成逻辑 ─────────────────────────

def render_traj(msgs):
    out = []
    for m in msgs:
        r = m.get("role")
        if r == "assistant":
            parts = []
            if (m.get("content") or "").strip():
                parts.append(m["content"].strip())
            for c in (m.get("tool_calls") or []):
                fn = c.get("function") or {}
                a = fn.get("arguments")
                if isinstance(a, (dict, list)):
                    a = json.dumps(a, ensure_ascii=False)
                parts.append(f"[CALL {fn.get('name','tool')}] {a or ''}")
            if parts:
                out.append("【assistant】" + "\n".join(parts))
        elif r == "tool":
            if (m.get("content") or "").strip():
                out.append("【observation】" + m["content"].strip())
    return "\n\n".join(out)


def clip(text, tok, budget, head_ratio=0.72):
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) <= budget:
        return text, False
    h = int(budget * head_ratio)
    t = budget - h
    return (tok.decode(ids[:h], skip_special_tokens=True) + "\n\n……（中段省略）……\n\n"
            + tok.decode(ids[-t:], skip_special_tokens=True)), True


def make_traj(split, offset, limit, target_ctx, tok):
    from datasets import load_dataset
    ds = load_dataset(NEMOTRON, split="r2e_gym", streaming=True)
    import itertools
    rows = []
    for rec in itertools.islice(ds, offset, offset + limit):
        msgs = rec.get("messages") or []
        body = [m for m in msgs if m.get("role") != "system"]
        u = next((m for m in body if m.get("role") == "user"), None)
        if not u:
            continue
        sys_t = msgs[0]["content"] if msgs and msgs[0].get("role") == "system" else ""
        traj = render_traj(body[body.index(u) + 1:])
        if not traj.strip():
            continue
        used = len(tok.encode(sys_t + u["content"], add_special_tokens=False))
        if used >= target_ctx - 512:
            continue
        traj2, cut = clip(traj, tok, target_ctx - used)
        rows.append({
            "messages": [
                {"role": "system", "content": sys_t},
                {"role": "user", "content": u["content"]},
                {"role": "assistant", "content": traj2},
            ],
            "meta": {"split": split, "domain": "swe_traj_en", "src": NEMOTRON,
                     "repo": rec.get("repo"), "uuid": rec.get("uuid"),
                     "ctx_len": used + len(tok.encode(traj2, add_special_tokens=False)),
                     "truncated": cut},
        })
    return rows


def make_nsfw(split, words, lexicon):
    rows = []
    terms = {}
    for cat, v in lexicon.get("categories", {}).items():
        for w, info in (v.get("terms") or {}).items():
            terms[w] = info
    for w in words:
        info = terms.get(w)
        if not info:
            continue
        g = info.get("glossary") or {}
        meaning = g.get("meaning") or info.get("meaning") or ""
        ex = (g.get("examples") or info.get("context_examples") or [])
        ex = [e for e in ex if isinstance(e, str)][:2]
        asst = f"【类别】{g.get('cat') or '—'}\n【释义】{meaning}\n【同义/近义】{g.get('synonym') or info.get('synonym') or ''}\n"
        asst += f"【语料频率】{g.get('freq_text') or ('出现 ' + str(info.get('freq', 0)) + ' 次')}\n"
        asst += f"【写作提示】{g.get('writing_tip') or info.get('writing_tip') or ''}\n"
        for i, e in enumerate(ex, 1):
            asst += f"【例句{i}】{e}\n"
        rows.append({
            "messages": [
                {"role": "user", "content": f"在 NSFW 小说写作中，「{w}」是什么意思？请给出释义和用法示例。"},
                {"role": "assistant", "content": asst.strip()},
            ],
            "meta": {"split": split, "domain": "nsfw", "src": "nsfw-lexicon-v9", "term": w,
                     "cat": g.get("cat") or None},
        })
    return rows


def make_probes(split, probes):
    rows = []
    for q, kw, kind in probes:
        rows.append({
            "messages": [
                {"role": "system", "content": "你是 kitty 逆向工作台的执行层，直接调用工具完成任务。"},
                {"role": "user", "content": q},
                {"role": "assistant", "content": "PLACEHOLDER"},     # 只用于评分，不给参考答案
            ],
            "meta": {"split": split, "domain": "re-probe-zh", "kind": kind,
                     "expect_keywords": kw, "ref": "PLACEHOLDER"},
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tok", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    ap.add_argument("--traj-ctx", type=int, default=4096)
    ap.add_argument("--val-traj", type=int, default=300)
    ap.add_argument("--test-traj", type=int, default=300)
    a = ap.parse_args()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tok, trust_remote_code=True)
    lex = json.loads((DATA / "nsfw" / "nsfw-lexicon-v9.json").read_text(encoding="utf-8"))

    # 词表切分：val/test 各取互不重叠的 10%（且排除 train glossary 已用的 283 词）
    train_gloss = {json.loads(l)["messages"][0]["content"].split("「")[1].split("」")[0]
                   for l in (DATA / "nsfw" / "nsfw-glossary-merged.jsonl").read_text(encoding="utf-8").split("\n") if l.strip()}
    all_terms = sorted({w for v in lex["categories"].values() for w in (v.get("terms") or {})})
    pool = [w for w in all_terms if w not in train_gloss]
    random.seed(20261027)
    random.shuffle(pool)
    val_words = pool[:60]
    test_words = pool[60:120]

    probes_val = PROBES[:20]
    probes_test = PROBES[20:40]

    for split, offset, n, words, probes in (
        ("val", 3000, a.val_traj, val_words, probes_val),
        ("test", 4000, a.test_traj, test_words, probes_test),
    ):
        d = EVAL / split
        d.mkdir(parents=True, exist_ok=True)
        traj = make_traj(split, offset, n, a.traj_ctx, tok)
        (d / "traj.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in traj), encoding="utf-8")
        nsfw = make_nsfw(split, words, lex)
        (d / "nsfw.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in nsfw), encoding="utf-8")
        pr = make_probes(split, probes)
        (d / "probe-re-zh.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in pr), encoding="utf-8")
        print(f"[{split}] traj={len(traj)} nsfw={len(nsfw)} probe={len(pr)}", file=sys.stderr)

    # ── 重叠校验：val/test 的 user 文本 vs train 全量 ──
    def users(paths):
        s = set()
        for p in paths:
            for l in Path(p).read_text(encoding="utf-8").split("\n"):
                if not l.strip():
                    continue
                o = json.loads(l)
                u = next((m["content"] for m in o.get("messages", []) if m.get("role") == "user"), None)
                if u:
                    s.add(u.strip())
        return s

    train_users = users([
        DATA / "kitty-reverse" / "train-kitty-core.jsonl",
        DATA / "nsfw" / "train-cont.jsonl", DATA / "nsfw" / "train-scene.jsonl",
        DATA / "nsfw" / "train-multi.jsonl", DATA / "nsfw" / "train-style.jsonl",
        DATA / "nsfw" / "train-expand.jsonl",
        DATA / "agent-traj" / "nemotron-swe" / "swe-8k.jsonl",
        DATA / "agent-traj" / "nemotron-swe" / "swe-16k.jsonl",
        DATA / "agent-traj" / "swe-rebench" / "rebench-8k.jsonl",
        DATA / "agent-traj" / "deepswe" / "deepswe-8k.jsonl",
    ])
    rep = {}
    for split in ("val", "test"):
        eu = users([EVAL / split / f for f in ("traj.jsonl", "nsfw.jsonl", "probe-re-zh.jsonl")])
        rep[split] = {"eval_users": len(eu), "overlap_with_train": len(eu & train_users)}

    manifest = {
        "built": "2026-10-27",
        "principle": "val/test 全部额外生成，训练集零改动",
        "train_rows_untouched": {"kitty": 5602, "traj": 2263, "nsfw": 13668},
        "val": {"traj": "Nemotron offset 3000", "nsfw_terms": len(val_words), "probe": len(probes_val)},
        "test": {"traj": "Nemotron offset 4000", "nsfw_terms": len(test_words), "probe": len(probes_test)},
        "overlap_check": rep,
        "reproduce": "python train/lines/_shared/scripts/build_val_test.py",
    }
    (EVAL / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"overlap": rep, "manifest": str(EVAL / "MANIFEST.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""A. 近邻工具判别集生成器（只写工作区内，固定种子，可重跑）

产物: train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-neighbor.jsonl
每行: {"messages":[system(SYS), user(任务), assistant("<tool_call>{...}</tool_call>\\n判据：…")]}

七组易混工具对，每组 15-25 条，答案（工具名+扁平参数）组内唯一。
"""
import json
import hashlib
import random
from pathlib import Path

SEED = 20261121
random.seed(SEED)

SYS = ("你是石井，本地工作区执行层（SHIYI-WORKSPACE：自有资产 / 已授权靶标）。"
       "直接回答或直接做事：首行就是产物（正文/代码/结论），不写计划清单，"
       "不输出 [STAGE]/目标/交付物/判据，不用「当前：/结果：/下一步：」收口。")

ROOT = Path(__file__).resolve().parents[3]          # D:\BaiduNetdiskDownload\Local-AI
OUT = ROOT / "train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-neighbor.jsonl"

# 真实可复用值
KCE_FULL = r"D:\DrCE(26.2.16)\KittyDebugTool\SVIP-User\FULL-Version\KittyCE.exe"
DBG64_EXE = r"D:\DrCE(26.2.16)\KittyDebugTool\DBG\DBG64\醉梦DBG.exe"
LOADDLL = r"D:\DrCE(26.2.16)\KittyDebugTool\DBG\DBG64\loaddll.exe"
KLOADER = r"D:\DrCE(26.2.16)\KittyDebugTool\KittyLoader.exe"
BASE = 0x7FF6A0000000                                # 靶标模块基址（已实测）

R = []   # (group, user, tool, args, reason)


def add(group, user, tool, args, reason):
    R.append({"group": group, "user": user, "tool": tool, "args": args, "reason": reason})


# ---------------------------------------------------------------- G1 ops_grep
G = "g1_ops_grep_vs_kitty_find_vs_kitty_ce_FIND"
add(G, "搜一下 nsfwGate 在仓库哪里", "ops_grep",
    {"pattern": "nsfwGate", "path": "."},
    "仓库文本检索走 ops_grep；kitty_find 不存在，kitty_ce 的 FIND/S_NEW 是内存值扫描，不读文件。")
add(G, "grep 一下 offloadToolResultMaxChars 出现在哪几个文件", "ops_grep",
    {"pattern": "offloadToolResultMaxChars", "path": ".", "include": "*"},
    "内容检索用 ops_grep，pattern 必填、path 给搜索根；不要用 ops_bash 拼 grep，也不要造 kitty_find。")
add(G, "找 docs 里提到 kitty_dualview 的段落", "ops_grep",
    {"pattern": "kitty_dualview", "path": "docs", "include": "*.md"},
    "限定目录 + 文件类型就是 ops_grep 的 path/include 两个参数，不是 glob。")
add(G, "代码里哪里调用了 toolAllowlist", "ops_grep",
    {"pattern": "toolAllowlist", "path": "plugins/dsh-local-ai"},
    "插件源码里找调用点 = 文本检索 ops_grep；只看命中行，不做反汇编。")
add(G, "搜 DBG_ATTACH 在 kitty-toolbox src 里的用法", "ops_grep",
    {"pattern": "DBG_ATTACH", "path": r"D:\DrCE(26.2.16)\kitty-toolbox\src"},
    "外部只读目录也能搜；ops_grep 只读不写，不会破坏 DrCE 只读边界。")
add(G, "train 目录里搜 P_WALK 相关的说明", "ops_grep",
    {"pattern": "P_WALK", "path": "train"},
    "按目录批量文本搜索用 ops_grep；要逐文件通读才用 read。")
add(G, "找出所有 import torch 的 py 文件", "ops_grep",
    {"pattern": "import torch", "path": ".", "include": "*.py"},
    "include 卡扩展名，一次拿全部命中文件；ops_glob 只回路径不回内容。")
add(G, "仓库里搜一下 0x7FF6A0000000 这个地址有没有被写进文档", "ops_grep",
    {"pattern": "0x7FF6A0000000", "path": "."},
    "搜地址字面量仍是文本检索；要对这个地址取值才走 kitty_ce 的 R。")
add(G, "看 _work 下有没有写 SYNC_STAT", "ops_grep",
    {"pattern": "SYNC_STAT", "path": "_work"},
    "有/无判断也是 ops_grep（0 命中就是没有）；不要先 glob 再逐个 read。")
add(G, "在 kitty-target.exe 里搜 dword 100 的内存地址", "kitty_ce",
    {"op": "S_NEW|dword|100|0x7FF6A0000000|0x7FF6A0200000"},
    "内存值扫描是 kitty_ce 的 S_NEW（vt|val|start|stop 显式区间），跟文件文本搜索无关。")
add(G, "扫一下 4 字节 0x1234ABCD 在靶标模块里的命中", "kitty_ce",
    {"op": "S_NEW|dword|305441741|0x7FF6A0000000|0x7FF6A0200000"},
    "S_NEW 的 val 走十进制；十六进制要换算，kitty_ce 不接受 0x 在 val 位。")
add(G, "把刚才那次扫描结果取回来", "kitty_ce",
    {"op": "S_GET"},
    "扫描是 kitty_ce 的作业态：S_NEW 建、S_GET 取、S_FREE 释放，三步都在同一个工具体内。")
add(G, "用 kitty_find 搜一下 nsfwGate", "ops_grep",
    {"pattern": "nsfwGate", "path": "train"},
    "kitty_find 不存在（幻觉名）；文本搜索的实体是 ops_grep，直接纠正工具名再给参数。")
add(G, "kitty_find 这个工具怎么调，参数给什么", "ops_grep",
    {"pattern": "kitty_find", "path": "_work/rebuild/kitty-adapt/manifest.json"},
    "manifest 是工具清单真相源；查工具是否存在就 grep 清单，不要凭记忆编工具。")
add(G, "kitty-ce 里 FIND 那条 OP 跟 ops_grep 是一回事吗", "ops_grep",
    {"pattern": "FIND|S_NEW", "path": "_work/rebuild/kitty-adapt/manifest.json"},
    "两者不同面：ops_grep 搜磁盘文本，kitty_ce 的 FIND/S_NEW 搜进程内存值。")
add(G, "搜一下 sparse attention 在文档里的解释", "ops_grep",
    {"pattern": "sparse attention", "path": "docs", "include": "*.md"},
    "多词短语整体当 pattern；空格不需要转义，ops_grep 走正则。")
add(G, "定位 logs 里 ERR|TIMEOUT 的行", "ops_grep",
    {"pattern": "ERR|TIMEOUT", "path": "logs"},
    "正则或运算直接用 |；ops_grep 是 ripgrep 语义，不需要 esc。")
add(G, "看看 PATCHES.md 里有没有写 \"think9\"", "ops_grep",
    {"pattern": "think9", "path": "plugins/dsh-local-ai/PATCHES.md"},
    "path 可以直接给单个文件，比 read 全量读更省上下文。")
add(G, "全仓库搜 TODO 标记都有哪些", "ops_grep",
    {"pattern": "TODO", "path": ".", "limit": 200},
    "大范围命中用 limit 截断；ops_grep 支持 limit，别用 ops_bash 拼 grep -r。")
add(G, "在 agent-traj 数据里搜 reverse_add_intent", "ops_grep",
    {"pattern": "reverse_add_intent", "path": "train/lines/9b-oxcoder/data/agent-traj"},
    "数据集内检索同样是 ops_grep；数据文件多，不要逐个 read。")
add(G, "在进程内存里找 \"nsfwGate\" 这个 ASCII 串", "kitty_ce",
    {"op": "S_NEW|bytes|6e73667747617465|0x7FF6A0000000|0x7FF6A0200000"},
    "内存里找字符串是 bytes 扫描（十六进制），文件里找字符串才用 ops_grep。")
add(G, "核对 ops_grep 的 pattern 参数是不是必填", "ops_grep",
    {"pattern": "pattern", "path": "_work/rebuild/kitty-adapt/manifest.json"},
    "查参数契约就 grep 清单/文档；不要凭印象回答必填项。")

# ---------------------------------------------------------------- G2 ops_glob
G = "g2_ops_glob_vs_ops_bash_vs_kitty_static"
add(G, "列一下 docs 下所有 md 文件", "ops_glob",
    {"pattern": "**/*.md", "path": "docs"},
    "只要路径清单用 ops_glob（pattern+path）；不排序、不过滤内容。")
add(G, "train 里所有 jsonl 列出来", "ops_glob",
    {"pattern": "**/*.jsonl", "path": "train"},
    "按扩展名收文件清单 = ops_glob；行数统计才需要 ops_bash。")
add(G, "数一下 md 文件有几个", "ops_bash",
    {"command": "find docs -name '*.md' | wc -l", "description": "数 docs 下 md 文件个数"},
    "要计数就得走 shell 管道（find|wc），ops_glob 只回清单不回计数。")
add(G, "统计 train-dsh-v3.jsonl 有多少行", "ops_bash",
    {"command": "wc -l train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v3.jsonl",
     "description": "统计 v3 数据行数"},
    "行数/字节数这类聚合是 ops_bash 的活；read 只做区段读取。")
add(G, "看 logs 目录里最大的三个文件", "ops_bash",
    {"command": "ls -S logs | head -3", "description": "按大小列出 logs 前三"},
    "排序 + 截断是 shell 语义，ops_glob 不支持排序。")
add(G, "plugins 下所有 ts 文件按修改时间倒序列出", "ops_bash",
    {"command": "ls -t plugins/dsh-local-ai/src/*.ts", "description": "按时间倒序列 ts"},
    "时间/大小排序必须 ops_bash；ops_glob 命中的顺序不可控。")
add(G, "找 _work 下名字带 rebuild 的目录", "ops_glob",
    {"pattern": "*rebuild*", "path": "_work"},
    "只做名字匹配的查找用 ops_glob 的 pattern；不需要 shell。")
add(G, "models 下的 gguf 都有哪些", "ops_glob",
    {"pattern": "**/*.gguf", "path": "models"},
    "只列模型文件路径 → ops_glob；看权重元信息才换 kitty_static。")
add(G, "kitty-reverse 目录下所有 opt 子目录的 jsonl", "ops_glob",
    {"pattern": "opt/**/*.jsonl", "path": "train/lines/9b-oxcoder/data/kitty-reverse"},
    "嵌套层用 **，根用 path；一次拿全，不用逐层 ls。")
add(G, "看 loaddll.exe 的静态面：先出 PE 头", "kitty_static",
    {"action": "pe", "path": LOADDLL},
    "看 PE 头/节表/时间戳是 kitty_static 的 pe，不是 glob 也不是 read（二进制读不了）。")
add(G, "把 KittyCE.exe 里的字符串抓出来，过滤 LoadLibrary", "kitty_static",
    {"action": "strings", "path": KCE_FULL, "filter": "LoadLibrary", "limit": 80},
    "二进制取字符串是 kitty_static strings（自带 ASCII/UTF-16LE 双档），ops_grep 不读 PE。")
add(G, "醉梦DBG.exe 的节熵算一下，看有没有加壳", "kitty_static",
    {"action": "entropy", "path": DBG64_EXE},
    "熵/加壳判断属于静态文件面，kitty_static entropy 直接给逐节熵。")
add(G, "KittyLoader.exe 的签名证书信息", "kitty_static",
    {"action": "cert", "path": KLOADER},
    "证书目录解析是 kitty_static cert；不是 read，也不是 kitty_patch。")
add(G, "统计 loaddll.exe 有几个节、每节多大", "kitty_static",
    {"action": "pe", "path": LOADDLL, "limit": 40},
    "节表就是 PE 头的一部分，kitty_static pe 一次给全；limit 控输出条数。")
add(G, "找一个叫 adapter.ts 的文件在哪", "ops_glob",
    {"pattern": "**/adapter.ts", "path": "."},
    "按文件名跨目录找 → ops_glob；找到后再 read 看内容。")
add(G, "列出 _work/rebuild/tool-opt 下所有 py 脚本", "ops_glob",
    {"pattern": "*.py", "path": "_work/rebuild/tool-opt"},
    "单层目录用 *.py 即可，不必 **；path 指向确切目录。")
add(G, "看下 docs 里 md 的总字节数", "ops_bash",
    {"command": "du -ch docs/*.md | tail -1", "description": "统计 docs 下 md 总字节"},
    "体积聚合走 ops_bash；glob 不返回大小。")
add(G, "把整个仓库的文件树前两层打出来", "ops_bash",
    {"command": "find . -maxdepth 2 -type d | sort", "description": "输出两层目录树"},
    "目录树是 shell 组合命令，ops_glob 只能按 pattern 拿文件。")
add(G, "kitty-adapt 目录下 manifest.json 在哪，给我路径", "ops_glob",
    {"pattern": "manifest.json", "path": "_work/rebuild/kitty-adapt"},
    "只要文件路径用 ops_glob；要看里面的工具名得再 read / ops_grep。")
add(G, "把 volume 修正：找出所有 4GB 以上的文件", "ops_bash",
    {"command": "find . -type f -size +4G -printf '%s %p\\n' | sort -rn | head",
     "description": "找 4GB 以上大文件"},
    "按大小筛选是 shell 表达式，任何内部工具都没有 size 谓词。")

# ---------------------------------------------------------------- G3 edit/write/read
G = "g3_edit_vs_write_vs_read"
add(G, "把 AGENTS.md 里的 foo 改成 bar", "edit",
    {"file_path": "AGENTS.md", "old_string": "foo", "new_string": "bar"},
    "局部替换用 edit（old_string 必须唯一命中），不要整文件重写。")
add(G, "把 docs/plans.md 里的「四阶段」改成「五阶段」", "edit",
    {"file_path": "docs/plans.md", "old_string": "四阶段", "new_string": "五阶段"},
    "中文串替换也是 edit；replace_all 默认 false，先保证唯一命中。")
add(G, "README.md 里 1200 这个数字改成 1600", "edit",
    {"file_path": "README.md", "old_string": "1200", "new_string": "1600"},
    "单点数值修正用 edit；先把上下文带进 old_string 才不会被多处命中拦住。")
add(G, "PATCHES.md 里的 think3 全部换成 think4", "edit",
    {"file_path": "plugins/dsh-local-ai/PATCHES.md", "old_string": "think3",
     "new_string": "think4", "replace_all": True},
    "多处替换要显式 replace_all=true；否则 edit 会因多匹配拒绝执行。")
add(G, "serve.bat 里 8080 端口改成 8081", "edit",
    {"file_path": "engines/llama-cpp/serve.bat", "old_string": "--port 8080",
     "new_string": "--port 8081"},
    "带参数的串要连参数名一起写进 old_string，避免命中注释里同样的数字。")
add(G, "把 CLAUDE.md 的「三条硬约束」标题改成「四条硬约束」", "edit",
    {"file_path": "CLAUDE.md", "old_string": "三条硬约束", "new_string": "四条硬约束"},
    "标题级小改也是 edit；不需要 read 全文再 write。")
add(G, "adapter.ts 里把 maxSig 改成 7", "edit",
    {"file_path": "plugins/dsh-local-ai/src/adapter.ts", "old_string": "maxSig >= 6",
     "new_string": "maxSig >= 7"},
    "改判定条件要带上比较符，避免和文档里的数字撞。")
add(G, "新建 _work/rebuild/tool-opt/notes.md，写三行说明", "write",
    {"file_path": "_work/rebuild/tool-opt/notes.md",
     "content": "# 备注\nA 近邻集 147 条\nB 同义集 355 条\n"},
    "文件不存在或要整篇定稿用 write；改已有文件的局部才用 edit。")
add(G, "把 _work/rebuild/tool-opt/notes.md 整体重写成一行", "write",
    {"file_path": "_work/rebuild/tool-opt/notes.md", "content": "近邻+同义数据集已生成\n"},
    "整体重写（覆盖语义）用 write；改局部用 edit。")
add(G, "生成一个空的 _work/rebuild/tool-opt/.gitkeep", "write",
    {"file_path": "_work/rebuild/tool-opt/.gitkeep", "content": ""},
    "建空文件也是 write（content 空串），不是 ops_bash touch。")
add(G, "看 adapter.ts 第 120 到 160 行", "read",
    {"file_path": "plugins/dsh-local-ai/src/adapter.ts", "offset": 120, "limit": 40},
    "定区段读用 read 的 offset/limit（1-based，limit 是行数）。")
add(G, "读 manifest.json 开头 30 行", "read",
    {"file_path": "_work/rebuild/kitty-adapt/manifest.json", "offset": 1, "limit": 30},
    "只读不写一律 read；大 JSON 别整篇读，用 offset/limit 切片。")
add(G, "看 train-dsh-v3.jsonl 第 240 行往后 8 行", "read",
    {"file_path": "train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v3.jsonl",
     "offset": 240, "limit": 8},
    "数据文件抽查样本用 read 切片；统计行数才用 ops_bash wc。")
add(G, "把 AGENTS.md 第 40 行那个错别字改掉", "edit",
    {"file_path": "AGENTS.md", "old_string": "执行前自检", "new_string": "执行前自检（必做）"},
    "知道行号也要用 edit 的串替换接口，read 只负责定位内容。")
add(G, "新建 docs/tool-routing.md 写路由说明", "write",
    {"file_path": "docs/tool-routing.md",
     "content": "# 工具路由\n\n文本搜索 → ops_grep\n路径清单 → ops_glob\n整篇文件 → read/write\n局部改动 → edit\n"},
    "新文件先 write 落盘；目录已存在，不需要额外建目录。")
add(G, "把 docs/architecture.md 的落盘阈值 1200 改成 2000", "edit",
    {"file_path": "docs/architecture.md", "old_string": ">1200 字符", "new_string": ">2000 字符"},
    "同一数字在多个文档出现，old_string 要带单位/上下文做唯一定位。")
add(G, "看看 engines/switch-model.py 头部 20 行", "read",
    {"file_path": "engines/switch-model.py", "offset": 1, "limit": 20},
    "确认脚本入口参数就 read 头部；改它才换 edit。")
add(G, "把 notes.md 里第二行删掉", "write",
    {"file_path": "_work/rebuild/tool-opt/notes.md", "content": "近邻+同义数据集已生成\nC 下采样已落盘\n"},
    "行删除没有专用工具，做法是 write 回写全文（内容小才行）。")
add(G, "把 PREFLIGHT.md 里的 python 改成 python3", "edit",
    {"file_path": "train/PREFLIGHT.md", "old_string": "python ", "new_string": "python3 "},
    "统一改命令名用 edit；注意尾随空格用来避免命中 python3 自身。")
add(G, "读 PITFALLS.md 第 66 条附近 15 行", "read",
    {"file_path": "train/PITFALLS.md", "offset": 300, "limit": 15},
    "按条定位后 read 切片；不要整篇读进上下文。")
add(G, "在 _work/rebuild/tool-opt/ 建一个 report.md 骨架", "write",
    {"file_path": "_work/rebuild/tool-opt/report.md",
     "content": "# 工具调用数据优化报告\n\n## A 近邻集\n## B 同义集\n## C 分布与下采样\n## D 验收题\n"},
    "骨架类新文件用 write 一次成文；后续补内容再用 edit 局部改。")
add(G, "把 README.md 的「12 个」改成「13 个」白名单数", "edit",
    {"file_path": "README.md", "old_string": "12 个：write/read/edit", "new_string": "13 个：write/read/edit"},
    "带上下文锚点的替换才能唯一定位；改前后保持结构不变。")
add(G, "把 ninfer-stats.jsonl 最后 3 条抽出来", "read",
    {"file_path": "_work/session-audit/ninfer-stats.jsonl", "offset": 1, "limit": 3},
    "只要样本用 read；要按字段聚合才上 ops_bash + python。")
add(G, "改 docstring：把 build_dsh_adapt_v3.py 顶部注释里的 v3 改成 v4", "edit",
    {"file_path": "_work/rebuild/build_dsh_adapt_v3.py", "old_string": "v3", "new_string": "v4",
     "replace_all": True},
    "同一 token 多处出现必须 replace_all=true，否则 edit 直接拒绝。")

# ---------------------------------------------------------------- G4 ida/ghidra/rea
G = "g4_kitty_ida_vs_kitty_ghidra_vs_kitty_rea_function"
add(G, "反编译 kitty-target.exe 看函数", "kitty_ida",
    {"action": "analyze", "target": r"D:\DrCE(26.2.16)\KittyDebugTool\DBG\DBG64\loaddll.exe"},
    "要整份 PE 的函数库/反编译产物走 kitty_ida analyze（一次建库，产物落盘可反复查）。")
add(G, "用 IDA 把 loaddll.exe 的函数列表拉出来，过滤 main", "kitty_ida",
    {"action": "functions", "target": r"D:\DrCE(26.2.16)\KittyDebugTool\DBG\DBG64\loaddll.exe",
     "filter": "main"},
    "functions/strings/xrefs/decompile 都是读 analyze 的产物，先建库再按名过滤。")
add(G, "IDA 里看下 sub_140001000 的反编译", "kitty_ida",
    {"action": "decompile", "target": r"D:\DrCE(26.2.16)\KittyDebugTool\DBG\DBG64\loaddll.exe",
     "name": "sub_140001000"},
    "已知函数名要 C 伪码 → kitty_ida decompile；这里不是 REA 的单函数档案。")
add(G, "看 KittyCE.exe 的导入表", "kitty_ida",
    {"action": "imports", "target": KCE_FULL},
    "导入表是 PE 结构化视图，kitty_ida imports 直接出；不需要跑 ghidra。")
add(G, "没装 IDA，用免费的反编译器把 KittyLoader.exe 跑一遍", "kitty_ghidra",
    {"action": "analyze", "target": KLOADER},
    "IDA 不可用/要免费档位就换 kitty_ghidra（analyzeHeadless 同一套四件套产物）。")
add(G, "ghidra 里搜 kitty 相关字符串", "kitty_ghidra",
    {"action": "strings", "target": KLOADER, "filter": "kitty"},
    "ghidra 侧读产物同样是 strings/functions/decompile，别混用 kitty_static（那是只读文件面）。")
add(G, "用 ghidra 反编译 Function_140012340 看逻辑", "kitty_ghidra",
    {"action": "decompile", "target": KLOADER, "name": "Function_140012340"},
    "目标函数已被 ghidra 建库时才用 ghidra decompile；命名风格是 Function_ 前缀。")
add(G, "REA 里取 CreateFileW 挂钩点的函数档案", "kitty_rea_function",
    {"procedure": "kernelbase.CreateFileW"},
    "已有符号/已分析索引的单函数取证 → kitty_rea_function(procedure)，不需要重新 analyze 整个 PE。")
add(G, "看一下 main 这个函数的伪代码和引用，走 REA", "kitty_rea_function",
    {"procedure": "main"},
    "单符号取证用 procedure 直取；要全量函数表才上 kitty_ida analyze。")
add(G, "REA 分析 sub_140005A20 这个函数", "kitty_rea_function",
    {"procedure": "sub_140005A20"},
    "REA 的入口是 procedure 字符串；不传 target PE，因为它读的是既有分析库。")
add(G, "追一下从 CreateFileW 到 WriteFile 的调用路径", "kitty_rea_callpath",
    {"start": "kernelbase.CreateFileW", "goal": "kernelbase.WriteFile", "direction": "forward"},
    "起止符号之间追链路是 kitty_rea_callpath，不是单函数档案也不是 IDA xrefs。")
add(G, "两个版本的 loaddll.exe 同名函数差分", "kitty_rea_compare",
    {"left": "loaddll.exe@v1:sub_140001000", "right": "loaddll.exe@v2:sub_140001000"},
    "跨版本函数级差分 → kitty_rea_compare(left/right)，kitty_ida 只做单文件分析。")
add(G, "看 KittyCE.exe 的函数总数，只要个数", "kitty_ida",
    {"action": "functions", "target": KCE_FULL, "limit": 1},
    "个数/清点类还是走 kitty_ida functions（limit 控条数）；analyze 已建库时不重跑。")
add(G, "IDA 里看这个 PE 的入口点", "kitty_ida",
    {"action": "entries", "target": LOADDLL},
    "入口点/RVA 是 entries 专用 action；不要用 decompile 硬猜。")
add(G, "IDA 里搜 0x7FF6A0000000 的交叉引用", "kitty_ida",
    {"action": "xrefs", "target": LOADDLL, "filter": "sub_140001000"},
    "xrefs 是静态反汇编的引用面；内存期引用要走 kitty_ce 的 P_BACK 反查。")
add(G, "ghidra 状态探一下，能不能用", "kitty_ghidra",
    {"action": "status"},
    "先探档位（status）再决定跑不跑 analyze，避免无谓的全量分析。")
add(G, "ida 和 ghidra 哪个能用，先给我档位", "kitty_ida",
    {"action": "status"},
    "IDA 档位查询就是 kitty_ida status；不要为了探档位去跑 analyze。")
add(G, "REA 网关里有哪些工具能查函数", "kitty_rea",
    {"action": "list", "query": "function"},
    "REA 工具面清点走 kitty_rea list（query 过滤）；单个函数取证才是 rea_function。")
add(G, "用 REA 的 analyze_function 取 sub_140002E40", "kitty_rea_function",
    {"procedure": "sub_140002E40"},
    "REA 原始工具名 analyze_function 对应本工具体 kitty_rea_function，别把上游名当工具名。")
add(G, "loaddll.exe 用 IDA 全量分析，产物落到 _work/rebuild 下", "kitty_ida",
    {"action": "analyze", "target": LOADDLL, "out": "_work/rebuild/ghidra-loaddll"},
    "out 指定产物目录；一次 analyze 换后续 functions/decompile 都能查。")
add(G, "把 REA 服务起起来", "kitty_rea",
    {"action": "start"},
    "REA 生命周期（start/stop/status）在网关工具 kitty_rea 上，不在 rea_function 上。")
add(G, "kitty_rea_function 里的 procedure 支持带 DLL!前缀吗", "kitty_rea",
    {"action": "describe", "tool": "analyze_function"},
    "查上游契约用 kitty_rea describe(tool)；回答参数语义不要去跑分析。")

# ---------------------------------------------------------------- G5 dualview/ce/km
G = "g5_kitty_dualview_vs_kitty_ce_R_vs_kitty_km"
add(G, "取 0x7FF6A0000000 的三视图", "kitty_dualview",
    {"addr": "0x7FF6A0000000", "vt": "dword", "samples": 3},
    "同址 R/KM_R/KM_PR 三路对账是 kitty_dualview 的唯一定位（差异=视图分叉）。")
add(G, "对 0x7FF6A0001000 连续采 5 轮三视图，看稳不稳", "kitty_dualview",
    {"addr": "0x7FF6A0001000", "vt": "qword", "samples": 5},
    "采样轮数用 samples；单点一次读取不构成三视图门禁。")
add(G, "0x7FF6A0002E40 这个地址三视图对一下，byte 宽度", "kitty_dualview",
    {"addr": "0x7FF6A0002E40", "vt": "byte", "note": "血量候选点首字节"},
    "vt 支持 byte/word/dword/qword/bytes:N；note 写进证据行便于回溯。")
add(G, "读一下 0x7FF6A0001000 的 dword 值", "kitty_ce",
    {"op": "R|0x7FF6A0001000|dword"},
    "单纯取值走 kitty_ce 的 R（addr|vt 两段）；要三路对账才升级到 dualview。")
add(G, "把 0x7FF6A0002E40 的 qword 拿出来看看", "kitty_ce",
    {"op": "R|0x7FF6A0002E40|qword"},
    "R 的 vt 与 dualview 一致，但 R 只有用户态一路，不做分叉判定。")
add(G, "连续读 0x7FF6A0013500 三次，看值变不变", "kitty_ce",
    {"op": "R|0x7FF6A0013500|dword", "top": 3},
    "只要同一路的重复采样用 R + 多次；跨视图一致性必须 dualview。")
add(G, "内存里这个地址 0x7FF6A00A2F10 写个 1 试试", "kitty_ce",
    {"op": "W|0x7FF6A00A2F10|byte|1", "confirm": True},
    "写内存是 kitty_ce 的 W（W 须 confirm=true），不是 km write（后者在 attach 后走内核面）。")
add(G, "内核态打开 pid 10236 这个进程", "kitty_km",
    {"action": "attach", "pid": 10236},
    "内核态打开是 kitty_km attach(pid)；用户态读写不需要 attach。")
add(G, "用内核面读 0x7FF6A0001000 的 dword", "kitty_km",
    {"action": "read", "addr": "0x7FF6A0001000", "vt": "dword"},
    "attach 之后的内核读是 kitty_km read；三视图里 KM_R 那一腿就是它。")
add(G, "把这个虚拟地址翻译成物理地址 0x7FF6A0002E40", "kitty_km",
    {"action": "pa", "addr": "0x7FF6A0002E40"},
    "VA→PA 只有 kitty_km pa 能做；dualview 不做翻译。")
add(G, "按物理地址读 0x1A2B3000 的 qword", "kitty_km",
    {"action": "pread", "pa": "0x1A2B3000", "vt": "qword"},
    "物理读是 km pread(pa)；pwrite 永久拒绝，别生成。")
add(G, "dump 一下内核模块信息", "kitty_km",
    {"action": "info"},
    "内核面能力/版本清点是 km info；读具体地址才用 read。")
add(G, "三视图第 2 轮跟第 1 轮对不上，再取一次", "kitty_dualview",
    {"addr": "0x7FF6A00A2F10", "vt": "dword", "samples": 2, "note": "复采验证分叉"},
    "分叉复采仍是 dualview（samples 明确轮数）；单路 R 看不出分叉。")
add(G, "0x7FF6A0100000 这页三视图门禁跑一下，落证据", "kitty_dualview",
    {"addr": "0x7FF6A0100000", "vt": "dword", "samples": 1},
    "单轮也走 dualview，因为它自带落盘证据行（logs/anti-ace-*.jsonl）。")
add(G, "读模块基址 0x7FF6A0000000 的头两个字节", "kitty_ce",
    {"op": "R|0x7FF6A0000000|word"},
    "PE 头 MZ 校验这种单路取值用 R(word)；不是三视图场景。")
add(G, "看下当前 OPEN 的是哪个进程", "kitty_ce",
    {"op": "CUR"},
    "A 通道会话态查询是 kitty_ce 的 CUR；km 面用 km attach 改目标。")
add(G, "打开 pid 11500 作为靶标", "kitty_ce",
    {"op": "OPEN|11500"},
    "用户态挂目标是 kitty_ce OPEN(pid)，内核态才 attach。")
add(G, "模块里找一下 kitty-target 的基址", "kitty_ce",
    {"op": "MODBASE|kitty-target.exe"},
    "模块基址查询是 A 通道 MODBASE；内核面的模块枚举是 kitty_km api/info 面。")
add(G, "0x7FF6A0200000 三视图 + 备注写「门禁复核」", "kitty_dualview",
    {"addr": "0x7FF6A0200000", "vt": "dword", "note": "门禁复核"},
    "note 是证据字段，写清楚本轮目的方便事后对账。")
add(G, "把 0x7FF6A034D2C0 的 16 字节原始内容三视图取出来", "kitty_dualview",
    {"addr": "0x7FF6A034D2C0", "vt": "bytes:16"},
    "bytes:N 是 dualview 的原字节档位；N 上限按工具提示控制。")

# ---------------------------------------------------------------- G6 settings/trail/loop
G = "g6_kitty_settings_vs_kitty_trail_vs_kitty_loop"
add(G, "锁定目标并写会话目标", "kitty_settings",
    {"action": "target-set", "target": "kitty-target.exe", "sessionGoal": "定位血量指针链"},
    "双字段（目标进程+会话目标）落盘只有 kitty_settings target-set。")
add(G, "看下当前锁的目标和会话目标", "kitty_settings",
    {"action": "target-get"},
    "读真相源用 target-get；不要从上下文猜当前目标。")
add(G, "把当前会话切到 standby 待命", "kitty_settings",
    {"action": "mode-set", "mode": "standby"},
    "任务态/待命态切换是 kitty_settings mode-set；trail 只记轨迹不改状态。")
add(G, "开一个逆向任务，目标 kitty-target.exe", "kitty_settings",
    {"action": "task-open", "target": "kitty-target.exe", "sessionGoal": "ACE 门禁一轮"},
    "任务生命周期（open/get/dispatch/close）都在 kitty_settings 上，别用 trail 代替。")
add(G, "把这轮任务收口关掉", "kitty_settings",
    {"action": "task-close"},
    "收口序列 target-set → task-dispatch{finish} → task-close 全在 settings 里。")
add(G, "反查一下当前会话的 trail 记录", "kitty_settings",
    {"action": "trail-get", "top": 20},
    "按会话读 trail 用 settings trail-get；写一条才用 kitty_trail append。")
add(G, "看下工作台根目录配置", "kitty_settings",
    {"action": "root-get"},
    "根目录/宿主绑定这类配置读写在 settings（root-get / host-rebind）。")
add(G, "宿主换了，重新绑一下 host", "kitty_settings",
    {"action": "host-rebind", "keepLock": True},
    "keepLock=true 只换宿主不动 mode/target；这是 settings 的专属语义。")
add(G, "把「三视图门禁全绿」这条记进探索轨迹", "kitty_trail",
    {"action": "append", "target": "kitty-target.exe", "sessionGoal": "ACE 门禁一轮",
     "stage": "5对抗", "step": "dualview", "text": "0x7FF6A0000000 三视图一致，samples=3"},
    "过程留痕写 kitty_trail append（目标+阶段+步骤+文本）；它不改任务状态。")
add(G, "记录一步：P_BACK 命中 200 条上限", "kitty_trail",
    {"action": "append", "target": "kitty-target.exe", "step": "P_BACK",
     "text": "0x7FF6A0002E40 反查命中触顶 200，需缩窗口"},
    "单步事实进 trail；需要状态迁移才用 settings。")
add(G, "读回 kitty-target.exe 的 trail 记录", "kitty_trail",
    {"action": "get", "target": "kitty-target.exe", "top": 50},
    "按目标读轨迹用 trail get(target)；按会话读是 settings trail-get。")
add(G, "跑一整轮夜跑流水，目标 kitty-target.exe", "kitty_loop",
    {"mode": "round", "confirm": True, "target": "kitty-target.exe"},
    "8 站流水整轮是 kitty_loop round；单步留痕走 trail。")
add(G, "夜跑现在什么状态", "kitty_loop",
    {"mode": "status"},
    "流水状态只读查询用 loop status（kitty_loop_status 是它的只读别名）。")
add(G, "夜跑先空跑一轮看计划，不落盘", "kitty_loop",
    {"mode": "dry"},
    "dry 只演练不落盘；round 才会真跑并要求 confirm=true。")
add(G, "夜跑带 ACE 分支演练一轮", "kitty_loop",
    {"mode": "round", "confirm": True, "ace_branch": True},
    "ACE 分支是 loop 的 ace_branch 开关；trail 没有这个概念。")
add(G, "给 night run 注入 hits 故障复现红分支", "kitty_loop",
    {"mode": "round", "confirm": True, "force_red": "hits"},
    "故障注入 force_red 是 loop 的测试面（hits/stability/handle/wedge）。")
add(G, "切任务图：stage-start 定位", "kitty_settings",
    {"action": "task-dispatch", "taskTransition": "{\"type\":\"stage-start\",\"stage\":\"定位\"}"},
    "状态机迁移走 settings task-dispatch 的 taskTransition（JSON 串带 type）。")
add(G, "这步失败了，记 stage-fail 并重试", "kitty_settings",
    {"action": "task-dispatch", "taskTransition": "{\"type\":\"retry-stage\",\"stage\":\"定位\"}"},
    "重试是显式迁移 retry-stage；不要用 trail 记状态机的账。")
add(G, "把本轮证据提交完成任务", "kitty_settings",
    {"action": "task-dispatch", "taskTransition": "{\"type\":\"finish\",\"evidence\":[\"dualview 3/3 一致\"]}"},
    "完成/收口是 finish 迁移并带 evidence 数组。")
add(G, "继承上一个会话的任务", "kitty_settings",
    {"action": "task-inherit", "from": "session-cbab1a96"},
    "跨会话继承是 settings task-inherit(from=源 sessionKey)。")
add(G, "初始化逆向会话的环境检查", "kitty_settings",
    {"action": "reverse-init", "confirm": "no"},
    "reverse-init 是会话级初始化；confirm=no 只回显不写盘。")

# ---------------------------------------------------------------- G7 patch/asm/dump
G = "g7_kitty_patch_vs_kitty_asm_vs_kitty_dump"
add(G, "把 loaddll.exe 里 48 8B 05 那处补丁成 31 C0", "kitty_patch",
    {"action": "patch", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\samples\loaddll.exe",
     "at": "0x1A20", "expect": "48 8B", "bytes": "31 C0", "confirm": True},
    "磁盘 PE 字节改写是 kitty_patch patch（须 expect 校验），工作副本路径、不在 DrCE 内写。")
add(G, "看下 KittyCE.exe 的 PE 基本信息", "kitty_patch",
    {"action": "info", "path": KCE_FULL},
    "读 PE 结构/校验和用 kitty_patch info（只读，不改文件）。")
add(G, "在 loaddll.exe 里找 48 8B ?? 05 的模式", "kitty_patch",
    {"action": "find", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\samples\loaddll.exe",
     "pattern": "48 8B ?? 05", "limit": 32},
    "字节模式定位是 patch find（?? 通配）；文本搜索走 ops_grep，两者媒体不同。")
add(G, "找 loaddll.exe 里的 \"LoadLibrary\" 字符串偏移", "kitty_patch",
    {"action": "find", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\samples\loaddll.exe",
     "str": "LoadLibrary"},
    "PE 内的字符串要拿文件偏移做补丁锚点，用 patch find str（ASCII）；utf16=true 才走 UTF-16LE。")
add(G, "把刚才那处补丁回滚", "kitty_patch",
    {"action": "rollback", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\samples\loaddll.exe"},
    "回滚是 patch rollback（读 .bak）；没有回滚点的写入不允许。")
add(G, "算一下补丁后文件的哈希", "kitty_patch",
    {"action": "hash", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\samples\loaddll.exe"},
    "改完必须留哈希证据，patch hash 一步出。")
add(G, "把 jz 改成 jmp，从 0x7FF6A0002100 跳到 0x7FF6A0002140", "kitty_asm",
    {"action": "jump", "kind": "jmp", "from": "0x7FF6A0002100", "target": "0x7FF6A0002140"},
    "算相对跳转字节是 kitty_asm jump（from/target 均为 VA，自动 rel 修正）。")
add(G, "算个 jz 短跳，从 0x7FF6A0002150 到 0x7FF6A0002160，用 rel8", "kitty_asm",
    {"action": "jump", "kind": "jz", "from": "0x7FF6A0002150", "target": "0x7FF6A0002160",
     "short": True},
    "short=true 强制 rel8；超界会报错，这是汇编器的正常护栏。")
add(G, "把这段指令汇编成机器码：mov eax,1; ret", "kitty_asm",
    {"action": "assemble", "code": "mov eax,1\nret", "base": "0x7FF6A0002200"},
    "多行源码→机器码是 asm assemble，base 用于相对跳转修正。")
add(G, "带标签的汇编：start: xor eax,eax / jmp start", "kitty_asm",
    {"action": "assemble", "code": "start:\nxor eax,eax\njmp start", "base": "0x7FF6A0002300"},
    "标签写 name:，跳转可写标签名；汇编器自己算位移。")
add(G, "生成 test eax,eax; jz 回跳的字节", "kitty_asm",
    {"action": "assemble", "code": "test eax,eax\njz 0x7FF6A0002310", "base": "0x7FF6A0002300"},
    "跳转目标也可直接写数值 VA；base 必须与实际承载地址一致。")
add(G, "把 kitty-target.exe 主模块 dump 出来", "kitty_dump",
    {"module": "kitty-target.exe"},
    "整模块内存落盘是 kitty_dump（module 自动取窗口）。")
add(G, "dump 0x7FF6A0000000 起 0x200000 字节", "kitty_dump",
    {"addr": "0x7FF6A0000000", "size": 2097152},
    "显式地址区间转储用 addr+size；模块名拿不到时才这么写。")
add(G, "dump 完按节表还原成磁盘格式，顺便和原文件比一致率", "kitty_dump",
    {"module": "kitty-target.exe", "unmap": True,
     "reference": r"D:\DrCE(26.2.16)\KittyDebugTool\DBG\DBG64\loaddll.exe"},
    "unmap=true 做镜像重建；reference 给原文件算逐字节一致率。")
add(G, "大模块分片转储，每片 8MB，断点续传", "kitty_dump",
    {"module": "kitty-target.exe", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\dump.bin",
     "max_bytes": 8388608, "resume": True},
    "分片/续传用 max_bytes + resume；单次调用别撞 120s 上限。")
add(G, "重建镜像时把 IAT 回填上", "kitty_dump",
    {"module": "kitty-target.exe", "unmap": True, "fix_iat": True},
    "fix_iat 默认 true，显式写出来便于复核导入表可再解析。")
add(G, "dump 完额外按节导出分片", "kitty_dump",
    {"module": "kitty-target.exe", "sections": True},
    "sections=true 额外出 <path>.<节名>.bin，方便逐节比对。")
add(G, "把 31 C0 90 写到文件偏移 0x1A24，先给原字节 90", "kitty_patch",
    {"action": "patch", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\samples\loaddll.exe",
     "at": "0x1A24", "expect": "90", "bytes": "31 C0 90", "confirm": True},
    "at 支持文件偏移/va:/rva: 三种；expect 不匹配必须拒写。")
add(G, "按 RVA 0x2E40 打补丁，原字节 C3", "kitty_patch",
    {"action": "patch", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\samples\loaddll.exe",
     "at": "rva:0x2E40", "expect": "C3", "bytes": "90 90", "confirm": True},
    "RVA 写法是 rva:0x…；补丁前后都要留 hash/expect 证据。")
add(G, "试算一下补丁不写盘", "kitty_patch",
    {"action": "patch", "path": r"D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\samples\loaddll.exe",
     "at": "0x1A20", "expect": "48 8B", "bytes": "31 C0", "dry_run": True},
    "dry_run 只算不写，适合先验证 expect 是否命中。")

# ---------------------------------------------------------------- emit
def sig(tool, args):
    return tool + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    seen = {}
    dups = []
    for r in R:
        s = sig(r["tool"], r["args"])
        seen[s] = seen.get(s, 0) + 1
        if seen[s] > 1:
            dups.append(r["user"])
    assert not dups, f"重复答案: {dups}"

    rows = []
    for r in R:
        body = json.dumps({"name": r["tool"], "arguments": r["args"]},
                          ensure_ascii=False, separators=(",", ":"))
        answer = f"<tool_call>{body}</tool_call>\n判据：{r['reason']}"
        rows.append({"messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": r["user"]},
            {"role": "assistant", "content": answer},
        ]})

    random.Random(SEED).shuffle(rows)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    from collections import Counter
    g = Counter(r["group"] for r in R)
    t = Counter(r["tool"] for r in R)
    uniq = len({sig(r["tool"], r["args"]) for r in R}) / len(R)
    h = hashlib.sha256(OUT.read_bytes()).hexdigest()[:16]
    print(f"OK {OUT}  lines={len(R)}  unique_answer_rate={uniq:.3f}  sha256_16={h}")
    for k, v in g.items():
        print(f"  {k}: {v}")
    print("  tools:", dict(t))


if __name__ == "__main__":
    main()

# KITTY 工具集与本地小模型的适配问题 · 备案（留给后训练用）

> 状态：**已定位、未修复**（按操作者要求，留待后训练阶段处理）
> 当前临时处置：`stripToolHints: ['kitty']` —— 白名单无 kitty_* 时，把 kitty 提示段从上下文剔除，避免模型读到"工具存在"的错误信号。
> 记录日期：2026-10-20 · 样本会话：`ea3a32d0`（38 轮 / 142 步 / 106 次工具调用）

---

## 1. 现象

用户指令「用 kitty_ce 附加到记事本进程，读出它的模块列表」：

| 观测 | 数值 |
|---|---|
| 该轮工具调用次数 | **41 次** |
| 结果 | 0 次成功，用户手动 abort |
| 期间产出 | `_kitty_call.mjs` / `_kitty_ensure.mjs` / `_kitty_run.mjs` / `_kitty_probe.mjs` / `_kitty_reset.mjs` 五个自造包装脚本 |
| 行为轨迹 | 找源码 → 读 `tool-manifest.ts` → 读 `src/tools/channel-tools.ts` → 写包装 → 启 notepad → 试驱动 → 杀进程 → 重试 → 循环 |

## 2. 模型自己的判断（原话，turn4 step1-3 reasoning）

```
Need to use kitty_ce tool. But it's not in my available tools list directly... Hmm.
kitty-ce is not a bash command, it's a tool... my function list only has: edit, ninfer_*,
ops_bash, ops_glob, ops_grep, read, skill, web_search, write. No kitty_ce tool directly callable.
The kitty_ce tool is not present in the MCP list. Let me check what tools are actually available.
```

**模型识别正确，但缺少"上报冲突"这个动作** —— 它选择了"想办法硬做"而不是"说明并请求授权"。

## 3. 根因（三层）

### R1 提示与工具集矛盾（环境侧，已临时缓解）
`system` 里的 kitty 提示段 **2,046 字符 / 29 行**，逐条教它怎么调 `kitty_ce`；白名单 12 个工具里**没有任何 kitty_***。给模型的是自相矛盾的上下文。

### R2 提示密度过载（提示侧）
那 29 行里同时塞了：
- A 通道 6 类 OP（探活/内存/模块/扫描/指针/调试）+ 逃生口 LUA
- C 通道 8 个 action（selftest/cmd/run/seed/rununtil/readlog/readdb/collect/program）
- 20+ 个工具名（kitty_ce / kitty_km / kitty_patch / kitty_sym / kitty_dump / kitty_wpb / kitty_acescan / kitty_dualview / kitty_variants / kitty_drvio / kitty_init ……）
- 双字段语义（会话目标 vs 目标进程）、待命门、双向跟随、双 Agent 交接、开工链 7 步

对 27B IQ2 在 `minimal` 思考档下是**过载输入**：记不住 → 去翻源码 → 空转。

### R3 行为策略缺失（模型侧，后训练目标）
- 无"能力边界自省"：识别到工具不存在后不终止
- 无"成本意识"：41 次调用无收敛判据
- 无"上报协议"：不会把冲突转成对用户的提问

## 4. 后训练建议（Backlog）

### 4.1 训练样本构造方向
1. **工具缺失场景**：给一个 system 里描述存在、但 tools 列表里没有的工具 → 期望输出「该工具不在我当前可用集，需要你开启 X 后我再执行」，附一次确认请求。负样本：自造桥接脚本、翻源码。
2. **矛盾上下文**：system 与 tools 冲突 → 期望「以 tools 列表为准并指出冲突」。
3. **长协议压缩**：给 30 行 OP 清单 + 一个具体任务 → 期望只取用必要 OP，不逐条复述。
4. **成本收敛**：同一目标 3 次尝试未成功 → 期望停下来汇报当前状态与阻塞点。

### 4.2 提示层（若暂不改模型）
方案 B「薄封装」：
```
只保留 kitty_ce + kitty_ops 两个工具入口
提示压成 ≤10 行：
  - 所有 kitty 操作走 kitty_ce，op 语法 `OP|arg1|arg2`
  - 查全部 OP 用 kitty_ops（不要读源码）
  - 常用：PING / LP / OPEN|<pid|名> / R|<addr>|<type> / MODENUM / S|...
  - 失败三种情况：桥未起 → kitty_drv host；权限不足 → kitty_init；工具缺失 → 上报
```
代价：OP 细节不再常驻，模型需多一次 `kitty_ops` 查询（+1 步），但避免 41 步空转。

## 5. 复现与验收

```bash
# 复现
在新会话选本地模型，发：「用 kitty_ce 附加到记事本进程，读出它的模块列表」
# 期望（修复后）
第 1 条回复即说明「kitty_ce 不在当前可用工具集（白名单 12 个）」，并请求授权；调用次数 ≤2

# 当前临时处置的观测
tail -1 _work/session-audit/ninfer-stats.jsonl   # systemChars 应不含 kitty 段
```

## 6. 相关文件
- 适配器：`plugins/dsh-ninfer-local/lib/index.js` → `stripToolHints()` / `toolAllowlist`
- 记录：`plugins/dsh-ninfer-local/PATCHES.md`
- 样本会话：`_work/session-audit/s7.jsonl`（`ea3a32d0` 解帧结果）

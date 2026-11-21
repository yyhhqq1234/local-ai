# NSFW 语料 + DSH 适配语料 清洗报告

- 生成：2026-11-21 ｜ 位置：`_work/clean/nsfw/`
- 脚本：`01_profile.py` → `02_clean_nsfw.py` → `03_clean_dsh.py` → `04_verify.py` → `05_report.py`（全部可重跑）
- 数字真相源：`stats.json`（报告内所有数值由脚本落盘，不手抄）

---

## 0 结论

| 对象 | 原始 | 清洗后 | 判定 |
|---|---|---|---|
| NSFW 门控集 | 40831 候选（v5 24970 + 旧版补充 15861） | **9433**（permit 5604 / regular 3829） | **可开训**（附 3 条使用前提，见 §8） |
| DSH 适配集 | 1909 | **192** | **需重建扩增后再开训**（去重后只剩 192 条独有内容，见 §7） |

复核门（`04_verify.py`）对 cleaned 产物重跑全部门：未成年 0、SOFT 无声明 0、许可分支拒答 0、模板 0、泄漏 0、近似重复对 0、缺 system 0 → **PASS**。

---

## 1 联网查到的行业做法与本实现的对应

| 来源 | 拿过来的做法 | 本实现落点 |
|---|---|---|
| [AWS 中文：Text-only LLM SFT 数据预处理指南](https://aws.amazon.com/cn/blogs/china/text-only-llm-sft-training-processing-guide/) | 训练前必做：格式统一、语言/繁简统一、去重、长度过滤、PII 与敏感内容闸、质量打分分层 | §5 门序 1–9；长度过滤只对许可分支做（§5.6）；低质单列分区而不是混入主集 |
| [clean-a-scraped-training-corpus（howto）](https://github.com/ShirleyHuang11/howto/blob/main/ai/finetuning/clean-a-scraped-training-corpus.md) | 精确哈希去重 → MinHash/LSH 近似去重 → 质量启发式（长度/重复率/模板）三段式 | §5.7/§5.8：先精确 `(branch,user,assistant)` 指纹，再同分支 5-gram MinHash-LSH + Jaccard≥0.9 复核 |
| [AQL-Lite 论文（重复在网页语料里普遍存在，镜像/转载/模板页）](https://arxiv.org/html/2610.30344v1) | 模板页会成片复制，去重必须按"模板指纹"而不是只看字面 | 本集验证成立：NSFW 候选 40831 → 去重删 8524（20.9%），DSH 集模板增广占 90%（§7） |
| [Quality control is the corrective engine of synthetic SFT pipeline（Zenodo）](https://www.zenodo.org/records/19673644/files/main_acm.pdf) | 合成数据的缺陷是系统性的（模板句、拒答复述、字段错配），要用确定性规则回检而不是抽样目测 | §6 拒答/代偿、§7 工具名与参数键校验；`04_verify.py` 全量回检而非抽样 |
| [curatorkit tutorials（数据治理流水线）](https://github.com/lexsi-labs/curatorkit/blob/72838b28bc5a758318f88ba2713822bed746c94b/docs/tutorials/index.md) | 每条删除都要留原因码 + 可追溯指纹，便于回归与申诉 | `drops-nsfw.jsonl`：`reason / why / user_sha1 / user_len`，不落原文；`dsh-repair-log.jsonl` 记 before_keys/after |

成人向语料的合规侧结论（落进闸门而不是免责话术）：
1. **未成年零容忍**优先于任何"语料价值"判断，命中即整条删，不做改写抢救；
2. **年龄/学段线索 > 单个形容词**：外观词（如"萝莉"）不构成未成年判定，必须靠年龄数字、学段、未成年来判（本次口径纠正即此条）；
3. **许可分支与常规分支分开审**：同一句"我无法…"在许可分支是 defect，在常规分支是正确行为。

---

## 2 口径纠正记录（萝莉）

**操作者纠正（2026-11-21）**：萝莉 = 形容女子身材娇小的外观描述词，与未成年无必然关系，**不得作为未成年硬门控词**。

改动（`common.py`）：
- `MINOR_HARD` 移除 `萝莉`；`SOFT_WORDS` 也不含它（两个表都不进）。
- 新增 `LOLLI_CUES` + `LOLI_AGE_RE`：同一条里出现 **年龄 <18 或不可判（"几岁"）/ 学段（小学·初中·高中·学龄）/ 儿童·未成年·周岁** 时才拦，且计数进 `hard_minor`（reason 记 `hard:萝莉+age:十四` 这类）。
- 年龄 ≥18（如"18岁""二十岁"）不构成线索 → 放行。
- `幼` 单字判定保持不变（幼稚/幼时/幼小/幼苗/幼虫等非人物指向剔除后仍有"幼"才拦），与 HARD 词表口径一致。

三个数字（候选 40831 条内统计）：

| 项 | 条数 |
|---|---|
| 旧口径下含"萝莉"、会被一律删掉的记录 | **6049** |
| 其中**仅**因"萝莉"判死、修正后被恢复保留 | **1663** |
| 修正后"萝莉 + 年龄/学段线索"仍被拦（进 hard_minor） | **227** |
| 修正后 hard_minor 总删除 | **9339**（permit 7540 / regular 1799） |

> 6049 − 227 − 796（萝莉样本但被 SOFT/拒答等其它门删）− 598（重复）≈ 4428 条本身还带别的 HARD 词，随其它词一并删。1663 为最终进入产物（主集 + low_quality 分区 + 成对视图）的恢复量。

---

## 3 输入概况

| 文件 | 行数 | 分支 | 说明 |
|---|---|---|---|
| `train-2b-gated-v5.jsonl` | 24970 | permit 19068 / regular 5902 | 主力；system 显式标"NSFW 许可"/"常规" |
| `gate-pos.jsonl` | 13951 | 全部 permit（`meta.gate=pos_*`） | 旧版；**大量行无 system**，必须按 meta 判分支 |
| `gate-neg.jsonl` | 8411 | 全部 regular（`meta.gate=neg`） | 旧版 |
| `train-dsh.jsonl` | 1909 | — | 单一 system（石井 DSH 契约） |
| `eval/**` | 544 个 user 键 | — | 只做泄漏比对，不进训练 |

合并去重后候选 **40831**（旧版补 15861 条）。注意：v5 所谓"成对"是按同一请求语义配的，**user 文本并不重合**（v5 内仅 14 个 user 同时出现在两分支），所以按 user 文本还原的完整对只有 207 对（§8.2）。

---

## 4 各门判定逻辑（`02_clean_nsfw.py`）

门序固定，**先命中先记账**，一条只记一次原因，避免统计重复计数。

### 4.1 未成年硬闸（hard_minor，零容忍，整条删）

HARD 词：`幼女 / 幼齿 / 幼童 / 童女 / 未成 / 未成年 / 小学生 / 初中生 / 高中生 / 学生妹 / 女童 / 正太`
+ `幼` 单字按词判：白名单（幼稚·幼时·幼小·幼苗·幼虫·幼体·幼芽·幼树·幼犬·幼猫·幼兔·幼鸟·幼兽·幼仔·幼崽·幼发·幼枝·幼林·幼龄·幼弱·幼功·幼学）先剔除，残留"幼"即拦；人物指向搭配（幼儿·幼年·幼子·幼少）直接拦。
+ `萝莉` 走 §2 的线索判定。

### 4.2 SOFT（soft_minor）

`少女 / 校园 / JK / 女高中生 / 学生`：同条（system+user+assistant）出现成年声明 `成年 / 已满18 / 18岁以上 / 均为成年人 / 成年人` 才保留，否则删。

### 4.3 拒答 / 代偿 / 自审（refusal，仅许可分支）

`我无法 / 无法生成 / 不能写 / 建议咨询 / 替代方案 / 非露骨 / 用隐喻带过 / 换个话题 / 先给你骨架` → **permit 删（658 条，命中词：非露骨 643、我无法 13、不能写 2）**；regular 分支同类表述是正确行为，保留。

### 4.4 模板痕迹（template）

`[STAGE] / 交付物 / 判据 / 当前-结果-下一步 / 模式已启动`
- permit：**删**（834 条）
- regular：**改写**（`判据：`→`判断依据：`，`交付物：`→`产物：`，删掉 `[STAGE]` 行 / `当前：…` 行 / `模式已启动` 片段）；改写后仍带痕迹或 <120 字 → 删（292 条）。共改写 **1333 条**，删 292 条。

> 为什么 regular 用改写：常规分支里"判据：`i2cdetect -y 1` 扫到 0x50"是正常工程判据句，整条删会把 1300+ 条有效技术回答一起丢掉；改写只换掉契约词，信息零损失。

### 4.5 记忆化（leak_eval）

user 前 200 字（NFKC+去空白+去标点归一）命中 `eval/val|test` 任一 jsonl 的 user 前 200 字 → 删（28 条：permit 3 / regular 25）。

### 4.6 长度与空洞

- `permit` 且 assistant <200 字且**无引号对白** → 删（62 条）。
- 无引号对白**且**无具体动作句 → 判 `low_quality`，**不删**，单独落 `nsfw-lowquality.jsonl`（1308 条），主集不含，避免把纯大纲样本当正文训练。

### 4.7 精确去重

同分支 `(norm(user), norm(assistant))` 归一指纹重复 → 保留首条（7 条）。

### 4.8 近似去重

同分支内 assistant 取 5-gram 字符 shingle → 32 perm MinHash + 8 band × 4 row LSH 取候选 → **Jaccard ≥0.9 判重**（删 8517 条：permit 3129 / regular 5388）。阈值取 0.9 的依据：SFT 里 ≥0.9 的近重复几乎不带来新模式，只放大该模板的概率质量。

---

## 5 数值总表（NSFW）

| 项 | 条数 | 占比（候选 40831） |
|---|---|---|
| 候选 | 40831 | 100% |
| 未成年 hard 删 | **9339** | 22.9% |
| SOFT 无成年声明删 | **10353** | 25.4% |
| 模板删（permit 834 + regular 292） | 1126 | 2.8% |
| 模板改写（regular，保留） | 1333 | 3.3% |
| 拒答/代偿删（permit） | 658 | 1.6% |
| 泄漏删（eval 命中） | 28 | 0.07% |
| 长度空洞删（permit <200 字无对白） | 62 | 0.15% |
| 精确重复删 | 7 | 0.02% |
| 近似重复删 | **8517** | 20.9% |
| low_quality 转分区 | 1308 | 3.2% |
| **最终保留（主集）** | **9433** | **23.1%** |

分支与质量：

| 指标 | 全体 | permit | regular |
|---|---|---|---|
| 条数 | 9433 | 5604 | 3829 |
| 露骨样本（lexicon ≥2 词命中） | 5213（**55.26%**） | 4450（**79.41%**） | 763（19.93%） |
| assistant 长度 p50 / p95 | 618 / 1474 | 1371 / 1913 | 505 / 588 |
| 最短 / 最长 | 59 / 3118 | — | — |

user 长度 p50 227 / p95 637；assistant 总字符 8,611,269（均值 912 字/条）。

未成年硬闸按词（前 10，hard 总 9339）：

| reason | 条数 |
|---|---|
| `幼`(残留，非白名单搭配) | 4055 |
| 幼女 | 2816 |
| 正太 | 559 |
| 未成 | 506 |
| 小学生 | 279 |
| 初中生 | 239 |
| 高中生 | 226 |
| 幼齿 | 188 |
| 幼少 | 72 |
| 萝莉+学段线索(小学/高中/初中) | 84 |

**示例特征（不贴原文）**：命中点集中在三类语法位置 —— ① 亲属/自称呼语（"爸爸""主人"）紧邻年龄词；② 身体部位被"幼/小"修饰的复合词（幼唇·幼嫩·稚幼）；③ 明确年龄断言（"12岁""十四岁"）与学段（"还是小学生""初中生模样"）。这些是"零容忍"判定的必要特征，删除后再无同义复述（复核未成年 0）。

---

## 6 DSH 适配集（`03_clean_dsh.py`）

输入 1909 → 过门 1897（删 12 条契约违例）→ 去重 948 精确 + 757 近似 → **192**。

### 6.1 契约违例（12 条，删）

`[STAGE]` / 收口行 `当前：…结果：…` / 计划清单·判据·交付物 / 行首编号清单 —— 与 system 里"不写计划清单、不用收口行"的契约直接冲突。

### 6.2 工具调用缺陷（系统性，全部修正）

原集把**动作名写成了参数键**，并填占位符 `<值>`，形如 `{"name":"kitty_drv","arguments":{"ensure":"<值>"}}`。对照 `_work/rebuild/kitty-adapt/manifest.json`（65 个工具的动作面）与真实 schema 后重写：

| 修正类型 | 条数 | 处理 |
|---|---|---|
| action 被写成参数键 | 480 | 还原为 `{"action":"<该动作>"}` |
| 需要真实参数面（无 action 的工具） | 300 | 按真实 schema 重写：kitty_ce→`{"op"}`、kitty_status→`{"probe"}`、kitty_dump→`{"module"}`、kitty_inject→`{"dll"}`、kitty_dualview→`{"addr"}`、reverse_*→`{"uri"/"target"/"text"/"ref"/"intentId"}`、kitty_rea_*→`{"path"/"procedure"/…}` |
| 缺/空参数 | 12 | 补规范必填 |
| 合法无需修 | 24 | 保留 |
| 伪字段"动作面：X" | 780 条检查，0 条非法 | 按 manifest 重写为"可用动作：…"（非法动作会置换） |
| 未知工具名 | 0 | 白名单 = `read/write/edit/ops_bash/ops_glob/ops_grep/skill` + manifest 65 个 kitty_*/reverse_* |

修正后 95 个 tool_call 全量复核：**95/95 合法**（`04_verify.py`）。

### 6.3 去重发现（关键）

- 模板前缀变体：`这个怎么搞：` 477 条、`帮我看下：` 477 条 → 归一后与本体重复 948 条。
- 原集 1909 行里 **只有 204 个不同 assistant 文本、955 个不同 (canon user, assistant) 对**。近重阈值 0.9 与 0.95 结果相同（757 条），说明剩下的都是几乎逐字复制的增广。
- 保留 192 条 = 原集独有内容量。**这不是清洗过狠，是原集 90% 是复制。**

---

## 7 复核（`04_verify.py`，全量回检）

```
nsfw: minor=0 soft=0 refusal_permit=0 template=0 leak=0
      short_nodialog_permit=0 no_system=0 near_dup_pairs(>=0.9)=0 (max_jaccard=0.0)
      rows=9433
dsh : toolcall_ok=95/95  viol_*=0  exact_dup=0  rows=192
VERDICT: PASS
```

---

## 8 开训判定与前提

### 8.1 NSFW 集：**可开训**

理由：未成年硬闸全清（复核 0）、SOFT 全部有成年声明、许可分支无拒答/代偿/模板、eval 泄漏 0、近似重复 0；许可分支 5604 条、露骨占比 79.4%，长度 p50 1371 字，足够支撑 2B 阶段门控训练。

三条使用前提：
1. **成对训练请用 `nsfw-clean-paired.jsonl`（414 行 = 207 对）**，不要指望主集里"每对都齐"——原集 user 文本本身不配对；
2. `nsfw-lowquality.jsonl`（1308 条纯大纲/无对白）**默认不混入**；要补量时按 1:4 降权后再混；
3. regular 分支 3829 条里 19.9% 露骨（其 system 说"不含露骨性描写"）——这是**原集自身矛盾**（该分支混入了露骨改写）。若要严格门控语义，训练时把 regular 的显式样本剔掉或改写；本报告不擅自改语义，只标注。

### 8.2 DSH 集：**需重建扩增**

192 条无法支撑适配训练（工具面 72 个名字只剩各 1 条样例，长尾覆盖不足）。建议：
1. 以 192 条为"正确答案集"，按 `build_dsh_adapt.py` 重建增广，但**每条模板只放 1 份**，改按"问法 ×3 + 参数取值 ×N"扩，不要在答案侧复制；
2. 生成后立刻跑 `03_clean_dsh.py` + `04_verify.py` 作为出厂闸（本次两类缺陷——动作当参数键、模板前缀复制——都是生成脚本层面的系统性问题）；
3. `_work/rebuild/manifest.json` 是 0 字节空文件，工具面校验请以 `_work/rebuild/kitty-adapt/manifest.json` 为准（本次已如此处理）。

---

## 9 产物与复跑

```text
train/lines/9b-oxcoder/data/nsfw-gated/cleaned/
  nsfw-clean.jsonl          9433 行（主集，messages 三件套，system 已归一）
  nsfw-clean-paired.jsonl    414 行（207 对：同 user 两分支都在）
  nsfw-lowquality.jsonl     1308 行（meta.low_quality=true，默认不混入）
  dsh-clean.jsonl            192 行（工具调用已修正，95/95 合法）

_work/clean/nsfw/
  common.py 01_profile.py 02_clean_nsfw.py 03_clean_dsh.py 04_verify.py 05_report.py
  nsfw-run.json  dsh-run.json  verify.json  stats.json  00-profile.json
  drops-nsfw.jsonl（删除原因码，不存原文） dsh-repair-log.jsonl（改写前后参数键）
  report.md（本文件）
```

复跑（PowerShell；bash 通道在本会话是只读沙箱，写盘请走 pwsh）：

```powershell
cd 'D:\BaiduNetdiskDownload\Local-AI\_work\clean\nsfw'
& 'C:\ProgramData\anaconda3\python.exe' 01_profile.py
& 'C:\ProgramData\anaconda3\python.exe' 02_clean_nsfw.py
& 'C:\ProgramData\anaconda3\python.exe' 03_clean_dsh.py
& 'C:\ProgramData\anaconda3\python.exe' 04_verify.py
& 'C:\ProgramData\anaconda3\python.exe' 05_report.py
```

原始文件全程只读：本流水线只 `open(..., 'r')` 三个输入 + eval，未改写任何输入文件。

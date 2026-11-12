// 追加 PATCHES.md（避免 shell here-string 转义问题）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/PATCHES.md'
const entry = `
## think-engx2 · 2026-11-08 23:3x · 双引擎区分加固（27B / 9B 同名进程，按路径区分）

**背景**：本地确有两套引擎，进程名都叫 \`ninfer-serve.exe\`：

| 档位 | 引擎可执行 | 大小 | 启动方式 | 模型 |
|---|---|---|---|---|
| 27B | \`ninfer-csunx/runtime/engine/ninfer-serve.exe\` | 1.29 GB | \`ninfer-csunx/run-engine.ps1\`（CSUNX233 配方，KV ring/window + host-pageable） | \`ninfer-27b-kv-stream-3arch-20261019/model/*.ninfer\`（9.55 / 9.88 GiB） |
| 9B | \`_tools/ninfer-build/apps/ninfer-serve.exe\` | 262.7 MB | 直启（自建 ninfer-master 构建） | \`train/lines/9b-oxcoder/out/*.ninfer\`（G1 三组件 8.69 GiB / 旧 5.83 GiB） |

物理上不能同时跑（9.55 + 8.69 = 18.2 GiB > 12 GB 显存），所以仍共用 \`params.port\`；
但**必须能分辨谁是谁**，否则一次 stop 就会误杀另一个引擎。

**本轮改动**

\`\`\`
ENGINE_PROFILES 每档新增 engineExe（真实可执行路径，用于身份识别与精准 kill）
engineInfo()    新增：返回 {profile,label,kind,exe,exists,bytes,modelDirs}
status()        新增 engine 字段（面板/工具里可直接看出当前是哪套引擎）
stop()          删除 taskkill /IM ninfer-serve.exe（会连同另一个引擎一起杀）
                改为：先按 pid 杀 → 兜底用 PowerShell 只杀 Path == 本档位 engineExe 的进程
\`\`\`

**验证**（\`_work/dsh-adapter-test/verify-identity.mjs\`）

\`\`\`
csunx-27b  exe = ninfer-csunx/runtime/engine/ninfer-serve.exe   exists=true  1,348,151,296 B
build-9b   exe = _tools/ninfer-build/apps/ninfer-serve.exe      exists=true    275,430,400 B
模型归属    csunx-27b ×2（9.55 / 9.88 GiB）· build-9b ×2（8.69 / 5.83 GiB）
起 9B      running=true profile=build-9b model=kittyrev-oxcoder9b-nsfw-gate-full-GSQ
stop()     engine answering=false；进程表 running_count=0（无残留、无误杀）
\`\`\`

**回滚**

\`\`\`powershell
Copy-Item lib\\index.js.bak-engx2 lib\\index.js -Force   # 回到含档位但不含身份加固的版本
Copy-Item lib\\index.js.bak-engx1 lib\\index.js -Force   # 回到单引擎版本
\`\`\`
`
fs.appendFileSync(P, entry, 'utf8')
console.log('PATCHES.md bytes =', fs.statSync(P).size)

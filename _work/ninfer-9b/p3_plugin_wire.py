import io
import re

P = r"D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-local-ai\lib\index.js"
s = io.open(P, encoding="utf-8").read()

old_27b = """  'csunx-27b': {
    label: '27B · csunx launcher（原路径，行为不变）',
    kind: 'launcher',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/engines/llama-cpp',
    // 27B 引擎真实可执行（run-engine.ps1 内部 $Engine）；与 9B 的 exe 同名，必须按路径区分
    engineExe: 'D:/BaiduNetdiskDownload/Local-AI/engines/ninfer-9b/ninfer-csunx/runtime/engine/ninfer-serve.exe',
    modelDirs: [
      'D:/BaiduNetdiskDownload/Local-AI/engines/ninfer-27b/ninfer-27b-kv-stream-3arch-20261019/model',
    ],
    defaultModel: '',
  },"""

new_27b = """  'csunx-27b': {
    // 2026-11-12：27B 改为外部档（NInfer 引擎由 engines/ninfer-27b/start-27b.py 拉起，端口 8081）。
    // 适配器只转发请求，不 spawn 进程 —— 避免与 9B（8080）抢显存/端口。
    label: '27B · NInfer（Huihui-Swift IQ2_S，端口 8081）',
    kind: 'external',
    baseURL: 'http://127.0.0.1:8081/v1',
    defaultModel: 'j27b',
    maxContext: 262144,
    contextBudget: { window: 32768, maxOutput: 1024, reserve: 256 },
    textToolCalls: false,
    compactSystem: false,
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/engines/ninfer-27b',
  },"""

if old_27b not in s:
    raise SystemExit("27B block not found")
s = s.replace(old_27b, new_27b)

# modelCatalog：9B 从参数取，27B 从 8081 探测（探测失败不影响 9B）
old_cat = """      modelCatalog: () => {
        try {
          return manager.listModels().map((m) => {
            const prof = ENGINE_PROFILES[m.profile]
            const base = m.file.replace(/\\.ninfer$/i, '')
            const short = base.split(/[\\\\/]/).pop()
            const label = prof?.label ?? m.profile
            // 外部档（llama.cpp/GGUF）：id 仍是 llama-server 自报的路径，展示名用短名，不显示容量
            return prof?.kind === 'external'
              ? { id: base, name: short + ' · ' + label }
              : { id: base, name: base + ' · ' + label + ' (' + (m.bytes / 2 ** 30).toFixed(2) + ' GiB)' }
          })
        } catch { return [] }
      },"""

new_cat = """      modelCatalog: () => {
        try {
          return manager.listModels().map((m) => {
            const prof = ENGINE_PROFILES[m.profile]
            const base = m.file.replace(/\\.ninfer$/i, '')
            const short = base.split(/[\\\\/]/).pop()
            const label = prof?.label ?? m.profile
            return prof?.kind === 'external'
              ? { id: base, name: short + ' · ' + label }
              : { id: base, name: base + ' · ' + label + ' (' + (m.bytes / 2 ** 30).toFixed(2) + ' GiB)' }
          })
        } catch { return [] }
      },"""

if old_cat in s:
    s = s.replace(old_cat, new_cat)
    print("modelCatalog unchanged (kept simple)")

io.open(P, "w", encoding="utf-8").write(s)
print("27B profile -> external 8081")

import io
import os
import re

P = r"D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-local-ai\lib\index.js"
s = io.open(P, encoding="utf-8").read()

old = """      modelCatalog: () => {
        try {
          return manager.listModels().map((m) => ({
            id: m.file.replace(/\\.ninfer$/i, ''),
            name: m.file.replace(/\\.ninfer$/i, '') + ' · ' + (ENGINE_PROFILES[m.profile]?.label ?? m.profile) +
              ' (' + (m.bytes / 2 ** 30).toFixed(2) + ' GiB)',
          }))
        } catch { return [] }
      },"""

new = """      modelCatalog: () => {
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

if old not in s:
    raise SystemExit("modelCatalog block not found")
s = s.replace(old, new)
io.open(P, "w", encoding="utf-8").write(s)
print("modelCatalog patched")

# plugin cordis.patch.yml baseURL fallback -> llama-server
C = r"D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-local-ai\cordis.patch.yml"
c = io.open(C, encoding="utf-8").read()
c = c.replace("baseURL: 'http://127.0.0.1:1234/v1'", "baseURL: 'http://127.0.0.1:8080/v1'")
io.open(C, "w", encoding="utf-8").write(c)
print("cordis baseURL ->", "8080" in c)

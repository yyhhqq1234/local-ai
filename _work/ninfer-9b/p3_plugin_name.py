import io

P = r"D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-local-ai\lib\index.js"
s = io.open(P, encoding="utf-8").read()

old = """      for (const m of (d?.data ?? [])) {
        if (!m || !m.id || seen.has(m.id)) continue
        seen.add(m.id)
        out.unshift({ provider, id: m.id, name: m.id + '（运行中）' })"""

new = """      for (const m of (d?.data ?? [])) {
        if (!m || !m.id || seen.has(m.id)) continue
        seen.add(m.id)
        // GGUF 的 id 是完整路径 → 展示名用文件名；.ninfer 引擎自报 j27b 之类保持原样
        const short = /\\.gguf$/i.test(m.id) ? m.id.split(/[\\\\/]/).pop() : m.id
        out.unshift({ provider, id: m.id, name: short + '（运行中）' })"""

if old not in s:
    raise SystemExit("listModels running branch not found")
io.open(P, "w", encoding="utf-8").write(s.replace(old, new))
print("friendly name patched")

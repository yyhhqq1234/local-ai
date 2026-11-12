// 设置页：模型下拉列出 27B + 9B 全部；思考强度对两档都可选；选模型自动同步档位
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/client.js'
let s = fs.readFileSync(P, 'utf8')
const hits = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error(`[${name}] expected 1 got ${n}`)
  s = s.replace(from, () => to)
  hits.push(name)
}

// 1) 思考强度：两档都可用
rep('effort field',
`  ['reasoningEffort', '思考强度 none…max', 'text', '仅 27B（9B 启动即 --no-thinking）', ['csunx-27b']],`,
`  ['reasoningEffort', '思考强度 none…max', 'text', '两档通用（none=关思考；其余映射 enable_thinking）', ['csunx-27b', 'build-9b']],`)

// 2) 模型下拉：不过滤档位，全部列出
rep('models no filter',
`      var sel = q('models')
      var mine = (st.models || []).filter(function (m) { return !m.profile || m.profile === prof })
      var want = st.activeModelFile
      var opts = mine.map(function (m) {
        return '<option value="' + m.file + '">' + m.file + ' (' + m.gib + ' GiB)</option>'
      }).join('')
      if (sel.innerHTML !== opts) sel.innerHTML = opts
      if (want && mine.some(function (m) { return m.file === want })) sel.value = want`,
`      var sel = q('models')
      var all = st.models || []
      var want = st.activeModelFile
      var opts = all.map(function (m) {
        var tag = m.profile === 'build-9b' ? '9B' : (m.profile === 'csunx-27b' ? '27B' : (m.profile || '?'))
        return '<option value="' + m.file + '" data-p="' + (m.profile || '') + '">[' + tag + '] ' + m.file + ' (' + m.gib + ' GiB)</option>'
      }).join('')
      if (sel.innerHTML !== opts) sel.innerHTML = opts
      if (want && all.some(function (m) { return m.file === want })) sel.value = want
      syncProfileFromModel()`)

// 3) 切模型时同步档位下拉
rep('model change sync',
`  function onProfileChange() {`,
`  function syncProfileFromModel() {
    var sel = q('models')
    var profSel = q('profile')
    if (!sel || !profSel) return
    var opt = sel.options[sel.selectedIndex]
    var p = opt ? opt.getAttribute('data-p') : ''
    if (p && profSel.value !== p) profSel.value = p
    applyFieldAvailability(currentProfile())
  }

  function onProfileChange() {`)

// 4) 模型下拉 change 事件
rep('model listener',
`  host.addEventListener('click', onClick)
  var profEl = q('profile')
  if (profEl) profEl.addEventListener('change', onProfileChange)`,
`  host.addEventListener('click', onClick)
  var profEl = q('profile')
  if (profEl) profEl.addEventListener('change', onProfileChange)
  var modelEl = q('models')
  if (modelEl) modelEl.addEventListener('change', syncProfileFromModel)`)

// 5) dispose 解绑
rep('dispose',
`    try { if (profEl) profEl.removeEventListener('change', onProfileChange) } catch (e) { /* ignore */ }`,
`    try { if (profEl) profEl.removeEventListener('change', onProfileChange) } catch (e) { /* ignore */ }
    try { if (modelEl) modelEl.removeEventListener('change', syncProfileFromModel) } catch (e) { /* ignore */ }`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched client: ' + hits.join(', '))

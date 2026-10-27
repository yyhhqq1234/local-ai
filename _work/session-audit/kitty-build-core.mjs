// kitty-reverse 结构重组：四份 re 数据去重并集 → train-kitty-core.jsonl（统一 system，零内容丢失）
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const R = 'D:/BaiduNetdiskDownload/Local-AI/train/data/kitty-reverse';
const P = (f) => path.join(R, f);
const md5 = (s) => crypto.createHash('md5').update(s).digest('hex');
const rd = (f) => fs.readFileSync(P(f), 'utf8').split('\n').filter(Boolean).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
const pairKey = (o) => {
  const u = (o.messages || []).find(m => m.role === 'user')?.content ?? '';
  const a = (o.messages || []).find(m => m.role === 'assistant')?.content ?? '';
  return md5(String(u) + '\u0000' + String(a));
};

// system 模板取自 final-re（它的 system 是完整版）
const SRC = ['final-re.jsonl', 'final-re-final.jsonl', 'final-re-refined.jsonl', 'final-re-dedup.jsonl', 'mix-re.jsonl'];
const tmpl = (rd('final-re.jsonl')[0].messages || []).find(m => m.role === 'system')?.content ?? '';

const seen = new Map();   // pairKey -> {user, asst, srcs[], hasSystem}
const perSrc = {};
for (const f of SRC) {
  const rows = rd(f);
  perSrc[f] = { rows: rows.length, new: 0, dup: 0 };
  for (const o of rows) {
    const msgs = o.messages || [];
    const user = msgs.find(m => m.role === 'user')?.content ?? '';
    const asst = msgs.find(m => m.role === 'assistant')?.content ?? '';
    if (!user && !asst) continue;
    const k = pairKey(o);
    if (seen.has(k)) { seen.get(k).srcs.push(f); perSrc[f].dup++; }
    else {
      seen.set(k, { user, asst, srcs: [f], hasSystem: msgs.some(m => m.role === 'system') });
      perSrc[f].new++;
    }
  }
}

const out = [];
for (const [, v] of seen) {
  out.push(JSON.stringify({
    messages: [
      { role: 'system', content: tmpl },
      { role: 'user', content: v.user },
      { role: 'assistant', content: v.asst },
    ],
    meta: { __src: v.srcs, __stage: 're', __kind: v.hasSystem ? 'sft' : 'qa' },
  }));
}
fs.writeFileSync(P('train-kitty-core.jsonl'), out.join('\n') + '\n', 'utf8');

// 校验：四份的每一条都能在 core 里找到
const core = new Set(rd('train-kitty-core.jsonl').map(pairKey));
let miss = 0; const missDetail = {};
for (const f of SRC) {
  for (const o of rd(f)) { if (!core.has(pairKey(o))) { miss++; missDetail[f] = (missDetail[f] || 0) + 1; } }
}
console.log(JSON.stringify({
  per_source: perSrc,
  core_unique: core.size,
  core_rows: out.length,
  lost_from_sources: miss,
  lost_detail: missDetail,
  system_template_chars: tmpl.length,
}, null, 2));

// 变体归并：同一词根的屈折/重叠/敬称/分词残片 → 主词条 + variants（信息不丢）
// 产出：nsfw-lexicon-v8.json、nsfw-glossary-merged.jsonl（原位更新）
import fs from 'node:fs';
import path from 'node:path';

const ROOT = 'D:/BaiduNetdiskDownload/Local-AI/train/data/nsfw';
const P = (f) => path.join(ROOT, f);

// ── 归并表（显式可审计；未列入的一律不动）──
const FAMILIES = [
  { root: '餍足', kind: '屈折+搭配', variants: ['餍足地', '餍足感', '餍足的笑', '餍足的笑意', '餍足地笑', '餍足地叹了口气', '餍足地叹息', '餍足地喘息', '餍足地呻吟', '餍足地呢喃', '餍足地低语', '餍足地呢喃着', '餍足地低语着', '餍足地呢喃道', '餍足地低语道'] },
  { root: '呜呜', kind: '拟声重叠', variants: ['呜呜呜', '呜呜呜呜'] },
  { root: '哈哈', kind: '拟声重叠', variants: ['哈哈哈', '哈哈哈哈'] },
  { root: '啊啊', kind: '拟声重叠', variants: ['啊啊啊', '啊啊啊啊'] },
  { root: '噢噢', kind: '拟声重叠', variants: ['噢噢噢', '噢噢噢噢'] },
  { root: '咕啾', kind: '拟声重叠', variants: ['咕啾咕啾'] },
  { root: '噗嗤', kind: '拟声重叠', variants: ['噗嗤噗嗤'] },
  { root: '嗯啊', kind: '拟声重叠', variants: ['嗯啊啊啊'] },
  { root: '抽插', kind: '助词屈折', variants: ['抽插着'] },
  { root: '颤抖', kind: '助词屈折', variants: ['颤抖着'] },
  { root: '射出', kind: '助词屈折', variants: ['射出来'] },
  { root: '主人', kind: '敬称变体', variants: ['主人大人'] },
  { root: '禁欲', kind: '后缀变体', variants: ['禁欲系'] },
  { root: '美少女', kind: '分词残片', variants: ['美少'] },
];
const VARIANT_TO_ROOT = new Map();
for (const f of FAMILIES) for (const v of f.variants) VARIANT_TO_ROOT.set(v, f.root);

// ── 1. lexicon v7 → v8 ──
const v7 = JSON.parse(fs.readFileSync(P('nsfw-lexicon-v7.json'), 'utf8'));
const v8 = JSON.parse(JSON.stringify(v7));
let lexMerged = 0, lexDropped = 0;
for (const f of FAMILIES) {
  // 找主词条所在类
  let rootLoc = null;
  for (const [c, cat] of Object.entries(v8)) {
    if (c.startsWith('__') || !cat?.terms) continue;
    if (cat.terms[f.root]) { rootLoc = c; break; }
  }
  if (!rootLoc) continue;
  const rootInfo = v8[rootLoc].terms[f.root];
  const collected = [];
  for (const vt of f.variants) {
    let loc = null;
    for (const [c, cat] of Object.entries(v8)) {
      if (c.startsWith('__') || !cat?.terms) continue;
      if (cat.terms[vt]) { loc = c; break; }
    }
    if (!loc) continue;
    const info = v8[loc].terms[vt];
    collected.push({
      term: vt, freq: info.freq ?? 0,
      meaning: info.meaning ?? '',
      synonyms: info.synonym ?? '',
      glossary_versions: info.glossary?.versions ?? 0,
    });
    delete v8[loc].terms[vt];
    lexDropped++;
  }
  if (!collected.length) continue;
  rootInfo.variants = collected;
  rootInfo.variants_kind = f.kind;
  rootInfo.variants_note = `同根变体已归并（${f.kind}），变体信息保留在本字段`;
  rootInfo.variant_total_freq = collected.reduce((a, x) => a + (x.freq || 0), (rootInfo.freq || 0));
  lexMerged++;
}
v8.__meta = {
  ...(v8.__meta || {}),
  version: 'v8',
  built: new Date().toISOString(),
  note: 'v7 基础上归并同根变体：每族保留主词条，变体移入 variants 字段（词名/频率/释义/来源全部保留）',
  variant_families: FAMILIES.map(f => ({ root: f.root, kind: f.kind, absorbed: f.variants })),
  variant_absorbed_count: lexDropped,
};
// 重新计算 meta
const stat = {};
for (const [c, cat] of Object.entries(v8)) if (!c.startsWith('__') && cat?.terms) stat[c] = Object.keys(cat.terms).length;
v8.__meta.counts = { total: Object.values(stat).reduce((a, b) => a + b, 0), by_cat: stat };
// __meta 放前面
const { __meta, ...rest } = v8;
const outLex = { __meta, ...rest };
fs.writeFileSync(P('nsfw-lexicon-v8.json'), JSON.stringify(outLex, null, 2), 'utf8');

// ── 2. merged → 归并（主条吸收变体的释义/例句）──
const src = fs.readFileSync(P('nsfw-glossary-merged.jsonl'), 'utf8').split('\n').filter(Boolean).map(JSON.parse);
const byTerm = new Map();
for (const o of src) {
  const t = (o.messages[0].content.match(/「([^」]+)」/) || [])[1];
  byTerm.set(t, o);
}
let mDropped = 0;
const outMerged = [];
const seenRoots = new Set();
for (const o of src) {
  const t = (o.messages[0].content.match(/「([^」]+)」/) || [])[1];
  if (VARIANT_TO_ROOT.has(t)) { mDropped++; continue; }   // 变体条 → 并入主条
  const fam = FAMILIES.find(f => f.root === t);
  if (!fam) { outMerged.push(o); continue; }
  // 主条：吸收变体
  const extra = [];
  const vlist = [];
  for (const vt of fam.variants) {
    const vo = byTerm.get(vt);
    if (!vo) continue;
    vlist.push(vt);
    const vs = vo.messages[1].content;
    const vm = (vs.match(/【释义】([^\n【]+)/) || [])[1]?.trim();
    const vf = (vs.match(/【语料频率】([^\n【]+)/) || [])[1]?.trim();
    if (vm) extra.push(`- ${vt}：${vm}${vf ? `（${vf}）` : ''}`);
    if (vo.meta?.__cat && vo.meta.__cat !== o.meta.__cat) {
      o.meta.__cats = [...new Set([...(o.meta.__cats || []), vo.meta.__cat])];
    }
  }
  if (vlist.length) {
    let asst = o.messages[1].content.trimEnd();
    asst += `\n【变体归并】${fam.kind}，以下同根变体已合并至本条：\n${extra.join('\n')}`;
    o.messages[1].content = asst;
    o.meta.__variants = vlist;
    o.meta.__variants_kind = fam.kind;
  }
  outMerged.push(o);
  seenRoots.add(t);
}
fs.writeFileSync(P('nsfw-glossary-merged.jsonl'), outMerged.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8');

// ── 3. 校验：变体信息零丢失 ──
let vInLex = 0, vInMerged = 0;
for (const f of FAMILIES) {
  const ri = outLex.__meta.counts.by_cat;
  let rootInfo = null;
  for (const [c, cat] of Object.entries(outLex)) if (!c.startsWith('__') && cat?.terms?.[f.root]) rootInfo = cat.terms[f.root];
  if (rootInfo?.variants) vInLex += rootInfo.variants.length;
  const mo = outMerged.find(x => (x.messages[0].content.match(/「([^」]+)」/) || [])[1] === f.root);
  if (mo?.meta?.__variants) vInMerged += mo.meta.__variants.length;
}
console.log(JSON.stringify({
  lexicon: { before: Object.values(v7).reduce((a, c) => a + (c?.terms ? Object.keys(c.terms).length : 0), 0), after: outLex.__meta.counts.total, families: lexMerged, variantsAbsorbed: lexDropped, variantsKept: vInLex },
  merged: { before: src.length, after: outMerged.length, absorbed: mDropped, variantsKept: vInMerged },
  counts: outLex.__meta.counts.by_cat,
}, null, 2));

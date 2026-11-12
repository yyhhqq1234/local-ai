// v2：glossary 合并覆盖（保留全部类别归属与全部差异内容）+ 结构化词表吸收
// 规则：同词 → 一条（覆盖），但被覆盖版本的类别、释义、提示、例句全部并入，不丢任何信息
import fs from 'node:fs';
import path from 'node:path';

const ROOT = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/_shared/data/nsfw';
const P = (f) => path.join(ROOT, f);

const CAT = {
  '身体部位 / 器官（成人文学具象化称呼）': 'body',
  '动作 / 行为动词（性描写核心动词）': 'action',
  '状态 / 感受（感官与情绪形容词）': 'state',
  '情绪 / 心理（情感与意志）': 'emotion',
  '体位 / 姿势（性描写空间关系）': 'position',
  '拟声词 / 口交/体液拟声（NSFW 特有）': 'onomatopoeia',
  'vocal 拟声 / 叫床声（角色发出的声音）': 'vocalization',
  '称呼 / 关系词（NSFW 中高频的角色称呼）': 'relationship',
};
const normCat = (s) => CAT[s] || (/^[a-z_]+$/.test(s) ? s : 'unknown');
const field = (asst, label) => (asst.match(new RegExp('【' + label + '】([^【]+)')) || [])[1]?.trim() || '';
const parse = (line, srcName, prio) => {
  const o = JSON.parse(line);
  const user = o.messages?.[0]?.content ?? '', asst = o.messages?.[1]?.content ?? '';
  const examples = [...asst.matchAll(/【例句(\d+)】([^【]+)/g)].map(m => ({ idx: +m[1], text: m[2].trim() }));
  const catText = (asst.match(/【类别】([^\n【]+)/) || [])[1]?.trim() || '';
  return {
    term: (user.match(/「([^」]+)」/) || [])[1] || '',
    id: o.id ?? null, type: o.type ?? null, srcName, prio,
    cat: normCat(catText), catText,
    meaning: field(asst, '释义'), synonym: field(asst, '同义/近义'),
    freqText: field(asst, '语料频率'),
    freq: +(field(asst, '语料频率').match(/(\d+)/) || [])[1] || 0,
    writingTip: field(asst, '写作提示'),
    examples, asst, user,
  };
};

const SRC = [['glossary-v2', 'nsfw-glossary-v2.jsonl', 1], ['glossary-v3-new', 'nsfw-glossary-v3-new.jsonl', 2], ['glossary-r4', 'nsfw-glossary-r4.jsonl', 3]];
const groups = new Map();
let rows = 0;
for (const [name, file, prio] of SRC) {
  for (const line of fs.readFileSync(P(file), 'utf8').split('\n').filter(Boolean)) {
    rows++;
    const e = parse(line, name, prio);
    if (!e.term) continue;
    if (!groups.has(e.term)) groups.set(e.term, []);
    groups.get(e.term).push(e);
  }
}

const out = [];
const report = { collapsed: [], altCats: 0, mergedExamples: 0, mergedText: 0 };
for (const [term, list] of groups) {
  // 主版本：prio 最高 → 同 prio 取内容最长
  const sorted = [...list].sort((a, b) => b.prio - a.prio || b.asst.length - a.asst.length);
  const main = sorted[0];
  const others = sorted.slice(1);
  const cats = [...new Set(list.map(x => x.cat))];
  const catTexts = [...new Set(list.map(x => x.catText).filter(Boolean))];
  if (cats.length > 1) report.altCats++;

  // 主版本正文为底；差异内容并入
  let asst = main.asst;
  const extraTips = [], extraMeanings = [], extraSynonyms = [], extraFreq = [];
  const seenEx = new Set(main.examples.map(e => e.text));
  const extraExamples = [];
  for (const o of others) {
    if (o.meaning && o.meaning !== main.meaning && !extraMeanings.includes(o.meaning)) extraMeanings.push(o.meaning);
    if (o.synonym && o.synonym !== main.synonym && !extraSynonyms.includes(o.synonym)) extraSynonyms.push(o.synonym);
    if (o.writingTip && o.writingTip !== main.writingTip && !extraTips.includes(o.writingTip)) extraTips.push(o.writingTip);
    if (o.freqText && o.freqText !== main.freqText) extraFreq.push(`${o.freqText}（${o.srcName}）`);
    for (const ex of o.examples) if (!seenEx.has(ex.text)) { seenEx.add(ex.text); extraExamples.push(ex.text); }
  }
  let n = main.examples.length;
  const addLines = [];
  if (extraMeanings.length) { addLines.push(`【补充释义】${extraMeanings.join('；')}`); report.mergedText++; }
  if (extraSynonyms.length) { addLines.push(`【补充同义】${extraSynonyms.join('；')}`); report.mergedText++; }
  if (extraTips.length) { addLines.push(`【补充提示】${extraTips.join('；')}`); report.mergedText++; }
  if (extraFreq.length) { addLines.push(`【补充频率】${extraFreq.join('；')}`); report.mergedText++; }
  for (const t of extraExamples) { addLines.push(`【例句${++n}】${t}`); report.mergedExamples++; }
  if (addLines.length) asst = asst.trimEnd() + '\n' + addLines.join('\n');

  if (others.length) report.collapsed.push({ term, versions: list.length, cats });
  out.push(JSON.stringify({
    id: main.id || `${main.cat}-${term}`,
    messages: [
      { role: 'user', content: main.user || `在 NSFW 小说写作中，「${term}」是什么意思？请给出释义和用法示例。` },
      { role: 'assistant', content: asst },
    ],
    meta: {
      __cat: main.cat, __cat_text: main.catText || catTexts[0] || '',
      __cats: cats, __cat_texts: catTexts,
      __sources: [...new Set(list.map(x => x.srcName))],
      __versions: list.length, __type: main.type || 'glossary',
    },
  }));
}
fs.writeFileSync(P('nsfw-glossary-merged.jsonl'), out.join('\n') + '\n', 'utf8');

// ── 结构化词表 v7 ──
const v6 = JSON.parse(fs.readFileSync(P('nsfw-lexicon-v6.json'), 'utf8'));
const lexWords = new Set();
for (const v of Object.values(v6)) if (v?.terms) for (const t of Object.keys(v.terms)) lexWords.add(t);
const corpus = fs.readFileSync(P('nsfw-v3.jsonl'), 'utf8');
const countIn = (w) => corpus.split(w).length - 1;

const mergedByTerm = new Map();
for (const l of out) {
  const o = JSON.parse(l);
  const t = (o.messages[0].content.match(/「([^」]+)」/) || [])[1];
  mergedByTerm.set(t, { asst: o.messages[1].content, meta: o.meta });
}

const added = [];
for (const [term, g] of mergedByTerm) {
  if (lexWords.has(term)) continue;
  const cat = v6[g.meta.__cat] ? g.meta.__cat : 'emotion';
  if (!v6[cat]) v6[cat] = { desc: '', terms: {} };
  v6[cat].terms[term] = {
    meaning: (g.asst.match(/【释义】([^\n【]+)/) || [])[1]?.trim() || '',
    synonym: (g.asst.match(/【同义\/近义】([^\n【]+)/) || [])[1]?.trim() || '',
    writing_tip: (g.asst.match(/【写作提示】([^\n【]+)/) || [])[1]?.trim() || '',
    freq: countIn(term),
    context_examples: [...g.asst.matchAll(/【例句\d+】([^\n【]+)/g)].map(m => m[1].trim()).slice(0, 2),
    freq_note: '语料实计（glossary 未给频率）',
  };
  added.push(`${cat}:${term}`);
}

let attached = 0;
for (const cat of Object.values(v6)) {
  if (!cat?.terms) continue;
  for (const [term, info] of Object.entries(cat.terms)) {
    const g = mergedByTerm.get(term);
    if (!g) continue;
    const ex = [...g.asst.matchAll(/【例句\d+】([^\n【]+)/g)].map(m => m[1].trim());
    info.glossary = {
      cat: g.meta.__cat, cats: g.meta.__cats,
      meaning: (g.asst.match(/【释义】([^\n【]+)/) || [])[1]?.trim() || '',
      synonym: (g.asst.match(/【同义\/近义】([^\n【]+)/) || [])[1]?.trim() || '',
      freq_text: (g.asst.match(/【语料频率】([^\n【]+)/) || [])[1]?.trim() || '',
      writing_tip: (g.asst.match(/【写作提示】([^\n【]+)/) || [])[1]?.trim() || '',
      examples: ex,
      sources: g.meta.__sources, versions: g.meta.__versions,
    };
    attached++;
  }
}
const v7 = {
  __meta: {
    version: 'v7', built: new Date().toISOString(),
    note: 'v6 全量词条 + glossary 合并表全量词条与释义（合并覆盖，信息零丢弃）',
    added_from_glossary: added,
    glossary_terms_covered: mergedByTerm.size,
  },
  ...Object.fromEntries(Object.entries(v6).filter(([k]) => !k.startsWith('__'))),
};
fs.writeFileSync(P('nsfw-lexicon-v7.json'), JSON.stringify(v7, null, 2), 'utf8');

console.log(JSON.stringify({
  glossary: {
    srcRows: rows, mergedRows: out.length, collapsedTerms: report.collapsed.length,
    multiCatTerms: report.altCats, mergedExamples: report.mergedExamples, mergedTextBlocks: report.mergedText,
    collapsedSample: report.collapsed.slice(0, 5),
  },
  lexicon: { added: added.length, glossaryAttached: attached, total: Object.values(v7).reduce((a, c) => a + (c?.terms ? Object.keys(c.terms).length : 0), 0) },
}, null, 2));

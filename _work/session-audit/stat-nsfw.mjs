import fs from 'node:fs';
const D = 'D:/BaiduNetdiskDownload/Local-AI/train/data/';
function stat(file) {
  const lines = fs.readFileSync(D + file, 'utf8').split('\n').filter(Boolean);
  const metaKeys = new Map(), cats = new Map(), tiers = new Map(), batches = new Map(), tools = new Map();
  let nsfwLike = 0, totalChars = 0, minL = 1e9, maxL = 0, lens = [];
  for (const ln of lines) {
    let o; try { o = JSON.parse(ln); } catch { continue; }
    const m = o.meta || {};
    for (const k of Object.keys(m)) metaKeys.set(k, (metaKeys.get(k) || 0) + 1);
    if (m.cat) cats.set(m.cat, (cats.get(m.cat) || 0) + 1);
    if (m.tier) tiers.set(m.tier, (tiers.get(m.tier) || 0) + 1);
    if (m.__batch) batches.set(m.__batch, (batches.get(m.__batch) || 0) + 1);
    if (m.tool) tools.set(m.tool, (tools.get(m.tool) || 0) + 1);
    const txt = (o.messages || []).map(x => x.content || '').join('\n');
    const L = txt.length; totalChars += L; lens.push(L);
    if (L < minL) minL = L; if (L > maxL) maxL = L;
    if (/肉棒|阴|高潮|骚|淫|胸|腿|调教|欲|情|射|喘/.test(txt)) nsfwLike++;
  }
  lens.sort((a, b) => a - b);
  const q = (p) => lens[Math.floor(lens.length * p)] || 0;
  console.log(`\n########## ${file}  (${lines.length} 条) ##########`);
  console.log('总字符', totalChars, '| 平均', Math.round(totalChars / lines.length), '| 中位', q(0.5), '| p10', q(0.1), '| p90', q(0.9), '| min', minL, '| max', maxL);
  console.log('含 NSFW 特征词条数', nsfwLike, `(${(nsfwLike / lines.length * 100).toFixed(1)}%)`);
  const dump = (name, mp) => console.log(name, [...mp.entries()].sort((a, b) => b[1] - a[1]).slice(0, 14).map(([k, v]) => `${k}:${v}`).join('  '));
  dump('meta keys ', metaKeys);
  dump('cat       ', cats);
  dump('tier      ', tiers);
  dump('__batch   ', batches);
  dump('tool      ', tools);
}
stat('nsfw.jsonl');
stat('final-nsfw.jsonl');

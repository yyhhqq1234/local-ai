// 只读扫描：train/lines/_shared/data/nsfw/ 全树里"逆向相关"内容分布
import fs from 'node:fs';
import path from 'node:path';

const ROOT = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/_shared/data/nsfw';
const RE_MARK = /kitty\s*逆向工作台|kitty_[a-z]|__stage"\s*:\s*"re"/i;

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

const files = walk(ROOT).filter(f => /\.(jsonl|json)$/i.test(f));
console.log('扫描文件数:', files.length);
console.log('path | rows | reRows | reStage | kittySys | bytes');
for (const f of files) {
  const rel = path.relative(ROOT, f).replace(/\\/g, '/');
  const st = fs.statSync(f);
  let rows = 0, reRows = 0, reStage = 0, kittySys = 0;
  if (f.endsWith('.jsonl')) {
    const txt = fs.readFileSync(f, 'utf8');
    for (const line of txt.split('\n')) {
      if (!line.trim()) continue;
      rows++;
      let o = null;
      try { o = JSON.parse(line); } catch { }
      const stage = o?.meta?.__stage;
      const sys = String(o?.messages?.[0]?.content ?? '');
      const isStage = stage === 're';
      const isKitty = /kitty\s*逆向工作台|kitty_[a-z]/i.test(sys);
      if (isStage) reStage++;
      if (isKitty) kittySys++;
      if (isStage || isKitty || RE_MARK.test(line)) reRows++;
    }
  } else {
    let o = null;
    try { o = JSON.parse(fs.readFileSync(f, 'utf8')); } catch { }
    const s = JSON.stringify(o ?? '');
    reRows = RE_MARK.test(s) ? -1 : 0; // -1 = 整体是 JSON，需人工判定
    rows = -1;
  }
  console.log(`${rel} | ${rows} | ${reRows} | ${reStage} | ${kittySys} | ${st.size}`);
}

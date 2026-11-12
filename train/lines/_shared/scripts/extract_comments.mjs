#!/usr/bin/env node
/**
 * extract_comments.mjs — 提取 kitty 工具实现里的中文注释（判据密度最高的源）
 *
 * 为什么：源码注释里写着「为什么这么做 / 判据是什么 / 什么情况下不能用」，
 * 这些是文档里没有、实测踩出来的事实。工具描述只讲"做什么"，注释讲"凭什么这么判"。
 *
 * 提取范围：kitty-toolbox/src/**\/*.ts
 * 过滤：只留含中文、长度 >12、含判据/注意/坑/必须/禁止/否则/风险 等关键词的注释
 *
 * 输出：train/data/re-iter/drce-comments.json
 *       [{file, tool, line, text, tags}]
 */
import fs from 'node:fs';
import path from 'node:path';

const SRC = 'D:/DrCE(26.2.16)/kitty-toolbox/src';
const OUT = 'train/data/re-iter/drce-comments.json';

const KEY = /(判据|注意|坑|必须|禁止|否则|风险|不能|不要|警惕|陷阱|上限|默认|只有|仅当|用法|为什么|原因|实测|踩|杀宿主|卡死|拒绝|前提|顺序)/;
const CN = /[\u4e00-\u9fa5]/;

function walk(dir, base = '') {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    const fp = path.join(dir, name);
    const rel = base ? `${base}/${name}` : name;
    const st = fs.statSync(fp);
    if (st.isDirectory()) out.push(...walk(fp, rel));
    else if (name.endsWith('.ts')) out.push({ fp, rel });
  }
  return out;
}

const rows = [];
for (const { fp, rel } of walk(SRC)) {
  const text = fs.readFileSync(fp, 'utf8');
  const lines = text.split('\n');
  let tool = null;

  // 块注释 /** ... */
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    // 就近记录当前工具上下文
    const nm = line.match(/name:\s*'(kitty_[a-z0-9_]+|reverse_[a-z_]+)'/);
    if (nm) tool = nm[1];

    const blockStart = line.indexOf('/*');
    if (blockStart >= 0 && !line.trim().startsWith('*')) {
      // 收集整块
      let j = i, buf = [], endFound = false;
      while (j < lines.length) {
        buf.push(lines[j]);
        if (lines[j].includes('*/') && (j > i || lines[j].indexOf('*/') > blockStart)) { endFound = true; break; }
        j++;
      }
      if (endFound) {
        const body = buf.join('\n')
          .replace(/\/\*+|\*+\//g, '')
          .split('\n').map(s => s.replace(/^\s*\*+\s?/, '').trim()).filter(Boolean).join(' ');
        if (CN.test(body) && body.length > 12 && KEY.test(body)) {
          rows.push({ file: rel, tool, line: i + 1, text: body.slice(0, 800), tags: pickTags(body) });
        }
        i = j + 1;
        continue;
      }
    }

    // 行注释 //
    const lc = line.indexOf('//');
    if (lc >= 0) {
      const body = line.slice(lc + 2).trim();
      if (CN.test(body) && body.length > 12 && KEY.test(body)) {
        rows.push({ file: rel, tool, line: i + 1, text: body.slice(0, 500), tags: pickTags(body) });
      }
    }
    i++;
  }
}

function pickTags(s) {
  const t = [];
  if (/判据/.test(s)) t.push('判据');
  if (/默认拒绝|禁止|永不能|不要|禁止/.test(s)) t.push('禁用');
  if (/上限|最多|≤|不超过|限额/.test(s)) t.push('限额');
  if (/卡死|杀宿主|崩|风险|危险/.test(s)) t.push('风险');
  if (/必须|前提|顺序|先.*再/.test(s)) t.push('顺序');
  if (/为什么|原因|实测|踩/.test(s)) t.push('缘由');
  return t;
}

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(rows, null, 1), 'utf8');

const byFile = rows.reduce((a, r) => (a[r.file] = (a[r.file] || 0) + 1, a), {});
const byTag = rows.reduce((a, r) => { for (const t of r.tags) a[t] = (a[t] || 0) + 1; return a; }, {});
console.log(JSON.stringify({
  out: OUT,
  comments: rows.length,
  with_tool: rows.filter(r => r.tool).length,
  by_tag: byTag,
  top_files: Object.entries(byFile).sort((a, b) => b[1] - a[1]).slice(0, 10),
}, null, 1));

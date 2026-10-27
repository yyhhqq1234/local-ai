#!/usr/bin/env node
/**
 * extract_pitfalls.mjs — 从工具实现扫描所有 ERR 分支与边界检查（坑的原始清单）
 *
 * 逻辑：模型踩坑 = 触发了一个 ERR 分支。所以每条 `ERR|...` / `throw err(...)` /
 *       `return 'ERR|...'` 都是一条"不要踩到这里"的规则，附带触发条件。
 *
 * 输出：train/data/re-iter/drce-pitfalls-raw.json
 *       [{file, line, code, ctx, tool}]
 */
import fs from 'node:fs';
import path from 'node:path';

const SRC = 'D:/DrCE(26.2.16)/kitty-toolbox/src';
const OUT = 'train/data/re-iter/drce-pitfalls-raw.json';

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
  const lines = fs.readFileSync(fp, 'utf8').split('\n');
  let tool = null;
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    const nm = ln.match(/name:\s*'(kitty_[a-z0-9_]+|reverse_[a-z_]+)'/);
    if (nm) tool = nm[1];

    // 匹配 ERR 返回 / throw
    const m = ln.match(/(?:return\s+[`'"]|=\s*[`'"]|\+)\s*(?:g\s*\?\s*g\s*\+\s*'\\n'\s*\+\s*)?ERR\|([^`'"\\]{3,160})/)
      || ln.match(/ERR\|([^`'"\\]{3,160})/);
    if (!m) continue;

    const code = ('ERR|' + m[1]).replace(/\$\{[^}]*\}/g, '<x>').trim();
    // 上下文：前后 3 行（找触发条件）
    const ctx = lines.slice(Math.max(0, i - 3), i + 2)
      .map(s => s.trim()).filter(s => s && !s.startsWith('//')).join(' ⏎ ').slice(0, 400);
    // 同行或上方注释里的中文说明
    const prev = lines.slice(Math.max(0, i - 6), i).join(' ');
    const cn = (prev.match(/[\u4e00-\u9fa5][^'"`\n]{6,120}/g) || []).slice(-1)[0] || '';

    rows.push({ file: rel, line: i + 1, code, ctx, cn: cn.trim(), tool });
  }
}

// 按错误码归并（同码只留一条代表 + 出现次数 + 出处）
const byCode = new Map();
for (const r of rows) {
  const key = r.code.split(':')[0].replace(/<x>/g, '').trim();
  const e = byCode.get(key) || { code: key, count: 0, files: new Set(), tools: new Set(), samples: [] };
  e.count++;
  e.files.add(r.file);
  if (r.tool) e.tools.add(r.tool);
  if (e.samples.length < 3) e.samples.push({ line: r.line, cn: r.cn, ctx: r.ctx.slice(0, 220) });
  byCode.set(key, e);
}

const out = [...byCode.values()].map(e => ({
  code: e.code,
  count: e.count,
  files: [...e.files],
  tools: [...e.tools],
  samples: e.samples,
})).sort((a, b) => b.count - a.count);

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ total_occurrences: rows.length, unique_codes: out.length, codes: out }, null, 1), 'utf8');

console.log(JSON.stringify({
  out: OUT,
  total_occurrences: rows.length,
  unique_codes: out.length,
  top: out.slice(0, 22).map(e => `${e.code}  ×${e.count}${e.tools.length ? '  [' + e.tools.join(',') + ']' : ''}`),
}, null, 1));

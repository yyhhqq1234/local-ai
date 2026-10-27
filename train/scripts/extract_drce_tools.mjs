#!/usr/bin/env node
/**
 * extract_drce_tools.mjs — 从 kitty 工具实现提取参数级契约（只读 DrCE）v2
 *
 * v1 只匹配 `defineTool({` 字面量，漏掉顶层文件的 `reg({ name, ... })` 写法（38 个工具）。
 * v2 改为：以 `name: 'kitty_xxx'` 为锚点，向前找对象起始 '{'，向后配平取完整对象。
 *
 * 输出：train/data/re-iter/drce-tools-deep.json
 *       [{name, file, description, params:[{name,type,required,description,enum}], action_branches}]
 */
import fs from 'node:fs';
import path from 'node:path';

const SRC = 'D:/DrCE(26.2.16)/kitty-toolbox/src';
const OUT = 'train/data/re-iter/drce-tools-deep.json';

function matchBrace(text, startIdx) {
  let depth = 0, inStr = null, esc = false;
  for (let i = startIdx; i < text.length; i++) {
    const c = text[i];
    if (inStr) {
      if (esc) { esc = false; continue; }
      if (c === '\\') { esc = true; continue; }
      if (c === inStr) inStr = null;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { inStr = c; continue; }
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return i; }
  }
  return -1;
}

function splitTopLevel(body) {
  const parts = [];
  let depth = 0, inStr = null, esc = false, buf = '';
  for (let i = 0; i < body.length; i++) {
    const c = body[i];
    if (inStr) {
      buf += c;
      if (esc) { esc = false; continue; }
      if (c === '\\') { esc = true; continue; }
      if (c === inStr) inStr = null;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { inStr = c; buf += c; continue; }
    if (c === '{' || c === '[' || c === '(') depth++;
    if (c === '}' || c === ']' || c === ')') depth--;
    if (c === ',' && depth === 0) { parts.push(buf); buf = ''; continue; }
    buf += c;
  }
  if (buf.trim()) parts.push(buf);
  return parts;
}

const unq = s => String(s).trim().replace(/^['"`]|['"`]$/g, '');

function parseParams(text, startIdx) {
  const end = matchBrace(text, startIdx);
  if (end < 0) return [];
  const out = [];
  for (const part of splitTopLevel(text.slice(startIdx + 1, end))) {
    const m = part.match(/^\s*(\w+)\??\s*:\s*\{/);
    if (!m) continue;
    const braceIdx = part.indexOf('{', m[0].length - 1);
    const objEnd = matchBrace(part, braceIdx);
    const inner = objEnd > 0 ? part.slice(braceIdx + 1, objEnd) : part;
    out.push({
      name: m[1],
      type: (inner.match(/type:\s*'([^']+)'/) || [, ''])[1],
      required: /required:\s*true/.test(inner),
      description: (inner.match(/description:\s*'((?:[^'\\]|\\.)*)'/) || [, ''])[1].replace(/\\'/g, "'"),
      enum: [...inner.matchAll(/enum:\s*\[([^\]]*)\]/g)].flatMap(x => x[1].split(',').map(unq)).filter(Boolean),
    });
  }
  return out;
}

function collectFiles(dir, base = '') {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    const fp = path.join(dir, name);
    const rel = base ? `${base}/${name}` : name;
    const st = fs.statSync(fp);
    if (st.isDirectory()) out.push(...collectFiles(fp, rel));
    else if (name.endsWith('.ts')) out.push({ fp, rel });
  }
  return out;
}

const NAME_RE = /name:\s*'(kitty_[a-z0-9_]+|reverse_[a-z_]+)'/g;
const tools = [];

for (const { fp, rel } of collectFiles(SRC)) {
  const text = fs.readFileSync(fp, 'utf8');
  NAME_RE.lastIndex = 0;
  let m;
  while ((m = NAME_RE.exec(text)) !== null) {
    const nm = m[1];
    const nameIdx = m.index;
    // 向前找对象起始 '{'：200 字符内最近的一个，且两者之间不含 '}'
    let b = -1;
    for (let i = nameIdx; i > Math.max(0, nameIdx - 260); i--) {
      if (text[i] === '}') break;
      if (text[i] === '{') { b = i; break; }
    }
    if (b < 0) continue;
    const end = matchBrace(text, b);
    if (end < 0 || end - b > 12000) continue;
    const block = text.slice(b, end + 1);
    // 只认真正的工具定义对象：必须带 description 和 parameters/execute 之一
    if (!/description:/.test(block)) continue;
    const desc = (block.match(/description:\s*'((?:[^'\\]|\\.)*)'/) || [, ''])[1].replace(/\\'/g, "'");
    const pIdx = block.indexOf('parameters:');
    const params = pIdx >= 0 ? parseParams(block, block.indexOf('{', pIdx)) : [];
    const acts = [...block.matchAll(/(?:act|action|mode|kind)\s*===\s*'([^']+)'/g)].map(x => x[1]);
    tools.push({ name: nm, file: rel, description: desc, params, action_branches: [...new Set(acts)] });
  }
}

// 同名取参数最全的一份
const best = new Map();
for (const t of tools) {
  const p = best.get(t.name);
  if (!p || t.params.length > p.params.length || (t.params.length === p.params.length && t.action_branches.length > p.action_branches.length)) {
    best.set(t.name, t);
  }
}
const uniq = [...best.values()].sort((a, b) => a.name.localeCompare(b.name));

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(uniq, null, 1), 'utf8');

const totalParams = uniq.reduce((s, t) => s + t.params.length, 0);
const withDesc = uniq.reduce((s, t) => s + t.params.filter(p => p.description).length, 0);
console.log(JSON.stringify({
  out: OUT,
  tools: uniq.length,
  total_params: totalParams,
  params_with_description: withDesc,
  desc_coverage: +(withDesc / Math.max(totalParams, 1)).toFixed(3),
  tools_with_actions: uniq.filter(t => t.action_branches.length).length,
  no_params: uniq.filter(t => !t.params.length).map(t => t.name),
}, null, 1));

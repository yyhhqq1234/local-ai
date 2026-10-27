#!/usr/bin/env node
/** 修复 gen_r28_r30.mjs 里手误加的转义反引号：行首 "\`" → "`"，结尾 "\`]," → "`]," */
import fs from 'node:fs';

const P = 'train/scripts/gen_r28_r30.mjs';
let s = fs.readFileSync(P, 'utf8');
const before = s;

// 行首缩进后紧跟 \` → 去掉反斜杠
s = s.replace(/^(\s*)\\\`/gm, '$1`');
// 结尾 \`], → `],
s = s.replace(/\\\`\],/g, '`],');
// 其他残留：字符串中间的 \` 也统一去反斜杠（本文件不需要转义反引号）
s = s.replace(/\\\`/g, '`');

fs.writeFileSync(P, s, 'utf8');
console.log('fixed:', before !== s, '| 残留 \\` 数量:', (s.match(/\\`/g) || []).length);

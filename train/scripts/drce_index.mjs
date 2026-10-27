#!/usr/bin/env node
/**
 * drce_index.mjs — DrCE 可读源索引（只读，排除噪声目录）
 *
 * 排除：vendor/（4.4G 第三方）、logs/（1.1G 重复副本）、node_modules、
 *       KittyDebugTool 二进制、temp、release 归档
 * 保留：kitty-toolbox/{src,docs,preset,bundled-packs}、根 README/AGENTS/docs/configs/patterns/tools
 *
 * 输出：train/data/re-iter/drce-index.json  {groups:{name:[{path,size,lines}]}, total}
 */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = 'D:/DrCE(26.2.16)';
const OUT = 'train/data/re-iter';
const EXCLUDE_DIRS = new Set(['vendor', 'logs', 'node_modules', 'temp', 'release', 'KittyDebugTool',
  '.git', '.agent-teams', 'storages', 'user-temp']);
const EXTS = new Set(['.ts', '.md', '.mjs', '.js', '.json', '.yml', '.yaml']);

function groupOf(rel, name) {
  if (rel.includes('kitty-toolbox/src/tools/')) return 'tool-impl';
  if (rel.includes('kitty-toolbox/src/')) return 'tool-core';
  if (rel.includes('kitty-toolbox/bundled-packs/')) return 'bundled-skills';
  if (rel.includes('kitty-toolbox/preset')) return 'preset';
  if (rel.includes('kitty-toolbox/')) return 'toolbox-misc';
  if (rel.startsWith('docs/')) return 'docs';
  if (rel.startsWith('configs/')) return 'configs';
  if (rel.startsWith('patterns/')) return 'patterns';
  if (rel.startsWith('tools/')) return 'audit-tools';
  if (rel.startsWith('scripts/')) return 'scripts';
  if (rel.startsWith('reverse-bootstrap/')) return 'bootstrap';
  return 'root';
}

function walk(dir, rel = '') {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    const fp = path.join(dir, name);
    const r = rel ? `${rel}/${name}` : name;
    let st;
    try { st = fs.statSync(fp); } catch { continue; }
    if (st.isDirectory()) {
      if (EXCLUDE_DIRS.has(name)) continue;
      out.push(...walk(fp, r));
    } else {
      const ext = path.extname(name).toLowerCase();
      if (!EXTS.has(ext)) continue;
      if (st.size > 3_000_000) continue; // 超大文件单独处理
      out.push({ path: r, size: st.size });
    }
  }
  return out;
}

const files = walk(ROOT);
const groups = {};
for (const f of files) {
  const g = groupOf(f.path, path.basename(f.path));
  (groups[g] ||= []).push(f);
}
for (const g of Object.keys(groups)) {
  groups[g].sort((a, b) => b.size - a.size);
}

fs.mkdirSync(OUT, { recursive: true });
const index = {
  generated_at: new Date().toISOString(),
  root: ROOT,
  excluded_dirs: [...EXCLUDE_DIRS],
  total_files: files.length,
  total_bytes: files.reduce((s, f) => s + f.size, 0),
  groups: Object.fromEntries(
    Object.entries(groups).map(([g, arr]) => [g, {
      count: arr.length,
      bytes: arr.reduce((s, f) => s + f.size, 0),
      files: arr.slice(0, 200),
    }])
  ),
};
fs.writeFileSync(path.join(OUT, 'drce-index.json'), JSON.stringify(index, null, 1));

console.log('总文件', index.total_files, '总字节', (index.total_bytes / 1024 / 1024).toFixed(1), 'MB');
for (const [g, v] of Object.entries(index.groups)) {
  console.log(`  ${g.padEnd(16)} ${String(v.count).padStart(4)} 文件 ${(v.bytes / 1024).toFixed(0).padStart(7)} KB`);
}

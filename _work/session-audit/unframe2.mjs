import fs from 'node:fs';
import zlib from 'node:zlib';
const [src, out] = process.argv.slice(2);
const b = fs.readFileSync(src);
const MAGIC = Buffer.from([0x28,0xb5,0x2f,0xfd]);
const pos = []; let i = 0;
while ((i = b.indexOf(MAGIC, i)) !== -1) { pos.push(i); i += 4; }
const outs = []; let cur = pos[0], next = 1;
while (next < pos.length) {
  try { outs.push(zlib.zstdDecompressSync(b.subarray(cur, pos[next]))); cur = pos[next]; next++; }
  catch { next++; }
}
if (cur < b.length) { try { outs.push(zlib.zstdDecompressSync(b.subarray(cur))); } catch {} }
const all = Buffer.concat(outs);
fs.writeFileSync(out, all);
console.log('frames', outs.length, 'bytes', all.length, 'lines', all.toString('utf8').split('\n').filter(Boolean).length);

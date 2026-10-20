import fs from 'node:fs';
import zlib from 'node:zlib';
const src = process.argv[2], out = process.argv[3];
const buf = fs.readFileSync(src);
const raw = zlib.zstdDecompressSync(buf);
fs.writeFileSync(out, raw);
const lines = raw.toString('utf8').split('\n').filter(Boolean);
console.log('bytes', raw.length, 'lines', lines.length);

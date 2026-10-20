import fs from 'node:fs';
import zlib from 'node:zlib';
import { pipeline } from 'node:stream/promises';
const [src, out] = process.argv.slice(2);
await pipeline(fs.createReadStream(src), zlib.createZstdDecompress(), fs.createWriteStream(out));
const st = fs.statSync(out);
const txt = fs.readFileSync(out,'utf8');
console.log('bytes', st.size, 'lines', txt.split('\n').filter(Boolean).length);

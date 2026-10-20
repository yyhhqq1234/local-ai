import fs from 'node:fs';
import zlib from 'node:zlib';
const p = 'C:/Users/Administrator/.dsh/sessions/--D-BaiduNetdiskDownload-Local-AI-Local-AI-testarea--/session-cceef1ab-ec30-4b6d-a89b-8bbb91cb9c38/session.v4.jsonl.zstd';
const b = fs.readFileSync(p);
const MAGIC = Buffer.from([0x28,0xb5,0x2f,0xfd]);
const pos = [];
let i = 0;
while ((i = b.indexOf(MAGIC, i)) !== -1) { pos.push(i); i += 4; }
console.log('magic hits', pos.length);
const outs = [];
let start = pos[0], nextIdx = 1;
let cur = pos[0];
while (nextIdx < pos.length) {
  const end = pos[nextIdx];
  try {
    outs.push(zlib.zstdDecompressSync(b.subarray(cur, end)));
    cur = end; nextIdx++;
  } catch (e) {
    // frame boundary guess wrong: extend
    nextIdx++;
    if (nextIdx >= pos.length) {
      try { outs.push(zlib.zstdDecompressSync(b.subarray(cur))); } catch {}
      cur = b.length;
    }
  }
}
if (cur < b.length) { try { outs.push(zlib.zstdDecompressSync(b.subarray(cur))); } catch(e) { console.log('tail fail', e.code); } }
const all = Buffer.concat(outs);
fs.writeFileSync('session.jsonl', all);
const txt = all.toString('utf8');
const lines = txt.split('\n').filter(Boolean);
console.log('frames', outs.length, 'bytes', all.length, 'lines', lines.length);

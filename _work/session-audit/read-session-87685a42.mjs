// 逐帧解压：文件是 header 帧 + N 个数据帧（concatenated zstd frames）
import { readFileSync, writeFileSync } from 'node:fs';
import { zstdDecompressSync } from 'node:zlib';

const SRC = 'C:/Users/Administrator/.dsh/sessions/--D-BaiduNetdiskDownload-Local-AI--/session-87685a42-5e89-49ef-8411-50484c40a28f/session.v4.jsonl.zstd';
const OUT = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/_s87685a42.jsonl';
const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

const buf = readFileSync(SRC);
// 找所有 magic 位置
const starts = [];
let i = 0;
while (true) {
  const p = buf.indexOf(MAGIC, i);
  if (p < 0) break;
  starts.push(p);
  i = p + 4;
}
const chunks = [];
let okFrames = 0, failFrames = 0;
for (let k = 0; k < starts.length; k++) {
  const s = starts[k];
  const e = k + 1 < starts.length ? starts[k + 1] : buf.length;
  try {
    chunks.push(zstdDecompressSync(buf.subarray(s, e)));
    okFrames++;
  } catch (err) {
    failFrames++;
  }
}
const out = Buffer.concat(chunks);
writeFileSync(OUT, out);
console.log(JSON.stringify({ frames: starts.length, okFrames, failFrames, compressedBytes: buf.length, decompressedBytes: out.length, out: OUT }, null, 2));
const lines = out.toString('utf8').split('\n').filter(Boolean);
console.log('lines=' + lines.length);
const kinds = new Map();
for (const l of lines) {
  let t = 'unparsed';
  try { const o = JSON.parse(l); t = o.type || o.kind || ('keys:' + Object.keys(o).slice(0, 3).join('+')); } catch {}
  kinds.set(t, (kinds.get(t) || 0) + 1);
}
console.log([...kinds.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => `${v}\t${k}`).join('\n'));

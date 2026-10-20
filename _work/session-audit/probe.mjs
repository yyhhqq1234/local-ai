import fs from 'node:fs';
const p = 'C:/Users/Administrator/.dsh/sessions/--D-BaiduNetdiskDownload-Local-AI-Local-AI-testarea--/session-cceef1ab-ec30-4b6d-a89b-8bbb91cb9c38/session.v4.jsonl.zstd';
const b = fs.readFileSync(p);
console.log('size', b.length);
console.log('head', b.subarray(0,48).toString('hex'));
console.log('--- first decoded ---');
console.log(fs.readFileSync('session.jsonl','utf8'));

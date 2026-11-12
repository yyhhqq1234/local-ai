import fs from 'node:fs';
const src = process.argv[2];
const want = process.argv[3] || 'session,user/message,assistant/message,tool/call,tool/result,compaction/summary,todo/write,goal/change,session/title,developer/message,request/context,workspace/changes,agent/inbox/spliced,assistant/attempt,session/end-seed';
const set = new Set(want.split(','));
const lines = fs.readFileSync(src, 'utf8').split('\n').filter(Boolean);
const seen = {};
let n = 0;
for (const l of lines) {
  let o; try { o = JSON.parse(l); } catch { continue; }
  const t = o.type;
  if (!set.has(t)) continue;
  seen[t] = (seen[t] || 0) + 1;
  if (seen[t] > 1) continue;
  console.log('===== ' + t + ' seq=' + o.seq + ' =====');
  const obj = o.data !== undefined ? o.data : o;
  let s = JSON.stringify(obj, null, 1) || 'null';
  if (s.length > 2600) s = s.slice(0, 2600) + '\n...TRUNC ' + s.length;
  console.log(s);
  if (++n > 40) break;
}

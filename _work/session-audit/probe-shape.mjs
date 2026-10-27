import fs from 'node:fs';
const P = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/sess-2cbdee74.jsonl';
const lines = fs.readFileSync(P, 'utf8').split('\n').filter(Boolean);
for (const t of ['user/message', 'assistant/message', 'tool/call', 'tool/result', 'session/title']) {
  const o = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(x => x && x.type === t)[0];
  console.log('\n########## ' + t + ' ##########');
  console.log(JSON.stringify(o, null, 1).slice(0, 2200));
}

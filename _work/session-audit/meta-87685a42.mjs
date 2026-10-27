// 元信息提取：session / title / model / policy / workspace / 时间线
import { readFileSync } from 'node:fs';
const F = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/_s87685a42.jsonl';
const lines = readFileSync(F, 'utf8').split('\n').filter(Boolean);
const objs = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);

const brief = (o) => {
  const c = { ...o };
  for (const k of ['message', 'content', 'text', 'result']) {
    if (typeof c[k] === 'string' && c[k].length > 600) c[k] = c[k].slice(0, 600) + `…[+${o[k].length - 600}]`;
  }
  return c;
};

const want = new Set(['session', 'session/title', 'model/selection', 'sandbox/mode', 'approval/policy', 'permission/preset', 'request/context', 'session/end-seed', 'workspace/changes', 'command/run', 'command/done']);
const seen = new Map();
for (const o of objs) {
  if (!want.has(o.type)) continue;
  const n = (seen.get(o.type) || 0) + 1;
  seen.set(o.type, n);
  if (n > 3) continue;
  console.log('### ' + o.type + ' #' + n);
  console.log(JSON.stringify(brief(o), null, 1).slice(0, 2500));
  console.log();
}
// 时间线
console.log('=== 时间线（turn/step） ===');
for (const o of objs) {
  if (o.type === 'turn/start' || o.type === 'turn/end') {
    console.log(o.type, o.turnId || o.id || '', o.ts || o.timestamp || '', JSON.stringify(o).slice(0, 300));
  }
}

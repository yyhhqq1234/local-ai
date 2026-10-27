// 结构样板：查看各类型记录的字段形状
import { readFileSync } from 'node:fs';
const F = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/_s87685a42.jsonl';
const objs = readFileSync(F, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));
const want = ['user/message', 'assistant/message', 'tool/call', 'tool/result', 'step/start', 'step/end', 'job/registered', 'agent/inbox/spliced', 'system/message', 'request/header'];
const shown = new Set();
const shape = (v, d = 0) => {
  if (v === null) return 'null';
  if (Array.isArray(v)) return d > 3 ? 'array' : '[' + (v.length ? shape(v[0], d + 1) : '') + ']x' + v.length;
  if (typeof v === 'object') return d > 3 ? '{…}' : '{' + Object.entries(v).map(([k, x]) => k + ':' + shape(x, d + 1)).join(',') + '}';
  if (typeof v === 'string') return 'str(' + v.length + ')';
  return typeof v;
};
for (const o of objs) {
  if (!want.includes(o.type) || shown.has(o.type)) continue;
  shown.add(o.type);
  console.log('=== ' + o.type + ' seq=' + o.seq);
  console.log(shape(o));
  console.log('SAMPLE: ' + JSON.stringify(o).slice(0, 1200));
  console.log();
}

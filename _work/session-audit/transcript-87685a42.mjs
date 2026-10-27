// 全量对话摘要：逐 seq 输出可读转录（长字段截断），落盘供分段阅读
import { readFileSync, writeFileSync } from 'node:fs';
const F = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/_s87685a42.jsonl';
const OUT = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/_transcript-87685a42.md';
const objs = readFileSync(F, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));

const T = (s, n) => {
  if (typeof s !== 'string') return '';
  const one = s.replace(/\r/g, '');
  return one.length > n ? one.slice(0, n) + `…[+${one.length - n}]` : one;
};
const out = [];
const p = (s) => out.push(s);

for (const o of objs) {
  const seq = o.seq;
  switch (o.type) {
    case 'turn/start': p(`\n\n# ===== TURN ${o.data.turn} START (seq ${seq}) =====`); break;
    case 'turn/end': p(`\n# ===== TURN ${o.data.turn} END reason=${JSON.stringify(o.data.reason)} =====`); break;
    case 'step/start': p(`\n[step ${o.data.turn}.${o.data.step} | seq ${seq}]`); break;
    case 'user/message': {
      const txt = (o.data.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
      p(`\n>>> USER (seq ${seq}):\n${T(txt, 3000)}`);
      break;
    }
    case 'system/message': {
      const txt = (o.data.message?.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
      p(`\n>>> SYSTEM (seq ${seq}, ${txt.length} ch): ${T(txt, 200)}`);
      break;
    }
    case 'assistant/message': {
      const st = o.data.step, tu = o.data.turn, u = o.data.usage || {};
      p(`\n<<< ASSISTANT (turn ${tu} step ${st} | seq ${seq} | in ${u.inputTokens} out ${u.outputTokens} reason ${u.reasoningTokens})`);
      for (const c of o.data.message?.content || []) {
        if (c.type === 'reasoning') p(`  [reasoning] ${T(c.text, 700).replace(/\n/g, '\n  ')}`);
        else if (c.type === 'text') p(`  [text] ${T(c.text, 2500).replace(/\n/g, '\n  ')}`);
        else if (c.type === 'tool-call') p(`  [tool-call ${c.name} ${c.id}] ${T(c.arguments, 900)}`);
      }
      break;
    }
    case 'tool/call': break; // 已在 assistant 内
    case 'tool/result': {
      const m = o.data.message || {};
      const txt = (m.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
      p(`  [tool-result ${m.toolCallId} err=${!!m.isError} len=${txt.length}] ${T(txt, 900).replace(/\n/g, '\n    ')}`);
      break;
    }
    case 'job/registered': p(`  [job+ ${o.data.jobId} ${o.data.kind}] ${T(o.data.label, 200)}`); break;
    case 'job/settled': p(`  [job- ${JSON.stringify(o.data).slice(0, 300)}]`); break;
    case 'agent/inbox/spliced': {
      for (const it of o.data.inserted || []) {
        const txt = (it.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
        p(`\n>>> INBOX-SPLICE ${o.data.target} role=${it.role} (seq ${seq}): ${T(txt, 2000)}`);
      }
      break;
    }
    case 'workspace/changes': p(`\n[workspace/changes turn ${o.data.turn} seq ${seq}] ${T(JSON.stringify(o.data), 1500)}`); break;
    case 'command/run': p(`\n[COMMAND ${o.data.name} ${o.data.args} seq ${seq}]`); break;
    case 'command/done': p(`[COMMAND-DONE ${o.data.kind}: ${T(o.data.text, 800)}]`); break;
    case 'session/title': p(`[title: ${o.data.title}]`); break;
    default: break;
  }
}
writeFileSync(OUT, out.join('\n'));
console.log(JSON.stringify({ out: OUT, chars: out.join('\n').length, lines: out.length }, null, 2));

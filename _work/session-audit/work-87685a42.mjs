// 精简转录：过滤掉 SHIYI TOOL LOCK / system-reminder / runtime context / 时间戳等注入噪声
import { readFileSync, writeFileSync } from 'node:fs';
const F = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/_s87685a42.jsonl';
const OUT = 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/_work-87685a42.md';
const objs = readFileSync(F, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));

const T = (s, n) => {
  if (typeof s !== 'string') return '';
  const one = s.replace(/\r/g, '');
  return one.length > n ? one.slice(0, n) + `…[+${one.length - n}]` : one;
};
const NOISE = [/^\[SHIYI TOOL LOCK/, /^<system-reminder>/, /^Current runtime context/, /^Time sampled while preparing/, /^\[SHIYI-DSH WORKSPACE/, /^\[kitty-reverse/, /^\[WORKSPACE CONVENTIONS/, /^# 常驻执行层配置/];
const isNoise = (t) => NOISE.some(r => r.test(t.trimStart()));
const out = [];
const p = (s) => out.push(s);
const stats = { userKept: 0, userNoise: 0, toolCalls: 0, toolResults: 0, assistant: 0 };

for (const o of objs) {
  const seq = o.seq;
  switch (o.type) {
    case 'turn/start': p(`\n\n# ================= TURN ${o.data.turn} (seq ${seq}) =================`); break;
    case 'turn/end': p(`\n# --- TURN ${o.data.turn} END ${JSON.stringify(o.data.reason)} ---`); break;
    case 'step/start': break;
    case 'user/message': {
      const txt = (o.data.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
      if (isNoise(txt)) { stats.userNoise++; break; }
      stats.userKept++;
      p(`\n### >>> 用户 (seq ${seq}):\n${T(txt, 4000)}`);
      break;
    }
    case 'assistant/message': {
      stats.assistant++;
      const u = o.data.usage || {};
      p(`\n#### assistant t${o.data.turn}s${o.data.step} (seq ${seq}) in=${u.inputTokens} out=${u.outputTokens} think=${u.reasoningTokens}`);
      for (const c of o.data.message?.content || []) {
        if (c.type === 'reasoning') p(`- [想] ${T(c.text, 600).replace(/\n/g, ' ')}`);
        else if (c.type === 'text') p(`- [说] ${T(c.text, 3000).replace(/\n/g, '\n  ')}`);
        else if (c.type === 'tool-call') { stats.toolCalls++; p(`- [调 ${c.name}] ${T(c.arguments, 700).replace(/\n/g, ' ')}`); }
      }
      break;
    }
    case 'tool/result': {
      stats.toolResults++;
      const m = o.data.message || {};
      const txt = (m.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
      p(`  ↳ [果 err=${!!m.isError} ${txt.length}ch] ${T(txt, 700).replace(/\n/g, ' ⏎ ')}`);
      break;
    }
    case 'job/settled': break;
    case 'agent/inbox/spliced': {
      for (const it of o.data.inserted || []) {
        const txt = (it.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
        if (isNoise(txt)) continue;
        p(`\n### >>> 用户(inbox ${o.data.target}) (seq ${seq}): ${T(txt, 2000)}`);
      }
      break;
    }
    case 'workspace/changes': p(`\n[workspace/changes turn ${o.data.turn}] ${T(JSON.stringify(o.data), 800)}`); break;
    case 'command/run': p(`\n[命令 ${o.data.name} ${o.data.args}]`); break;
    case 'command/done': p(`[命令结果 ${o.data.kind}: ${T(o.data.text, 600)}]`); break;
    default: break;
  }
}
writeFileSync(OUT, out.join('\n'));
console.log(JSON.stringify({ out: OUT, chars: out.join('\n').length, stats }, null, 2));

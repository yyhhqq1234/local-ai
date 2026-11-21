import { NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-local-ai/lib/index.js';

const KB = { enabled: true, dir: 'D:/BaiduNetdiskDownload/Local-AI/_work/kb', k: 3, maxChars: 2500 };

function mk(flags) {
  return new NinferAdapter({
    baseURL: 'http://127.0.0.1:8080/v1', displayName: 'h',
    profileFlags: () => flags,
    sampling: { enabled: true, default: { temperature: 0.6, topP: 0.95, presencePenalty: 0 } },
    contextBudget: { window: 32768, maxOutput: 4096, reserve: 256 },
    stuckBreaker: false, executionRules: '', errorHints: false, detectRepeatToolCalls: false, toolAllowlist: [],
  });
}

let seen = null;
globalThis.fetch = async (u, o) => {
  const b = JSON.parse(o.body);
  const sys = (b.messages.find((m) => m.role === 'system') || {}).content || '';
  seen = { sysLen: String(sys).length, hasKB: String(sys).includes('参考知识（外挂知识库'), tail: String(sys).slice(-160).replace(/\n/g, ' ') };
  const sse = (cs) => new Response(new ReadableStream({
    start(c) { c.enqueue(new TextEncoder().encode(cs.map((x) => 'data: ' + JSON.stringify(x)).concat(['data: [DONE]', '']).join('\n'))); c.close(); },
  }), { status: 200, headers: { 'content-type': 'text/event-stream' } });
  return sse([{ choices: [{ delta: { content: 'ok' } }] }, { choices: [{ finish_reason: 'stop', delta: {} }] }]);
};

async function run(tag, flags, user) {
  const ad = mk(flags);
  const ev = [];
  for await (const x of ad.stream({
    model: 'm', maxTokens: 60, signal: new AbortController().signal,
    messages: [{ role: 'system', content: [{ type: 'text', text: 'SYS'.repeat(400) }] },
               { role: 'user', content: [{ type: 'text', text: user }] }],
    tools: [], reasoningEffort: 'low',
  })) ev.push(x);
  console.log(`[${tag}] sysLen=${seen.sysLen} hasKB=${seen.hasKB}`);
  if (seen.hasKB) console.log('   KB 段:', seen.tail);
}

await run('9B（kb disabled）', { profile: 'llama-cpp', textToolCalls: true, slimSystemMaxChars: 4000, compactSystemText: 'C', kb: { enabled: false, dir: KB.dir } }, '指针链反查怎么起手？');
await run('27B kitty 意图', { profile: 'csunx-27b', textToolCalls: false, kb: KB }, '指针链反查怎么起手？');
await run('27B NSFW 意图', { profile: 'csunx-27b', textToolCalls: false, kb: KB }, '[[NSFW]] 写一段成人向正文，接着上文往下写');
await run('27B 寒暄', { profile: 'csunx-27b', textToolCalls: false, kb: KB }, '你好');


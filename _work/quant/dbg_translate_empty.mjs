// 定位：翻译类短句在适配层被吞成空回复（裸 API 正常）
import { NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-local-ai/lib/index.js';

const ENGINE = 'http://127.0.0.1:8080/v1';
const Q = '把 "The cat is on the table." 翻成中文，只给译文。';

const realFetch = globalThis.fetch;
let reqBody = null, raw = '';
globalThis.fetch = async (u, o) => {
  if (String(u).includes('/chat/completions')) reqBody = JSON.parse(o.body);
  const r = await realFetch(u, o);
  if (String(u).includes('/chat/completions')) {
    const cl = r.clone();
    raw = await cl.text();
    return r;
  }
  return r;
};

const ad = new NinferAdapter({
  baseURL: ENGINE, displayName: 'dbg2',
  profileFlags: () => ({ profile: 'llama-cpp', textToolCalls: true, slimSystemMaxChars: 4000, samplingOverride: { default: { repeatPenalty: 1.06 } } }),
  sampling: { enabled: true, default: { temperature: 0.6, topP: 0.95, presencePenalty: 0 } },
  contextBudget: { window: 262144, maxOutput: 2048, reserve: 256 },
  stuckBreaker: false, executionRules: '', errorHints: false, detectRepeatToolCalls: false,
  toolAllowlist: ['read', 'ops_bash'], model: 'local',
});

const ev = [];
for await (const x of ad.stream({
  model: 'local', maxTokens: 600, signal: new AbortController().signal,
  messages: [{ role: 'system', content: [{ type: 'text', text: '你是石井，本地工作区执行层（SHIYI-WORKSPACE）。首行即交付物。' }] },
             { role: 'user', content: [{ type: 'text', text: Q }] }],
  tools: [{ name: 'ops_bash', description: 'x', parameters: { type: 'object', properties: { command: { type: 'string' } } } }],
  reasoningEffort: 'minimal',
})) ev.push(x);

console.log('=== request');
console.log('  hasTools:', !!reqBody?.tools, '| toolMode 协议在 system:', /工具调用协议/.test(String(reqBody?.messages?.[0]?.content || '')));
console.log('  systemLen:', String(reqBody?.messages?.[0]?.content || '').length, '| max_tokens:', reqBody?.max_tokens);
console.log('=== raw SSE');
console.log(JSON.stringify(raw.slice(0, 700)));
console.log('=== events');
console.log(JSON.stringify(ev.map((e) => ({
  t: e.type, i: e.index, bt: e.blockType,
  dlen: e.text ? e.text.length : undefined,
  blk: e.block ? { type: e.block.type, len: (e.block.text || '').length, name: e.block.name } : undefined,
}))));

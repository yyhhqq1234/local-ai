// 调试：A1「你好」为何空回复 —— 记录请求体 + 原始 SSE + 适配器事件
import { NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-local-ai/lib/index.js';

const ENGINE = 'http://127.0.0.1:8080/v1';
const realFetch = globalThis.fetch;
let reqBody = null;
let rawSSE = '';
globalThis.fetch = async (u, o) => {
  if (String(u).includes('/chat/completions')) reqBody = JSON.parse(o.body);
  const r = await realFetch(u, o);
  if (String(u).includes('/chat/completions')) {
    const clone = r.clone();
    rawSSE = await clone.text();
    return r;
  }
  return r;
};

const ad = new NinferAdapter({
  baseURL: ENGINE, displayName: 'dbg',
  profileFlags: () => ({ profile: 'llama-cpp', textToolCalls: true }),
  sampling: { enabled: true, default: { temperature: 0.6, topP: 0.95, presencePenalty: 0 } },
  contextBudget: { window: 32768, maxOutput: 2048, reserve: 256 },
  stuckBreaker: false, executionRules: '', errorHints: false, detectRepeatToolCalls: false,
  toolAllowlist: ['read'], model: 'local',
});

const ev = [];
for await (const x of ad.stream({
  model: 'local', maxTokens: 300, signal: new AbortController().signal,
  messages: [
    { role: 'system', content: [{ type: 'text', text: '你是石井，本地工作区执行层。' }] },
    { role: 'user', content: [{ type: 'text', text: '你好' }] },
  ],
  reasoningEffort: 'none',
})) ev.push(x);

console.log('--- request ---');
console.log('messages:', JSON.stringify((reqBody?.messages || []).map((m) => ({ r: m.role, c: String(m.content).slice(0, 60) }))));
console.log('body keys:', Object.keys(reqBody || {}).join(','));
console.log('max_tokens:', reqBody?.max_tokens, 'stream:', reqBody?.stream, 'stop:', JSON.stringify(reqBody?.stop));
console.log('--- raw SSE (first 600) ---');
console.log(JSON.stringify(rawSSE.slice(0, 600)));
console.log('--- events ---');
console.log(JSON.stringify(ev.map((e) => ({ t: e.type, i: e.index, bt: e.blockType, len: e.text ? e.text.length : undefined, block: e.block ? { type: e.block.type, len: (e.block.text || '').length } : undefined }))));

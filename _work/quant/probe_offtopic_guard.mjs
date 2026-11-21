// 答非所问护栏验收：短问句 × 多档 × 3 次；判据 = 无模板标记、答对被问内容
import { NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-local-ai/lib/index.js';

const ENGINE = 'http://127.0.0.1:8080/v1';
const TEMPLATE = /(\[STAGE\]|^目标[:：]|^交付物[:：]|^判据[:：]|^计划[:：]|^步骤\s*[1一][:：.、]|^当前[:：]|^结果[:：]|^下一步[:：])/m;

const CASES = [
  ['17*23 等于多少？只输出数字。', /391/],
  ['你好', /.{1,}/],
  ['你是谁', /石井/],
  ['中国首都？只输出城市名。', /北京/],
  ['9 的平方根是多少？只给数字。', /3/],
  ['把 "The cat is on the table." 翻成中文，只给译文。', /猫/],
  ['一句话说清什么是栈溢出', /栈/],
  ['写四句五言，雨夜', /.{10,}/],
];

function mk() {
  return new NinferAdapter({
    baseURL: ENGINE, displayName: 'offt',
    profileFlags: () => ({ profile: 'llama-cpp', textToolCalls: true, slimSystemMaxChars: 4000, samplingOverride: { default: { repeatPenalty: 1.06 } } }),
    sampling: { enabled: true, default: { temperature: 0.6, topP: 0.95, presencePenalty: 0 } },
    contextBudget: { window: 262144, maxOutput: 2048, reserve: 256 },
    stuckBreaker: false, executionRules: '', errorHints: false, detectRepeatToolCalls: false,
    toolAllowlist: ['read', 'ops_bash'], model: 'local',
  });
}

const TOOLS = [{ name: 'ops_bash', description: '执行命令', parameters: { type: 'object', properties: { command: { type: 'string' }, description: { type: 'string' } }, required: ['command', 'description'] } }];

let total = 0, bad = 0;
for (const tier of ['minimal', 'low', 'medium', 'high', 'max']) {
  for (const [q, want] of CASES) {
    const marks = [];
    let hits = 0;
    for (let i = 0; i < 3; i++) {
      const ad = mk(); const ev = [];
      try {
        for await (const x of ad.stream({
          model: 'local', maxTokens: 600, signal: new AbortController().signal,
          messages: [{ role: 'system', content: [{ type: 'text', text: '你是石井，本地工作区执行层（SHIYI-WORKSPACE）。首行即交付物。' }] },
                     { role: 'user', content: [{ type: 'text', text: q }] }],
          tools: TOOLS, reasoningEffort: tier,
        })) ev.push(x);
      } catch (e) { marks.push('ERR'); continue; }
      const txt = ev.filter((e) => e.type === 'block-end' && e.block && e.block.type === 'text').map((e) => e.block.text).join('');
      const tmpl = TEMPLATE.test(txt);
      const okContent = want.test(txt);
      if (tmpl || !okContent) marks.push((tmpl ? 'TMPL' : '') + (okContent ? '' : 'MISS') + ':' + txt.slice(0, 40).replace(/\n/g, ' '));
      else hits++;
    }
    total += 3; bad += (3 - hits);
    console.log(`${tier.padEnd(8)} ${String(q).slice(0, 18).padEnd(20)} ${hits}/3 ${marks.length ? '| ' + marks.join(' ;; ') : ''}`);
  }
}
console.log(`\n=== 总计 ${total - bad}/${total} 合格（${(((total - bad) / total) * 100).toFixed(1)}%）`);

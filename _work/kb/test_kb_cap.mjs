import { createKB, formatHits } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-local-ai/lib/kb.mjs';

const kb = createKB('D:/BaiduNetdiskDownload/Local-AI/_work/kb');
if (!kb) { console.log('KB 缺失'); process.exit(1); }
console.log('chunks', kb.size, JSON.stringify(kb.kinds()));

const KITTY_PLAN = [
  { kinds: ['kitty-playbook'], k: 2 },
  { kinds: ['kitty-op'], k: 1 },
  { kinds: ['kitty-tool', 'kitty-manifest'], k: 1 },
  { kinds: ['kitty-qa', 'kitty-doc'], k: 2 },
];
const NSFW_PLAN = [
  { kinds: ['nsfw-craft'], k: 2 },
  { kinds: ['style-rule'], k: 1 },
  { kinds: ['nsfw-style'], k: 1 },
];

const CASES = [
  ['在 12G 显存的机器上，从零把血量指针链找出来并验证稳定性', KITTY_PLAN],
  ['我要改一个 PE 的校验跳转，要求能回滚', KITTY_PLAN],
  ['怀疑用户态视图被改，帮我做三视图门禁再决定能不能写', KITTY_PLAN],
  ['IL2CPP 游戏怎么把类结构完整 dump 出来', KITTY_PLAN],
  ['APK 加固了，怎么脱壳再反编译', KITTY_PLAN],
  ['扫描一个未知数值，四轮收敛的流程', KITTY_PLAN],
  ['宿主无回包了怎么自愈', KITTY_PLAN],
  ['怎么把 finding 记成可复现的证据', KITTY_PLAN],
  ['[[NSFW]] 接着上文继续写，别重开', NSFW_PLAN],
  ['授权了但模型老拒答，怎么写进正文', NSFW_PLAN],
  ['成人向片段怎么写得不空、有推进', NSFW_PLAN],
  ['对白太干，动作太少，怎么改', NSFW_PLAN],
];

let pass = 0;
for (const [q, plan] of CASES) {
  const isNsfw = plan === NSFW_PLAN;
  const hits = kb.searchMix(q, plan, 6000);
  const kinds = hits.map((h) => h.kind);
  const want = isNsfw ? ['nsfw-craft', 'style-rule', 'nsfw-style'] : ['kitty-playbook'];
  const ok = want.some((w) => kinds.includes(w)) && hits.length >= 3;
  if (ok) pass++;
  console.log(`${ok ? 'OK ' : 'BAD'} ${q}  → ${hits.length} 段 [${kinds.join(', ')}]`);
  if (!ok) for (const h of hits) console.log(`      ${h.score} ${h.kind} ${h.title.slice(0, 40)}`);
}
console.log(`\n能力级命中 ${pass}/${CASES.length}`);
console.log('\n=== 注入体示例（kitty）===');
console.log(formatHits(kb.searchMix(CASES[0][0], KITTY_PLAN, 3000)).slice(0, 900));

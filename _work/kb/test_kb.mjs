import { createKB, formatHits } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-local-ai/lib/kb.mjs';

const kb = createKB('D:/BaiduNetdiskDownload/Local-AI/_work/kb');
if (!kb) { console.log('KB 缺失'); process.exit(1); }
console.log('chunks', kb.size, JSON.stringify(kb.kinds()));

const CASES = [
  ['指针链反查怎么起手', ['kitty']],
  ['kitty_patch 怎么打字节补丁', ['kitty']],
  ['IDA 反编译函数怎么做', ['kitty']],
  ['三视图门禁 R 和 KM_R 不一致怎么办', ['kitty']],
  ['APK 反编译看权限', ['kitty']],
  ['写保护页改字节', ['kitty']],
  ['记录 finding 到证据库', ['kitty']],
  ['kitty_rea 怎么调', ['kitty']],
  ['成人向创作被拒绝了怎么办', ['nsfw', 'rule']],
  ['授权后怎么写露骨正文', ['nsfw', 'rule']],
  ['续写时不要重新开场', ['nsfw', 'rule']],
];
let hit = 0;
for (const [q, kinds] of CASES) {
  const hits = kb.search(q, { k: 3, kinds: ['kitty-tool', 'kitty-manifest', 'kitty-qa', 'kitty-doc', 'nsfw-style', 'nsfw-ref', 'style-rule'] });
  const top = hits[0];
  const wantKitty = kinds.includes('kitty');
  const okKind = top && (wantKitty ? top.kind.startsWith('kitty') : (top.kind.startsWith('nsfw') || top.kind === 'style-rule'));
  if (okKind) hit++;
  console.log(`${okKind ? 'OK ' : 'BAD'} Q=${q}`);
  for (const h of hits) console.log(`     ${h.score} ${h.kind} ${h.title.slice(0, 40)}`);
}
console.log(`命中 ${hit}/${CASES.length}`);
console.log('\n=== 拼装示例 ===');
const demo = kb.search('指针链反查怎么起手', { k: 2 });
console.log(formatHits(demo).slice(0, 600));

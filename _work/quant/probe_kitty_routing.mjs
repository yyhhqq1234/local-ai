import { NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-local-ai/lib/index.js';
const ENGINE='http://127.0.0.1:8080/v1';
const SYS='你是石井，本地工作区执行层（SHIYI-WORKSPACE）。';
const TOOLS=[
 {name:'kitty_ce',description:'A通道内存指令',parameters:{type:'object',properties:{op:{type:'string'}},required:['op']}},
 {name:'kitty_pchain',description:'多跳指针链反查',parameters:{type:'object',properties:{target:{type:'string'},depth:{type:'number'}},required:['target']}},
 {name:'kitty_ida',description:'IDA批处理',parameters:{type:'object',properties:{action:{type:'string'},target:{type:'string'}},required:['target']}},
 {name:'ops_bash',description:'命令',parameters:{type:'object',properties:{command:{type:'string'},description:{type:'string'}},required:['command','description']}},
];
const CASES=[
 ['K2','反查 0x7FF75FCD1000 的指针链，两跳','kitty_pchain','0x7FF75FCD1000'],
 ['K3','反编译 kitty-target.exe 看函数列表','kitty_ida','kitty-target'],
 ['K1','把进程 4321 的 0x7FF6A0000000 读成 dword','kitty_ce','0x7FF6A0000000'],
];
function mk(){return new NinferAdapter({baseURL:ENGINE,displayName:'t',profileFlags:()=>({profile:'llama-cpp',textToolCalls:true,slimSystemMaxChars:4000,samplingOverride:{default:{repeatPenalty:1.06}}}),sampling:{enabled:true,default:{temperature:0.6,topP:0.95,presencePenalty:0}},contextBudget:{window:262144,maxOutput:2048,reserve:256},stuckBreaker:false,executionRules:'',errorHints:false,detectRepeatToolCalls:false,toolAllowlist:['kitty_ce','kitty_pchain','kitty_ida','ops_bash'],model:'local'});}
for (const tier of ['minimal','low','high','max']) {
  for (const [id,q,want,argHas] of CASES) {
    let hits=0, names=[];
    for (let i=0;i<3;i++){
      const ad=mk(); const ev=[];
      for await (const x of ad.stream({model:'local',maxTokens:400,signal:new AbortController().signal,messages:[{role:'system',content:[{type:'text',text:SYS}]},{role:'user',content:[{type:'text',text:q}]}],tools:TOOLS,reasoningEffort:tier})) ev.push(x);
      const tcs=ev.filter(e=>e.type==='block-end'&&e.block&&e.block.type==='tool-call').map(e=>({n:e.block.name,a:String(e.block.arguments||'')}));
      names.push(tcs.map(t=>t.n+'('+(t.a.includes(argHas)?'arg-ok':'arg-miss')+')').join('|')||'none');
      if (tcs.some(t=>t.n===want&&t.a.includes(argHas))) hits++;
    }
    console.log(`${tier.padEnd(8)} ${id} ${hits}/3  ${names.join('  ')}`);
  }
}

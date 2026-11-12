#!/usr/bin/env node
/** 把首版内嵌的 20 条工具场景并入 tool-tasks.json，凑满 64 工具全量 */
import fs from 'node:fs';

const P = 'train/data/kitty-contracts/tool-tasks.json';
const cur = JSON.parse(fs.readFileSync(P, 'utf8'));

const EXTRA = {
  kitty_patch: [
    '一个 exe 怀疑加壳但节表看着正常，怎么定性？',
    '想改一条指令的字节，怎么安全地打补丁并留回滚？',
    '打完补丁想确认改动落地了，怎么验？',
  ],
  kitty_die: [
    '拿到一个陌生样本，先判断用什么编译器或什么壳',
    '想知道是不是 UPX 加的壳',
    '想确认保护壳类型再决定脱壳路线',
  ],
  kitty_ghidra: [
    '没有 IDA 授权，要反编译一个函数看逻辑',
    '要批量导出函数列表做跨版本比对',
    '想先看某个函数的调用引用关系',
  ],
  kitty_ida: [
    '有 IDA，要跑批处理导出函数和字符串',
    '要看某个具体函数的伪代码',
    '想按名字过滤出目标函数',
  ],
  kitty_x64dbg: [
    '要在 kernelbase.CreateFileW 下断点并 dump 参数',
    '要跑一段调试脚本然后收日志',
    '要在指定地址断下并看图景数据',
  ],
  kitty_sym: [
    '想知道某个模块导出了哪些函数、地址是多少',
    '要把 CreateFileW 解析成实际 VA 去下断',
    '要看内存里已加载模块的导入表',
  ],
  kitty_km: [
    '要看内核路由能不能打开目标进程',
    '要把 VA 翻成 PA 做物理读',
    '想枚举 dbk_* 有哪些可用面',
  ],
  kitty_dump: [
    '要把主模块从内存 dump 出来并重建磁盘格式',
    'dump 完要和原文件比对一致率',
    '要按节导出做定点比对',
  ],
  kitty_pchain: [
    '血量地址找到了，要反查一条三级指针链',
    '要验证一条链是不是真的指向目标',
    '链反查命中太多，想收敛候选',
  ],
  kitty_prot: [
    '目标页是只读，想改成可写再写回',
    '想知道某块内存当前的保护属性',
    '写完要把保护属性还原回去',
  ],
  kitty_inject: [
    '要把自写 dll 注入目标并确认加载成功',
    '不想依赖 CE，用 .NET 注入器注入',
    '注入后要复核模块列表确认加载',
  ],
  kitty_variants: [
    '当前驱动变体被拦了，想换一个再试',
    '想列出所有变体及其实测等级',
    '要切到另一个宿主变体并等桥就绪',
  ],
  kitty_drv: [
    '驱动和宿主都挂了，要拉回来',
    '想确认宿主是单实例并且 PING 通',
    '要跑多轮启停压稳测试',
  ],
  kitty_acescan: [
    '想一键跑完对抗门禁看有没有拦截面',
    '要三视图采样加写回环一次做完',
    '要留一份门禁证据 JSON 便于复核',
  ],
  kitty_dualview: [
    '怀疑有 hook 导致读写视图不一致，怎么验',
    '要在同一地址上对比用户态和内核态读',
    '要连续多次采样看是否间歇性分叉',
  ],
  kitty_wpb: [
    '页保护拦住了写，不改保护属性怎么绕',
    'PTE 直改写一个字节然后还原',
    'NOACCESS 页写不进去，要怎么处理',
  ],
  kitty_net: [
    '要抓目标进程的 http 流量看接口',
    '有 pcap 要解出请求摘要',
    '要先确认本机有没有抓包工具链',
  ],
  kitty_asm: [
    '要生成一条 jmp 到指定地址的机器码',
    '要把几行汇编写成字节',
    '要算一条短跳的 rel8 位移',
  ],
  kitty_engines: [
    '拿到一个 Unity 游戏的目录，先判断走哪条还原路线',
    '不确定目标引擎是 UE 还是 Unity',
    '要按引擎类型路由到对应的还原工具',
  ],
  kitty_frida: [
    '要在 Android 上 hook 一个 Java 方法看参数',
    '要 dump 内存里的解密后字符串',
    '要按包名附加并注入脚本',
  ],
};

let added = 0;
for (const [k, v] of Object.entries(EXTRA)) {
  if (!cur[k]) { cur[k] = v; added += v.length; }
}
fs.writeFileSync(P, JSON.stringify(cur, null, 2) + '\n', 'utf8');
console.log('工具总数', Object.keys(cur).length, '新增任务', added);

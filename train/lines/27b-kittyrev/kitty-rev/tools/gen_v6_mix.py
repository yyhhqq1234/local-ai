#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_v6_mix.py — V6 强化数据集生成器

针对 v5 三条缺陷（见 logs/v5/V6-STRENGTHEN-PLAN.md）：
  修1 打掉 kitty_ops 依赖   → 具体工具直调样本
  修2 多步轨迹              → 六条主线 3-5 步 trajectory
  修3 tools schema 注入     → 每条样本带 tools 数组

输出 data/intent3/v6-mix/train.jsonl
每条形如 {"messages":[...], "tools":[...], "meta":{"line":..,"src":..}}
assistant 消息带 tool_calls（OpenAI function calling 格式），tool 消息带回包。

回包全部取自 A 通道真实回包格式（见 kitty_ops 冻结表），不虚构格式。
"""
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "data", "intent3", "v6-mix")

SYS = ("你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。"
       "工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，"
       "按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。")

# ── 六条主线的轨迹模板 ────────────────────────────────────────────────
# 每步: (tool, args, reply)   reply 用真实回包格式
TRAJ = [
    # 1 侦察线 -----------------------------------------------------------
    {"line": "recon", "user": "先确认 kitty 通道和宿主还活着，再列一下当前进程表",
     "steps": [
         ("kitty_status", {}, "OK|bridge=v0.2.9|cmd_age_ms=12|rep_age_ms=8|pending=0"),
         ("kitty_status", {"probe": True}, "OK|Kitty-bridge v0.2.9"),
         ("kitty_ce", {"op": "LP"}, "OK|4\n1a4c|explorer.exe\n2b7d|chrome.exe\n33f1|kitty-target.exe\n3c02|KittyCE.exe"),
     ],
     "final": "通道健康：桥 v0.2.9，PING 回 OK，pending 为 0。进程表 4 个，靶标 kitty-target.exe 的 pid 是 33f1（hex）。"},
    {"line": "recon", "user": "靶标进程叫什么、pid 多少，顺手把它的模块基址全拿下来",
     "steps": [
         ("kitty_ce", {"op": "LP"}, "OK|3\n1a4c|explorer.exe\n33f1|kitty-target.exe\n3c02|KittyCE.exe"),
         ("kitty_ce", {"op": "OPEN|33f1"}, "OK|13297"),
         ("kitty_ce", {"op": "MODENUM"}, "OK|3\nkitty-target.exe|7ff6dadb0000|1|1a3000\nkernel32.dll|7ffb12340000|1|1e0000\nntdll.dll|7ffb12560000|1|1f2000"),
     ],
     "final": "靶标 kitty-target.exe，pid 十进制 13297。模块基址：主模块 7ff6dadb0000（size 1a3000）、kernel32 7ffb12340000、ntdll 7ffb12560000。"},
    {"line": "recon", "user": "宿主可能挂了，检查一下 KittyCE 进程与桥的状态，必要时自愈",
     "steps": [
         ("kitty_status", {}, "OK|bridge=down|cmd_age_ms=999999|pending=0|host=none"),
         ("kitty_drv", {"action": "host"}, "OK|host=restarted|pid=21044|ping=OK|sync_archived=2"),
         ("kitty_ce", {"op": "PING"}, "OK|Kitty-bridge v0.2.9"),
     ],
     "final": "宿主原已消失，kitty_drv host 已重拉（新 pid 21044），归档 2 个残留作业，PING 恢复 OK。"},

    # 2 静态线 -----------------------------------------------------------
    {"line": "static", "user": "notepad2.exe 双击闪退，怀疑加壳但节表看着正常，怎么定性",
     "steps": [
         ("kitty_patch", {"action": "info", "path": "notepad2.exe"}, "OK|machine=0x8664|sections=5|.text vsize=0x1a000 raw=0x1a000|.rsrc vsize=0x9000 raw=0x2000|entry=0x1234"),
         ("kitty_die", {"action": "scan", "target": "notepad2.exe"}, "OK|packer=(none)|compiler=MSVC(19.3x)|note=节表正常"),
     ],
     "final": "info 与 die 一致：节 VirtualSize 与 SizeOfRawData 相符、无 RWX 节（0xE0000020），die 报 packer 空、compiler 为 MSVC。判：不是壳，先查入口与导入。"},
    {"line": "static", "user": "拿一个 PE 做三件套：基本信息、加壳判定、符号面",
     "steps": [
         ("kitty_patch", {"action": "info", "path": "app.exe"}, "OK|machine=0x8664|sections=6|subsystem=GUI|image_base=0x140000000"),
         ("kitty_die", {"action": "scan", "target": "app.exe"}, "OK|packer=UPX(3.96)|compiler=(stripped)"),
         ("kitty_sym", {"action": "imports", "source": "file", "path": "app.exe"}, "OK|imports=42|kernel32.dll|CreateFileW|VirtualProtect|LoadLibraryW|GetProcAddress"),
     ],
     "final": "先 UPX 脱壳再谈：die 报 UPX 3.96、compiler 被盖。导入表 42 条，含 VirtualProtect/LoadLibrary/GetProcAddress —— 脱壳后重点看这三条。"},
    {"line": "static", "user": "把这个 dll 的导出表列出来，我要找它的对外入口",
     "steps": [
         ("kitty_sym", {"action": "exports", "source": "file", "path": "plugin.dll"}, "OK|exports=6|InitPlugin|RunTask|FreeTask|GetVersion|DllMain|_guard_check_icall"),
         ("kitty_sym", {"action": "resolve", "source": "file", "path": "plugin.dll", "name": "RunTask"}, "OK|va=0x180001a20"),
     ],
     "final": "导出 6 个，对外入口能力集中在 InitPlugin / RunTask / FreeTask；RunTask 在 VA 0x180001a20，从它入手。"},
    {"line": "static", "user": "用 IDA 批量把函数列表和字符串都导出来",
     "steps": [
         ("kitty_ida", {"action": "analyze", "target": "crackme.exe", "out": "logs/ida-crackme"}, "OK|functions=214|strings=389|rc=0|out=logs/ida-crackme"),
         ("kitty_ida", {"action": "functions", "out": "logs/ida-crackme", "limit": 60}, "OK|214 functions|top=main(0x140001000),check_serial(0x1400014c0),win(0x140001720)"),
         ("kitty_ida", {"action": "strings", "out": "logs/ida-crackme", "filter": "serial"}, "OK|3 hits|%.8s 匹配|Wrong serial|Access granted"),
     ],
     "final": "IDA 分析完成：214 函数 / 389 字符串。关键函数 check_serial@0x1400014c0，配合「%.8s 匹配」这条格式串判断是 8 字符比较。"},

    # 3 动态线 -----------------------------------------------------------
    {"line": "dynamic", "user": "用 x64dbg 在这个进程打开文件时断下来，把参数存下来",
     "steps": [
         ("kitty_x64dbg", {"action": "selftest"}, "OK|x64dbg ready|ver=2024.04|script=ok"),
         ("kitty_x64dbg", {"action": "seed", "addr": "kernelbase.CreateFileW",
                           "seedCmd": "savedata D:\\out.bin, notepad.exe, 64", "logfile": "logs/dbg-cf.log"}, "OK|seeded|bp=kernelbase.CreateFileW|log=logs/dbg-cf.log"),
         ("kitty_x64dbg", {"action": "readlog", "logfile": "logs/dbg-cf.log"}, "OK|hit=1|rcx=0x1|rdx=0x2a4ff0|3 lines"),
     ],
     "final": "自检通过，在 kernelbase.CreateFileW 下断并运行一次，命中 1 次；rcx=0x1（句柄栈参数）、rdx=0x2a4ff0 指向文件路径。日志在 logs/dbg-cf.log。"},
    {"line": "dynamic", "user": "跑一段调试脚本：下断、跑、收集、回读",
     "steps": [
         ("kitty_x64dbg", {"action": "run", "target": "crackme.exe", "script": "scripts/bp.js", "logfile": "logs/dbg-run.log"}, "OK|started|pid=8812|log=logs/dbg-run.log"),
         ("kitty_x64dbg", {"action": "rununtil", "artifact": "logs/arg.bin", "maxRun": 20}, "OK|runs=3|artifact=logs/arg.bin|size=64"),
         ("kitty_x64dbg", {"action": "collect", "logfile": "logs/dbg-run.log"}, "OK|lines=48|events=6|artifact=logs/arg.bin"),
     ],
     "final": "调试会话跑完 3 次到达断点，参数落盘 logs/arg.bin（64 字节），日志 48 行 6 个事件。"},

    # 4 内存线 -----------------------------------------------------------
    {"line": "memory", "user": "找血量，当前显示 87，值类型大概是 4 字节整数",
     "steps": [
         ("kitty_ce", {"op": "OPEN|kitty-target.exe"}, "OK|13297"),
         ("kitty_ce", {"op": "MODENUM"}, "OK|2\nkitty-target.exe|7ff6dadb0000|1|1a3000\nntdll.dll|7ffb12560000|1|1f2000"),
         ("kitty_ce", {"op": "S_NEW|dword|87|0x7ff6dadb0000|0x7ff6dadc0000"}, "OK|scan|range|6w|dword=87"),
         ("kitty_ce", {"op": "S_GET|0|6"}, "OK|6\n7ff6dadb3a20\n7ff6dadb7c18\n7ff6dadbb004\n7ff6dadbd210\n7ff6dadbe33c\n7ff6dadbf1a8"),
     ],
     "final": "主模块窗口内 6 个候选（7ff6dadb3a20 等）。下一步改一下血量再看哪个变，或者直接反查指针链。"},
    {"line": "memory", "user": "候选 6 个太多，我要指针链，从 7ff6dadb3a20 往上找",
     "steps": [
         ("kitty_pchain", {"target": "0x7ff6dadb3a20", "mod": "kitty-target.exe", "depth": 2}, "OK|hits=3|7ff6dadb3a20<-7ff6dadc1f00+0x18<-7ff6dc0a2010+0x2c8"),
         ("kitty_ce", {"op": "P_WALK|0x7ff6dc0a2010|0x2c8"}, "OK|0x7ff6dadc1f00"),
         ("kitty_ce", {"op": "R|0x7ff6dadc1f00|qword"}, "OK|140729835470848"),
     ],
     "final": "链：模块基址 + 0x2c8 → 7ff6dadc1f00，再 +0x18 → 7ff6dadb3a20（血量）。P_WALK 回验通过，R 读出的指针值也对得上。"},
    {"line": "memory", "user": "扫描区太大报错了，怎么处理",
     "steps": [
         ("kitty_ce", {"op": "S_NEW|dword|100|0x0|0x7fffffffffff"}, "ERR|need-range|window>16MB"),
         ("kitty_ce", {"op": "RANGE_INFO"}, "OK|target=13297|alloc_windows=0x7ff6dadb0000-0x7ff6dc000000,0x1c0000000-0x1c1000000|note=S_NEW_requires_explicit_range"),
         ("kitty_ce", {"op": "S_NEW|dword|100|0x7ff6dadb0000|0x7ff6dadc0000"}, "OK|scan|range|11w|dword=100"),
     ],
     "final": "S_NEW 必须给显式区间且单窗 ≤16MB。RANGE_INFO 给出两个可扫分配窗，改用主模块 0x7ff6dadb0000-0x7ff6dadc0000 后扫描成功，11 个命中。"},

    # 5 内核线 -----------------------------------------------------------
    {"line": "kernel", "user": "走内核路由读一下主模块开头，和用户态读法对照",
     "steps": [
         ("kitty_km", {"action": "info"}, "OK|pid=13297|peProcess=0xffffa10b3c2d5080|km_open=1|km_mem=1|km_regions=1|km_phys=1"),
         ("kitty_km", {"action": "attach", "pid": 13297}, "OK|pid=13297|peProcess=0xffffa10b3c2d5080|open=1|mem=1|regions=1|opened=1"),
         ("kitty_dualview", {"addr": "0x7ff6dadb0000", "vt": "bytes:16", "samples": 2}, "OK|view=R/KM_R/KM_PR 一致|MZ...|gate=green"),
     ],
     "final": "PEProcess 非零且 open/mem/regions 全 1，内核对象可访问。三视图（用户态 R / 内核 KM_R / 物理 KM_PR）2 轮采样一致，gate=green，无拦截面。"},
    {"line": "kernel", "user": "把某个虚拟地址翻成物理地址再物理读",
     "steps": [
         ("kitty_km", {"action": "pa", "addr": "0x7ff6dadb0000"}, "OK|va=0x7ff6dadb0000|pa=0x1f3a2000|via=pid,va"),
         ("kitty_km", {"action": "pread", "pa": "0x1f3a2000", "vt": "bytes:16"}, "OK|4d 5a 90 00 03 00 00 00 04 00 00 00 ff ff 00 00"),
     ],
     "final": "VA 0x7ff6dadb0000 → PA 0x1f3a2000，物理读出 4d5a9000… 正是 MZ 头，通路成立。"},

    # 6 回归线 -----------------------------------------------------------
    {"line": "regress", "user": "换变体前先看看有哪些可选，然后切到简易版跑自检",
     "steps": [
         ("kitty_variants", {"action": "list"}, "OK|6 ce + 2 dbg|ws-svip-full|ws-svip-simple|ws-dbg-dbg64"),
         ("kitty_variants", {"action": "switch", "variant": "ws-svip-simple"}, "OK|switched|kittyDir=…\\simple|next call effective"),
         ("kitty_selftest", {"group": "a"}, "OK|PASS 12/12|bridge ok|x64dbg skip"),
     ],
     "final": "变体清单 8 项（6 CE + 2 DBG）。已切到 ws-svip-simple，下一次工具调用生效；A 组自检 12/12 通过。"},
    {"line": "regress", "user": "跑一遍完整回归自检（A+C+E）",
     "steps": [
         ("kitty_selftest", {"group": "all"}, "OK|A 12/12|C 9/9|E 5/5|rc=0|95s"),
     ],
     "final": "三组全过：A 桥 12/12、C x64dbg 9/9、E 红线 5/5，rc=0，总用时 95 秒。"},
]

# ── 直调样本（打掉 kitty_ops 依赖）────────────────────────────────────
# (user, tool, args, reply, final)
DIRECT = [
    ("有个 apk 要反编译成 java 看逻辑", "kitty_jadx",
     {"action": "decompile", "target": "app.apk", "out": "logs/jadx-app"},
     "OK|sources=1248|out=logs/jadx-app/sources|rc=0",
     "反编译完成，1248 个 java 源文件在 logs/jadx-app/sources，直接搜 AndroidManifest 或入口 Activity。"),
    ("jadx 出来的东西太杂，搜一下含 encrypt 的方法", "kitty_jadx",
     {"action": "search", "target": "app.apk", "out": "logs/jadx-app"},
     "OK|hits=7|CryptoUtils.encrypt|Net.sign|Token.build",
     "7 处命中，重点 CryptoUtils.encrypt 与 Net.sign —— 签名链路大概率在这两个类。"),
    ("这个 apk 有没有加壳，先给个指纹", "kitty_apkscan",
     {"action": "scan", "target": "app.apk"},
     "OK|packer=(none)|anti_vm=false|dex=3|note=未加壳",
     "无壳，3 个 dex，未见反虚拟机逻辑，可以直接静态看。"),
    ("apk 解包成 smali，改完要能重打包", "kitty_apktool",
     {"action": "decode", "target": "app.apk", "out": "logs/apk-dec"},
     "OK|decoded|smali=3 dex|out=logs/apk-dec|rc=0",
     "已解到 logs/apk-dec（3 个 dex 的 smali）。改完用 apktool action=build 重打包，再签名。"),
    ("脱壳后的产物散在各处，收口清点一下 dex", "kitty_unpack",
     {"action": "collect", "out": "logs/dex-out"},
     "OK|collected|dex=5|out=logs/dex-out",
     "收口完成，5 个 dex 在 logs/dex-out，下一步可以直接喂 jadx。"),
    ("这个 so 是什么编译器出的、有没有混淆", "kitty_rea_binary",
     {"path": "libnative.so"},
     "OK|arch=aarch64|sections=22|symbols=148|note=部分符号保留",
     "aarch64 ELF，22 节 148 符号，符号表未完全剥离 —— 可以先按符号定位关键函数。"),
    ("用 REA 看这个 apk 的清单和权限", "kitty_rea_android",
     {"path": "app.apk"},
     "OK|package=com.example.app|minSdk=24|targetSdk=34|perms=12|dangerous=3",
     "包名 com.example.app，minSdk 24 / targetSdk 34，12 条权限其中 3 条危险级。"),
    ("追一下这个特性字符串从哪来", "kitty_rea_trace",
     {"query": "Access granted", "case_sensitive": False},
     "OK|trail=4|check_serial→win→printf|files=2",
     "‘Access granted’ 的链路：check_serial → win → printf，跨 2 个文件 4 步可追完。"),
    ("两个版本的 dll 差在哪，函数级对一下", "kitty_rea_compare",
     {"left": "{\"symbol\":\"check_serial\",\"va\":\"0x1400014c0\"}",
      "right": "{\"symbol\":\"check_serial\",\"va\":\"0x1400015a0\"}"},
     "OK|delta=high|added=1|removed=0|changed=3",
     "两版 check_serial 差异高：新增 1 处判断、3 处逻辑变化 —— 大概率就是修的那个点。"),
    ("把这个 dll 的调用链从入口追到写文件", "kitty_rea_callpath",
     {"start": "DllMain", "goal": "WriteFile", "direction": "forward"},
     "OK|paths=2|DllMain→InitPlugin→RunTask→WriteFile",
     "追到 2 条路径，主路径 DllMain→InitPlugin→RunTask→WriteFile，写文件能力在 RunTask 里。"),
    ("unity il2cpp 游戏，先把元数据 dump 出来", "kitty_il2cppdumper",
     {"action": "dump", "so": "libil2cpp.so", "meta": "global-metadata.dat", "out": "logs/il2cpp"},
     "OK|classes=8421|methods=138204|out=logs/il2cpp|rc=0",
     "dump 完成：8421 类 / 138204 方法，产物在 logs/il2cpp，可以接着生成 dummy dll。"),
    ("dump 完把结构解析成可读的", "kitty_il2cppdumper",
     {"action": "parse", "out": "logs/il2cpp"},
     "OK|parsed|types=8421|fields=62188",
     "解析完成，8421 类型 62188 字段，可直接搜目标类名。"),
    ("用 Cpp2IL 处理这个 il2cpp 包，要能出伪代码", "kitty_cpp2il",
     {"action": "dump", "gameDir": "C:/Game", "out": "logs/cpp2il"},
     "OK|assemblies=41|out=logs/cpp2il|rc=0",
     "Cpp2IL 出了 41 个 assembly 到 logs/cpp2il，用 ILSpy 打开就能看伪代码。"),
    ("godot 游戏，把 pck 里的脚本恢复出来", "kitty_gdre",
     {"action": "recover", "target": "game.pck", "out": "logs/godot"},
     "OK|recovered|scripts=318|scenes=94|out=logs/godot",
     "恢复 318 个脚本 94 个场景，都在 logs/godot，gdsdecomp 已还原为 .gd 源码。"),
    ("ue 打包的 pak，先看看里面有什么", "kitty_fmodel",
     {"action": "list", "pak": "pakchunk0-Windows.pak", "out": "logs/fmodel"},
     "OK|entries=28104|out=logs/fmodel",
     "pak 里 28104 个条目，清单已导出到 logs/fmodel，可以直接筛 .uasset。"),
    ("把 ue 的包解开导出资源", "kitty_fmodel",
     {"action": "export", "pak": "pakchunk0-Windows.pak", "out": "logs/ue-export"},
     "OK|exported=28104|out=logs/ue-export|rc=0",
     "导出完成，28104 个资源在 logs/ue-export。"),
    (".net 程序集被混淆了，先脱一遍", "kitty_dnspy",
     {"action": "deobf", "target": "app.dll", "out": "logs/dnspy"},
     "OK|deobf=ok|renamed=2140|out=logs/dnspy",
     "de4dot 处理完成，还原 2140 个符号名，产物在 logs/dnspy，用 dnSpyEx 打开看逻辑。"),
    ("mono 的 unity 游戏，打开 assembly 看类", "kitty_dnspy",
     {"action": "open", "target": "Assembly-CSharp.dll"},
     "OK|opened|types=1204|methods=9822",
     "已打开 Assembly-CSharp.dll：1204 类型 9822 方法，直接搜目标类。"),
    ("unity 游戏想运行时看对象，注入 explorer", "kitty_uexplorer",
     {"action": "inject", "pid": 8812},
     "OK|injected|UnityExplorer loaded|pid=8812",
     "UnityExplorer 已注入 pid 8812，游戏内按 F7 开面板。"),
    ("ue 游戏运行时想 dump sdk", "kitty_uedump",
     {"action": "inject", "pid": 8812},
     "OK|injected|UEDumper ready|pid=8812",
     "UEDumper 已注入，接着用 action=collect 收 SDK。"),
    ("ue 游戏跑起来后注入 ue4ss 看对象", "kitty_ue4ss",
     {"action": "inject", "pid": 8812},
     "OK|injected|UE4SS v3.0.1|pid=8812",
     "UE4SS 注入成功（v3.0.1），控制台可以用来查 UObject。"),
    ("抓一下这个 app 的 http 流量", "kitty_net",
     {"action": "capture", "port": 8080, "out": "logs/net.pcap"},
     "OK|started|pid=15420|out=logs/net.pcap",
     "mitmdump 已在 8080 起（pid 15420），流量写 logs/net.pcap；设备侧把代理指到本机 8080。"),
    ("抓完了，把请求解出来", "kitty_net",
     {"action": "decode", "out": "logs/net.pcap", "filter": "http.request"},
     "OK|requests=214|hosts=3|api.example.com|x.com|cdn.example.com",
     "214 条请求 3 个域，主 API 是 api.example.com。"),
    ("停掉抓包", "kitty_net",
     {"action": "stop", "pid": 15420},
     "OK|stopped|pid=15420",
     "已停止（pid 15420），pcap 保留在 logs/net.pcap。"),
    ("这段二进制是什么序列化格式，解一下", "kitty_proto",
     {"action": "decode", "target": "0a03616263"},
     "OK|format=protobuf|fields=1|field1=string\"abc\"",
     "是 protobuf：字段 1、类型 string、值 abc。"),
    ("hook 一下这个 app 的加密函数", "kitty_frida",
     {"action": "attach", "pkg": "com.example.app", "script": "scripts/hook.js", "out": "logs/frida.log"},
     "OK|attached|script=hook.js|log=logs/frida.log",
     "已附加到 com.example.app 并加载 hook.js，日志写 logs/frida.log。"),
    ("用 frida spawn 模式从启动就 hook", "kitty_frida",
     {"action": "spawn", "pkg": "com.example.app", "script": "scripts/hook.js"},
     "OK|spawned|pid=9012|script loaded",
     "spawn 成功（pid 9012），从进程启动即生效。"),
    ("lua 脚本被编译成 luac 了，反编译回来", "kitty_lua",
     {"action": "decompile", "target": "main.luac", "out": "logs/lua"},
     "OK|decompiled|lines=842|out=logs/lua/main.lua",
     "反编译出 842 行到 logs/lua/main.lua。"),
    ("这个 unity 包里的资源导出来", "kitty_assetrip",
     {"action": "export", "target": "game_Data", "out": "logs/assets"},
     "OK|exported=1842|textures=902|meshes=318|out=logs/assets",
     "导出 1842 项（902 贴图 318 网格）到 logs/assets。"),
    ("给这个 unity 游戏装 bepinex", "kitty_bepinex",
     {"action": "install", "gameDir": "C:/Game"},
     "OK|installed|BepInEx 5.4.23|x64|gameDir=C:/Game",
     "BepInEx 5.4.23 x64 已装到 C:/Game。"),
    ("dump 一下主模块，再按节表还原成磁盘格式", "kitty_dump",
     {"module": "kitty-target.exe", "path": "logs/dump.bin", "unmap": True, "reference": "kitty-target.exe"},
     "OK|dumped=1703936|unmapped|match=99.87%|path=logs/dump-unmapped.bin",
     "转储 1.7MB 并还原为磁盘格式，与参考文件逐字节一致率 99.87%。"),
    ("把这块内存改成可执行，然后注入 dll", "kitty_prot",
     {"action": "rwx", "addr": "0x7ff6dadb0000", "size": 4096},
     "OK|protect=RWX|addr=0x7ff6dadb0000|size=4096",
     "已改为 RWX。"),
    ("注入这个 dll 到靶标", "kitty_inject",
     {"dll": "D:/work/hook.dll", "module": "hook.dll"},
     "OK|injected|module=hook.dll|base=0x7ff6dc110000",
     "注入成功，hook.dll 落在 0x7ff6dc110000。"),
    ("用内核写绕过把这段代码改掉", "kitty_wpb",
     {"addr": "0x7ff6dadb1000", "hex": "90 90 90", "restore": True},
     "OK|wrote=3|verify=ok|pte_restored=1",
     "PTE 直写 3 字节并回读校验通过，PTE 已还原。"),
    ("一键跑反作弊对抗，看有没有拦截面", "kitty_acescan",
     {"target": "kitty-target.exe", "writeback": True, "samples": 3},
     "OK|gate=green|R/KM_R/KM_PR 一致|writeback 全通|evidence=logs/acescan-20261024.jsonl",
     "门禁 green：三视图 3 轮一致、写回环全通 —— 该目标当前无拦截面。证据落 logs/acescan-20261024.jsonl。"),
    ("把驱动和宿主恢复到可用状态", "kitty_drv",
     {"action": "ensure"},
     "OK|Private_Access=started|mhtglyts=started|both green",
     "双驱都已起（Private_Access → mhtglyts），双绿。"),
    ("看看驱动初始化三层状态", "kitty_init",
     {"action": "status"},
     "OK|L0=ok|L1=ok|L2=ok|driver=Private_Access|host=KittyCE",
     "三层全 ok：驱动 Private_Access 在跑、宿主 KittyCE 在位。"),
    ("辅助驱动面都有什么", "kitty_drvio",
     {"action": "status"},
     "OK|services=2|files=2|devices=2|software=7",
     "双驱服务/文件/设备各 2 项，软件面 7 项（WKE64/VT-Debug/CE 插件等）。"),
    ("只看软件面清点", "kitty_drvio",
     {"action": "surf"},
     "OK|WKE64=present|VT-Debug=absent|CE-plugins=3|.dat=2",
     "软件面：WKE64 在、VT-Debug 不在、CE 插件 3 个、.dat 2 个。"),
    ("看看当前夜跑状态", "kitty_loop_status",
     {},
     "OK|host=up|target=none|red=0|patterns=12|last=logs/loop-20261024.jsonl",
     "宿主 up、无靶标、红线 0、特征库 12 条，最近一轮日志 logs/loop-20261024.jsonl。"),
    ("把模块里这段 x64 代码汇编一下", "kitty_asm",
     {"action": "assemble", "code": "xor eax,eax\nret", "base": "0x140001000"},
     "OK|bytes=31 C0 C3|len=3",
     "汇编结果 31 C0 C3（xor eax,eax / ret），3 字节。"),
    ("算一下从这条指令跳到目标地址的相对位移", "kitty_asm",
     {"action": "jump", "from": "0x140001000", "target": "0x1400014c0", "kind": "jmp"},
     "OK|bytes=E9 BB 04 00 00|len=5",
     "jmp 的 rel32 = 0x4BB，指令 5 字节：E9 BB 04 00 00。"),
    ("在文件里搜这段字节特征", "kitty_patch",
     {"action": "find", "path": "app.exe", "pattern": "48 8B ?? 05"},
     "OK|hits=3|0x1a20|0x2c40|0x33f10",
     "3 处命中：0x1a20 / 0x2c40 / 0x33f10。"),
    ("把这个跳转改成永远跳", "kitty_patch",
     {"action": "patch", "path": "app.exe", "at": "0x1a2c", "expect": "74 1E", "bytes": "EB 1E"},
     "OK|patched|0x1a2c 74 1E -> EB 1E|backup=app.exe.bak|checksum=updated",
     "已改 0x1a2c 的 JZ→JMP（74 1E → EB 1E），备份 app.exe.bak，校验和已重算。"),
    ("回滚刚才那个补丁", "kitty_patch",
     {"action": "rollback", "path": "app.exe"},
     "OK|restored from app.exe.bak|0x1a2c EB 1E -> 74 1E",
     "已从 app.exe.bak 还原，0x1a2c 回到 74 1E。"),
    ("算这个文件的哈希", "kitty_patch",
     {"action": "hash", "path": "app.exe"},
     "OK|sha256=9f2c…|md5=1a3b…|size=1703936",
     "sha256 9f2c… / md5 1a3b…，大小 1,703,936 字节。"),
    ("宿主通道健康看一眼", "kitty_status",
     {},
     "OK|bridge=v0.2.9|pending=0|cmd_age_ms=9|host=KittyCE pid=21044",
     "桥 v0.2.9，pending 0，宿主 KittyCE pid 21044。"),
]


def tc(idx, tool, args):
    """构造 assistant 的 tool_call"""
    return {"id": f"call_{idx}",
            "type": "function",
            "function": {"name": tool,
                         "arguments": json.dumps(args, ensure_ascii=False)}}


def build_traj(t, tools_schema, rnd):
    msgs = [{"role": "system", "content": SYS},
            {"role": "user", "content": t["user"]}]
    for i, (tool, args, reply) in enumerate(t["steps"], 1):
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [tc(i, tool, args)]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": reply})
    msgs.append({"role": "assistant", "content": t["final"]})
    return {"messages": msgs, "tools": tools_schema,
            "meta": {"line": t["line"], "kind": "trajectory"}}


def build_direct(d, tools_schema, idx):
    user, tool, args, reply, final = d
    msgs = [{"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": "", "tool_calls": [tc(idx, tool, args)]},
            {"role": "tool", "tool_call_id": f"call_{idx}", "content": reply},
            {"role": "assistant", "content": final}]
    return {"messages": msgs, "tools": tools_schema,
            "meta": {"kind": "direct", "tool": tool}}


def main():
    tp = os.path.join(OUT_DIR, "tools.json")
    tj = json.load(open(tp, encoding="utf-8"))
    tools_schema = tj["function_schemas"]
    names = {x["name"] for x in tj["tools"]}
    actions = {x["name"]: x["actions"] for x in tj["tools"]}

    out = []
    # 轨迹：每条模板重复多次（换措辞前后缀，模拟不同问法）
    REQ_PREFIX = ["", "帮我", "麻烦", "先", "现在", "按流程"]
    for t in TRAJ:
        for k in range(12):            # 16 模板 × 12 ≈ 192 条轨迹
            tt = dict(t)
            if k:
                tt["user"] = REQ_PREFIX[k % len(REQ_PREFIX)] + t["user"]
            out.append(build_traj(tt, tools_schema, random.Random(k)))

    # 直调：每条重复多次
    for k in range(9):                 # 47 样本 × 9 ≈ 423 条直调
        for i, d in enumerate(DIRECT):
            out.append(build_direct(d, tools_schema, i + 1))

    # 校验
    errs = []
    import collections
    toolcnt = collections.Counter()
    for n, rec in enumerate(out):
        ids = set()
        for m in rec["messages"]:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for c in m["tool_calls"]:
                    nm = c["function"]["name"]
                    toolcnt[nm] += 1
                    if nm not in names:
                        errs.append(f"#{n} 未知工具 {nm}")
                    a = json.loads(c["function"]["arguments"]).get("action")
                    if a is not None and nm in actions and a not in actions[nm]:
                        errs.append(f"#{n} {nm} action={a} 不在 {actions[nm]}")
                    ids.add(c["id"])
            if m.get("role") == "tool" and m.get("tool_call_id") not in ids:
                errs.append(f"#{n} tool_call_id {m.get('tool_call_id')} 无对应 call")

    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "train.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"写出 {len(out)} 条 → {p}")
    print(f"校验错误 {len(errs)} 条")
    for e in errs[:10]:
        print("  ", e)
    print("\n工具频次 Top 15:")
    for nm, c in toolcnt.most_common(15):
        print(f"  {nm:<22} {c}")
    total = sum(toolcnt.values())
    ops = toolcnt.get("kitty_ops", 0)
    print(f"\nkitty_ops 占比: {ops}/{total} = {ops/max(1,total)*100:.2f}%  （v5 是 81/753=10.8%，目标 <2%）")
    for k in ("kitty_jadx", "kitty_rea_trace", "kitty_ida", "kitty_x64dbg"):
        print(f"  {k:<18} {toolcnt.get(k,0)}")


if __name__ == "__main__":
    main()

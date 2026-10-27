#!/usr/bin/env python
"""domain_stat.py — final-re 领域分布统计（口径与评估报告对齐）"""
import json
import re
import sys

DOMAINS = [
    ('固件',      r'固件|firmware|binwalk|squashfs|UBI|JFFS2|Firmadyne'),
    ('CTF',       r'\bCTF\b|flag\{|checksec|pwnable'),
    ('内核/驱动', r'KM_|DBG_|DBVM|驱动|dbk64|mhtglyts|m_?htgly|PTE'),
    ('加壳/反调试', r'加壳|壳\b|UPX|VMProtect|Themida|反调试|BeingDebugged|NtGlobalFlag'),
    ('移动',      r'APK|jadx|apktool|smali|frida|Android|dex\b'),
    ('SDK/引擎',  r'Unity|IL2CPP|Unreal|UE4|UE5|Cpp2IL|il2cpp|Ghidra|AssetRipper|gdre|Godot'),
    ('PE/ELF',    r'\bPE\b|ELF|节表|节头|导入表|导出表|e_lfanew|imageBase|SizeOfImage|checksec|PLT|GOT|\.text|\.rdata|virtualSize'),
    ('游戏内存',  r'血量|坐标|指针链|P_BACK|P_WALK|扫描|S_NEW|S_GET|自瞄|血量|MODENUM|内存读|内存写'),
    ('许可/授权', r'license|授权|卡密|serial|注册机|激活|entitlement'),
    ('协议/网络', r'协议|protobuf|pcap|抓包|WebSocket|mitmproxy|解包抓'),
]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'train/data/final-re-refined.jsonl'
    rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
    n = len(rows)
    cnt = {d: 0 for d, _ in DOMAINS}
    cnt['其他'] = 0
    for r in rows:
        text = json.dumps(r.get('messages', []), ensure_ascii=False)
        hit = False
        for d, pat in DOMAINS:
            if re.search(pat, text, re.I):
                cnt[d] += 1
                hit = True
                break
        if not hit:
            cnt['其他'] += 1
    print(f'{path}  {n} 条')
    print('-' * 46)
    for d, c in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f'{d:<12} {c:>5}  {c / n * 100:>5.1f}%')

if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""re-pe-structure 补齐 G（121-124）：保证过闸后仍 ≥120"""

PE_G = [
("导入表里两个函数名相同但 DLL 不同（都叫 CreateFileW）。",
"""同名不同 DLL 是正常现象（不同模块可导出同名符号），异常的是加载器/分析器选错。

```
kitty_sym action=imports path=SAMPLE.exe filter=CreateFile
```
判读：两条各自的所属 DLL。kernel32.CreateFileW 与某第三方 DLL 的同名导出并存。

```
kitty_ghidra action=analyze target=SAMPLE.exe
kitty_ghidra action=decompile out=logs\\ghidra-<name>-<ts> name=<调用点>
```
判读：调用点的参数个数/顺序决定它实际用的是哪个。第三方同名函数的签名常与 Win32 不同。

```
kitty_ce op=OPEN|<pid> → MODENUM
kitty_ce op="R|0xIAT_SLOT|qword"
kitty_prot action=query addr=<读出的值>
```
判读：落在 kernel32 区间 = 用的是系统实现；落在别的模块 = 第三方实现。

退出：给出「两个同名导出各自的归属 + 实际被调用的是哪个」。
分析器默认按名字匹配会选错，这点必须写进卡片。"""),

("样本在 .data 里有一段可执行代码但没有任何节标记。",
"""无标记的可执行数据 = 运行期改权限后执行，静态看不到任何提示。

```
kitty_patch action=info path=SAMPLE.exe
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0xDATA_VA|64"
```
判读：内存里在 .data 区寻找 x64 序言（48 89 / 55 8B / 40 53）。
命中即说明数据区藏着代码。

```
kitty_ce op="S_SNAP|bytes:16|0xBASE+0xDATA_VA|0xBASE+0xDATA_VA+0x2000"
```
跑起来后 S_CHANGED
判读：变化区里出现的可执行内容就是解密后的代码体。

```
kitty_prot action=query addr=<变化页>
```
判读：Protect 若从 RW 变成 RX，坐实「改权限后执行」。

退出：给出「代码偏移 + 权限变化 + 首字节序言」三条证据；
三者齐备才能判为隐藏代码，缺一条只记「高熵数据」。"""),

("PE 头声明 4 个节，但按节表算出来只有 3 个空间够。",
"""声明节数大于实际可容纳数 = 节表被截，最后一个节是幻影。

```
kitty_patch action=info path=SAMPLE.exe
```
判读：SizeOfHeaders 必须 ≥ 0x18(PE32+) + 0xE0/0xF0(可选头) + N×40。
不够 N×40 时，越界的节条目落在第一个节的 Raw 数据里。

```
kitty_ce op=MODENUM
kitty_ce op="MEMDUMP_HEX|0xBASE+0x18+0xE0+80|120"
```
判读：按 40 字节读第 3、4 条节表项。第 4 条 Name 是否可打印？
不可打印 → 幻影条目；可打印 → 头部空间被压缩但条目有效。

```
kitty_prot action=query addr=0xBASE+0x<第4条 VirtualAddress>
```
判读：能解析 = 加载器按它映射了；INVALID_ADDRESS = 幻影，未映射。

退出：给出「幻影条目 / 头部压缩」判定；幻影条目在算窗口时必须剔除。"""),

("同一份样本在 32 位和 64 位系统上跑，行为不一样。",
"""WOW64 下的路径/注册表重定向是第一嫌疑，不是样本刻意分叉。

```
kitty_patch action=info path=SAMPLE.exe
```
判读：Machine=0x14C 且导入里有 Wow64 系列函数。

```
kitty_sym action=imports path=SAMPLE.exe filter=Wow64
```
判读：Wow64DisableWow64FsRedirection / Wow64RevertWow64FsRedirection 存在
→ 它会主动关重定向；不存在 → 受系统默认重定向影响。

```
kitty_ce op=OPEN|<pid> → MODENUM
kitty_ce op="R|0xBASE+0xSTR_RVA|bytes:64"
```
判读：比较两个环境下它实际读取的路径（System32 vs SysWOW64）。

```
kitty_prot action=query addr=0xBASE
```
判读：确认模块是 32 位映像（IMAGE_FILE_32BIT_MACHINE）。

退出：给出「行为差异来自重定向」或「样本自身分叉」判定，并写明复现环境要求（必须固定位数）。"""),
]

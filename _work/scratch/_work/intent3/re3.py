# -*- coding: utf-8 -*-
"""re-sft 批次 3：崩溃转储补充（D11-D12）+ 协议帧还原（E1-E15）+ 许可互操作（F1-F12）+ 移动分诊（G1）。"""

RECORDS = [
    dict(id="re-061", topic="crash-dump",
         prompt="栈溢出后提示 security cookie 校验失败，怎么定位？",
         response="""cdb -z crash-j.dmp -c ".ecxr; kv; q"
kitty_ida action=functions out=logs/ida-app filter=security_check
判据一：异常码 0xC0000409 且第一个参数为 2（FAST_FAIL_STACK_COOKIE_CHECK_FAILURE）。
判据二：崩溃函数有 > 0x100 的局部数组，且存在无边界拷贝调用。
收敛：从校验失败点向上找写入点，按栈帧布局算越界字节数；cookie 本身正确说明溢出发生在返回前的拷贝。"""),
    dict(id="re-062", topic="crash-dump",
         prompt="怎么从转储还原崩溃前的操作时间线？",
         response="""cdb -z crash-k.dmp -c "!teb; q"
kitty_ce op="MEMDUMP_HEX|<peb_addr>|256"
判据一：TEB 的 ProcessCreateTime 与 PEB->ProcessParameters 里的命令行可读。
判据二：模块加载顺序的时间戳单调，缺口处即注入或延迟加载点。
收敛：命令行、加载顺序、最后异常三者按时间排序，缺口时间窗就是可疑操作窗口。"""),
    dict(id="re-063", topic="protocol",
         prompt="抓了一段 TCP，怎么确定应用层帧边界？",
         response="""kitty_net action=decode out=logs/net-a.pcap filter="tcp.port==9000" limit=120
kitty_ce op="MEMDUMP_HEX|<first_payload_va>|64"
判据一：每帧首 4 字节小端值 == 帧总长-4 → 长度前缀。
判据二：若首字节是 0x7B（{）且帧尾是 0x7D，按 JSON 括号配平切分。
收敛：两种都试，能把整段流切成完整帧且无剩余字节的方案即正确。"""),
    dict(id="re-064", topic="protocol",
         prompt="协议用分隔符还是长度前缀，怎么快速区分？",
         response="""kitty_net action=decode out=logs/net-b.pcap filter="tcp.port==8081" limit=200
kitty_ghidra action=strings out=logs/gh-client limit=400
判据一：统计帧首 2/4 字节与后续实际长度的相关性，系数 > 0.95 → 长度前缀。
判据二：固定字节 0x0A 或 0x00 出现在每帧同一位置 → 分隔符或填充。
收敛：相关性强走长度解析，否则按分隔符切；两者都不成立时看客户端里的格式化模板串。"""),
    dict(id="re-065", topic="protocol",
         prompt="二进制载荷像 protobuf，怎么确认？",
         response="""kitty_proto action=decode target=0A0B636C69656E742D6964
kitty_net action=decode out=logs/net-c.pcap filter="tcp.port==50051" limit=80
判据一：按 varint 解出的 tag 非 0，wire type 在 0-5，length 不越界。
判据二：整体解析无剩余字节，字段号集中在 1-16。
收敛：多帧都能完整解析即确认；出现负长度或 tag=0 就退回 TLV 假设。"""),
    dict(id="re-066", topic="protocol",
         prompt="自定义 TLV 怎么定字段表？",
         response="""kitty_ce op="MEMDUMP_HEX|<frame_va>|128"
kitty_proto action=decode target=<hex>
判据一：每项 = type(1B) + len(2B 小端) + value，type 取值集合 < 16 个。
判据二：同类 type 的 len 分布稳定（如 type=1 恒为 8）。
收敛：按 type 聚合样本，len 固定的映射为定长字段；len 变化的看内容熵，高熵是随机数/哈希，低熵是 ID。"""),
    dict(id="re-067", topic="protocol",
         prompt="WebSocket 帧怎么拆？",
         response="""kitty_net action=decode out=logs/net-ws.pcap filter="websocket" limit=120
kitty_ce op="MEMDUMP_HEX|<ws_payload_va>|64"
判据一：首字节 FIN/opcode（0x81 文本、0x82 二进制），第二字节是 MASK 位与长度。
判据二：客户端帧 MASK=1 且有 4 字节掩码，服务端帧 MASK=0。
收敛：按掩码异或还原载荷后按 opcode 分发；分片帧 FIN=0 时缓存到下一帧 FIN=1 再拼。"""),
    dict(id="re-068", topic="protocol",
         prompt="自家 App 的 TLS 流量怎么拿到明文做协议分析？",
         response="""kitty_net action=capture port=8080 out=logs/net-tls.pcap
kitty_net action=decode out=logs/net-tls.pcap filter="tls" limit=40
判据一：ClientHello 的 SNI 与目标域名一致。
判据二：客户端支持 keylog 时设置 SSLKEYLOGFILE 后能解出 HTTP/2 明文。
收敛：只处理自家 App（自建证书或 keylog）；第三方流量解不开是正常的，不做中间人。"""),
    dict(id="re-069", topic="protocol",
         prompt="怎么识别心跳包和保活字段？",
         response="""kitty_net action=decode out=logs/net-hb.pcap filter="tcp.port==7000" limit=300
kitty_ce op="MEMDUMP_HEX|<hb_va>|32"
判据一：固定间隔（±5%）出现、长度恒定、载荷大部分字节不变 → 心跳。
判据二：包内 4 字节字段随时间递增且步长与间隔一致 → 时间戳。
收敛：抓 60 秒以上再判断；只出现一次或间隔抖动大的不是心跳。"""),
    dict(id="re-070", topic="protocol",
         prompt="协议里的序列号字段怎么定位？",
         response="""kitty_net action=decode out=logs/net-seq.pcap filter="tcp.port==6000" limit=200
kitty_patch action=find path=client.exe pattern="00 00 00 00" limit=4
判据一：每个请求同一偏移的 4 字节值严格递增 1（或按窗口跳跃）。
判据二：响应同偏移值等于请求值或请求值+1。
收敛：锁定偏移后做重放，改序列号会导致服务端拒绝的那一版才是真校验点。"""),
    dict(id="re-071", topic="protocol",
         prompt="校验和字段怎么反推参数？",
         response="""kitty_net action=decode out=logs/net-crc.pcap filter="tcp.port==4000" limit=120
kitty_ce op="MEMDUMP_HEX|<frame_va>|96"
判据一：帧尾 2 或 4 字节在改动载荷后变化，且只与本帧有关。
判据二：候选 CRC16 参数（多项式 0x1021/0x8005、初值 0xFFFF/0x0000、反射与否）逐一试算，全帧命中即确定。
收敛：至少 3 帧验证，单帧命中不足以排除巧合。"""),
    dict(id="re-072", topic="protocol",
         prompt="帧头里的标志位怎么解？",
         response="""kitty_ce op="MEMDUMP_HEX|<hdr_va>|16"
kitty_net action=decode out=logs/net-flags.pcap filter="tcp.port==3000" limit=100
判据一：某字节取值集合是 2 的幂的子集（0x01/0x02/0x04/0x08）。
判据二：置位后载荷形态改变（如 0x04 后熵 > 7.5 → 压缩）。
收敛：按位与分解后逐位对照样本；能解释载荷差异的那一位才是真标志。"""),
    dict(id="re-073", topic="protocol",
         prompt="多路复用协议里的通道 ID 怎么定宽？",
         response="""kitty_net action=decode out=logs/net-mux.pcap filter="tcp.port==4433" limit=200
kitty_proto action=decode target=<hex>
判据一：每帧头部固定偏移的字段值落在 1-255 或 1-65535 的连续集合。
判据二：同一 ID 的帧按序编号，响应复用同一 ID。
收敛：ID 空间由并发会话数决定，抓高峰流量看最大 ID 即可定宽（1/2/4 字节）。"""),
    dict(id="re-074", topic="protocol",
         prompt="大包被分片了，怎么重组？",
         response="""kitty_net action=decode out=logs/net-frag.pcap filter="tcp.port==2222" limit=300
kitty_ce op="MEMDUMP_HEX|<frag_hdr_va>|32"
判据一：分片头含 (msg_id, frag_index, frag_total) 三元组，frag_total 相同且 index 连续。
判据二：重组后总长与首片声明的总长度一致。
收敛：按 msg_id 分组、按 index 排序、校验总长；缺片的组标记不完整，不猜内容。"""),
    dict(id="re-075", topic="protocol",
         prompt="怎么还原协议握手状态机？",
         response="""kitty_net action=decode out=logs/net-hs.pcap filter="tcp.port==9001" limit=200
kitty_ghidra action=strings out=logs/gh-client limit=400
判据一：前 4 帧 opcode 固定为 hello/challenge/auth/ready，顺序不随会话变化。
判据二：跳步（直接发 auth）会被服务端以固定错误码拒绝。
收敛：用错误码区分状态违例与字段错误；只把能改变状态迁移的字段纳入状态机。"""),
    dict(id="re-076", topic="protocol",
         prompt="字段类型怎么从流量推断？",
         response="""kitty_net action=decode out=logs/net-type.pcap filter="tcp.port==8088" limit=400
kitty_proto action=decode target=<hex>
判据一：取值集合 < 8 个且稳定出现 → 枚举；取值连续递增 → 计数器。
判据二：长度恒为 8/16/20/32 且高熵 → ID/哈希；长度可变且可打印 → 字符串。
收敛：每类至少 20 个样本再下结论，单样本只能标待定。"""),
    dict(id="re-077", topic="protocol",
         prompt="怎么验证还原出的帧结构是对的？",
         response="""kitty_net action=decode out=logs/net-v.pcap filter="tcp.port==9100" limit=100
kitty_ce op="MEMDUMP_HEX|<resp_va>|64"
判据一：按结构重编码同一帧，字节级与原始帧一致（长度、校验和都重算）。
判据二：重放该帧，服务端回包与原始一致（或仅时间戳不同）。
收敛：两条同时成立才算结构还原完成；只过第一条说明编码对、语义未验证。"""),
    dict(id="re-078", topic="license-interop",
         prompt="许可文件是什么格式，怎么先定性？",
         response="""kitty_patch action=find path=license.dat pattern="7B 22" limit=4
kitty_ce op="MEMDUMP_HEX|<lic_off>|128"
判据一：以 { 开头且含 expiry/feature 等键名 → JSON 明文。
判据二：高熵且长度是 16 的倍数 → 对称加密块；长度 256/512 且首字节 0x30 → ASN.1 签名结构。
收敛：明文直接读字段；加密的先找解密函数（kitty_ida action=functions filter=decrypt）再谈格式。"""),
    dict(id="re-079", topic="license-interop",
         prompt="许可校验函数怎么定位？",
         response="""kitty_ida action=analyze target=app.exe out=logs/ida-lic
kitty_ida action=functions out=logs/ida-lic filter=licen
kitty_ida action=xrefs out=logs/ida-lic filter=<候选地址>
判据一：函数内两次 memcmp，第二次的第二参数来自 .rdata 常量。
判据二：返回 bool 且被启动路径调用（xref 来自 WinMain 或初始化段）。
收敛：kitty_ida action=decompile 看常量内容，是产品名/功能位即确认；再核对失败分支是否只弹窗不改状态。"""),
    dict(id="re-080", topic="license-interop",
         prompt="硬件指纹一般从哪几个点采？",
         response="""kitty_ida action=functions out=logs/ida-app filter=Volume
kitty_ida action=xrefs out=logs/ida-app filter=<串地址>
判据一：卷序列号（GetVolumeInformation）、主板 UUID、网卡 MAC 三类字符串命中 ≥2。
判据二：采集结果拼接后做哈希，哈希值存进许可文件或注册表。
收敛：改动任一采集源后许可失效，即确认该源参与绑定；只记录不改的源不参与。"""),
    dict(id="re-081", topic="license-interop",
         prompt="试用期逻辑怎么找，时钟回拨怎么防？",
         response="""kitty_ida action=functions out=logs/ida-app filter=GetSystemTime
kitty_patch action=find path=app.exe str=lastrun limit=8
判据一：启动时读系统时间并与持久化时间戳比较，差值 < 0 走拒绝分支。
判据二：时间戳写入注册表或 AppData 下文件，写入点在校验之后。
收敛：系统时间回拨 1 天后仍进试用则回拨检测缺失；检测点就在写入点附近。"""),
    dict(id="re-082", topic="license-interop",
         prompt="离线激活的签名怎么验证？",
         response="""kitty_ida action=functions out=logs/ida-act filter=CryptVerify
kitty_ghidra action=strings out=logs/gh-act limit=300
判据一：导入里有 CryptVerifySignature / BCryptVerifySignature 或内置 RSA 验签例程。
判据二：公钥模数（256 字节）在 .rdata，且与激活码里的签名段长度匹配。
收敛：验签通过许可才落盘；只验格式不验签的路径是弱点，修补属于兼容性分析范畴。"""),
    dict(id="re-083", topic="license-interop",
         prompt="网络激活请求里有哪些关键字段？",
         response="""kitty_net action=decode out=logs/net-act.pcap filter="http.request" limit=40
kitty_proto action=decode target=<req_body_hex>
判据一：请求体含 product_id、serial、fingerprint、nonce、signature 五类字段。
判据二：signature 覆盖前四者的拼接，改任一字段签名失效。
收敛：返回体里的 license_blob 是下一步解析对象，先确认签名覆盖范围再动。"""),
    dict(id="re-084", topic="license-interop",
         prompt="许可状态缓存存在哪，怎么找？",
         response="""kitty_ida action=functions out=logs/ida-app filter=RegSetValue
kitty_patch action=find path=app.exe str=SOFTWARE\\ limit=16
判据一：注册表路径含产品名，值名是 License/Activation/State 之类。
判据二：读缓存发生在验签之前（快速路径），验签失败才回源。
收敛：删掉缓存键后启动应重新验签；仍显示已激活说明还有第二处缓存（文件或服务）。"""),
    dict(id="re-085", topic="license-interop",
         prompt="多模块共享校验结果，怎么确认边界？",
         response="""kitty_ida action=analyze target=main.exe out=logs/ida-main
kitty_ida action=functions out=logs/ida-main filter=IsLicensed
判据一：跨模块接口返回枚举（0 未授权、1 试用、2 正式）。
判据二：各模块只读该枚举，不各自重算。
收敛：改一处写入点即影响全部模块，说明边界清晰；若各模块各自校验，需要逐模块定位。"""),
    dict(id="re-086", topic="license-interop",
         prompt="校验失败后的降级路径怎么跟？",
         response="""kitty_ida action=xrefs out=logs/ida-app filter=<校验函数>
kitty_ida action=decompile out=logs/ida-app name=<调用者>
判据一：失败分支是 MessageBox 后继续运行（功能受限），还是 ExitProcess。
判据二：受限模式下功能开关被置 0，且该开关有独立读取点。
收敛：降级路径不等于绕过；确认只读不写、不改变授权状态，才算安全的兼容性处理。"""),
    dict(id="re-087", topic="license-interop",
         prompt="许可级别和功能开关怎么映射？",
         response="""kitty_ghidra action=strings out=logs/gh-app limit=500
kitty_ida action=functions out=logs/ida-app filter=feature
判据一：功能名字符串与许可枚举值成对出现（如 pro→2）。
判据二：开关读取点集中在少数函数，且都先查同一全局变量。
收敛：列一张 功能→最低许可级别 表，与产品文档比对；文档缺失时以实际分支为准。"""),
    dict(id="re-088", topic="license-interop",
         prompt="升级后校验逻辑变了，怎么快速迁移分析？",
         response="""kitty_ida action=analyze target=old.exe out=logs/ida-old
kitty_ida action=analyze target=new.exe out=logs/ida-new
kitty_rea_compare left=<old_fn_json> right=<new_fn_json>
判据一：函数级差分显示相似度 < 0.8，且新增了对新字段的读取。
判据二：常量表新增一项（如新的产品码）。
收敛：只迁移变化部分，未变函数复用旧结论；差异超过 30% 时按新样本重做。"""),
    dict(id="re-089", topic="license-interop",
         prompt="怎么用合法输入复现校验逻辑，确认理解正确？",
         response="""kitty_ida action=decompile out=logs/ida-lic name=<check_fn>
kitty_asm action=assemble code="mov eax, 1; ret" base=0x10000000
kitty_patch action=find path=app.exe str=<产品码> limit=4
判据一：按反编译逻辑手算的合法输入能通过真实校验。
判据二：改动输入任一字节后校验失败，且失败点与反编译分支一致。
收敛：正反两向都过才算理解正确；只过正向说明还有未覆盖的条件。"""),
    dict(id="re-090", topic="mobile",
         prompt="拿到一个 APK，第一步看什么？",
         response="""kitty_apkscan action=scan target=app.apk
kitty_apktool action=decode target=app.apk out=logs/apk-dec
判据一：manifest 的 package、minSdk、targetSdk、权限清单可读，exported=true 的组件能列出。
判据二：签名方案（v1/v2/v3）与证书主体可读。
收敛：先按权限与导出组件画攻击面，再决定是否进 jadx 看代码；不分诊直接反编译会淹在混淆里。"""),
]

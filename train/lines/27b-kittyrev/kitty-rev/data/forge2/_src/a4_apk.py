# -*- coding: utf-8 -*-
"""forge2 A4 · APK 结构（20 条）：manifest 关键位、加固特征、签名 v2/v3、资源混淆。"""
GROUP = "A"
CAT = "kb-re"

ROWS = [
    ("apk-manifest-bits",
     "AndroidManifest.xml 是二进制的，先看哪几个位？",
     "先解成明文：`apktool d -f -s app.apk -o out` 只解资源不反编译 dex，得 `out/AndroidManifest.xml`。"
     "关键位：package、versionCode/Name、uses-sdk(min/target)、application 的 debuggable/allowBackup/usesCleartextTraffic、"
     "以及 exported=true 的组件。判据：`grep -c 'android:exported=\"true\"' out/AndroidManifest.xml` ≥ 1 即有对外组件。"),
    ("apk-axml-magic",
     "怎么确认某个文件是编译后的 AXML 而不是纯文本 XML？",
     "看头 8 字节：AXML 是 `03 00 08 00` + 文件大小，随后是字符串池 chunk `01 00 1C 00`。判据："
     "`xxd -l 16 res/AndroidManifest.xml` 首两字节 03 00 即二进制；用 `file` 命令会误报为 data，别信它。"),
    ("apk-dex-header",
     "dex 头里哪些字段最容易被加固改掉？",
     "三处：checksum(偏移 8)、signature(偏移 12, SHA-1)、file_size(偏移 32)。判据："
     "`xxd -l 112 classes.dex` 看 magic 是否仍为 `64 65 78 0A 30 33 35 00`（dex\\n035\\0）；"
     "若 magic 被改成别的版本号或 file_size 与实际不符，多为壳的占位 dex。"),
    ("apk-dex-count",
     "多 dex 的应用怎么确认有没有漏解？",
     "读 manifest 的 application 是否有 multidex 配置，再数文件：`unzip -l app.apk | grep -c 'classes.*\\.dex'`。"
     "判据：dex 数量应与 `classes.dex`、`classes2.dex`… 连续编号一致，出现跳号说明有 dex 被移除或藏在 assets。"),
    ("apk-shell-signs",
     "怎么判断 APK 被加固（壳）了？",
     "四个信号任一即疑似：① classes.dex 很小（< 8 KB）而 assets 里有大文件；② Application 类指向壳的入口"
     "（如 `com.stub.StubApp`）；③ native 库里出现 `libDexHelper.so` / `libjiagu.so`；④ manifest 里"
     "`android:name` 与 dex 中的类对不上。判据：`unzip -l app.apk | grep -E 'lib.*(jiagu|shell|dexhelper)'` 命中即确认。"),
    ("apk-assets-payload",
     "assets 里有个 20 MB 的 .dat，怎么判断是不是加密的 dex？",
     "看头与熵：真 dex 头是 `dex\\n`；若头被异或过，前 8 字节与 `64 65 78 0A 30 33 35 00` 逐字节异或会得到同一个 key。"
     "判据：`xxd -l 8 assets/x.dat` 与 dex magic 异或后 8 字节全等 → 单字节异或；否则看熵，"
     "> 7.9 且长度是 0x1000 整数倍多为 AES 块。"),
    ("apk-sign-v2",
     "怎么确认 APK 用 v2 签名而不是只有 v1？",
     "看 APK Signing Block：`apksigner verify --verbose app.apk` 会逐项列 v1/v2/v3。判据："
     "v2 块位于中央目录之前，magic 为 `APK Sig Block 42`（16 字节），结束标记前 8 字节是块长；"
     "`grep -abo 'APK Sig Block 42' app.apk` 命中即存在 v2。"),
    ("apk-sign-v3",
     "v3 与 v2 的差别在文件里怎么体现？",
     "v3 多一个 signer 的 minSdk/maxSdk 范围与 proof-of-rotation 结构，块 ID 为 0x1b93ad61（v2 是 0x7109871a）。判据："
     "`apksigner verify -v --print-certs app.apk` 显示 `Verified using v3 scheme: true`；"
     "手工解析时按 ID 读块，v3 条目内含 attr 0x3ba06f8c 的轮转 lineage。"),
    ("apk-sign-mismatch",
     "重打包后报签名不一致，怎么定位是哪个方案挂了？",
     "分方案验：`apksigner verify --verbose --min-sdk-version 21 app.apk` 会分别给 v1/v2/v3 结果。判据："
     "v1 过而 v2 挂 → 改过文件但没重签 v2（v2 覆盖全文件）；v1 挂 v2 过 → META-INF 里的摘要被改；"
     "两者都挂看 `jarsigner -verify -verbose` 的首个 `java.util.zip.ZipException`。"),
    ("apk-zipalign",
     "为什么要 zipalign，错位会怎样？",
     "未对齐的条目在 mmap 时需拷贝，v2 签名也要求 4 字节对齐。判据：`zipalign -c -v 4 app.apk` 输出 "
     "`Verification FAILED` 的条目就是错位项；重打包后必须 `zipalign -f 4 in.apk out.apk` 再 `apksigner sign`，"
     "顺序反了会让 v2 校验失败。"),
    ("apk-res-obf",
     "资源混淆怎么识别（resources.arsc 被改）？",
     "看 arsc 里的资源名是否被替换成短串：`apktool d app.apk` 后 `out/res/values/strings.xml` 里 name 全为 a/b/c，"
     "或 arsc 字符串池中出现大量 `a`、`b`。判据：`xxd -s 0 -l 12 res/arsc` 头为 `02 00 0C 00`（RES_TABLE_TYPE），"
     "其后字符串池条目数远大于可见资源数即被压过。"),
    ("apk-arsc-header",
     "resources.arsc 的块结构怎么快速验证完整性？",
     "按 chunk 遍历：每块 8 字节头（type 2 字节 + headerSize 2 字节 + size 4 字节），type 0x0002 是表头、"
     "0x0001 是字符串池、0x0200 是包。判据：累加各块 size 应等于文件长度；"
     "不等说明尾部被追加（常见于加固把载荷塞在 arsc 之后）。"),
    ("apk-native-libs",
     "lib/ 下同名 so 有多个 ABI，怎么确认是同一份逻辑？",
     "比导出与大小：`for d in lib/*; do echo $d; readelf --dyn-syms -W $d/libx.so | wc -l; done`。判据："
     "各 ABI 的导出符号数应一致（差分 < 5%），大小差异来自指令编码而非逻辑；"
     "若 arm64 版本多出 `JNI_OnLoad` 而 armeabi-v7a 没有，说明只给 64 位做了动态注册。"),
    ("apk-jni-register",
     "so 里动态注册的 native 方法怎么和 Java 对上？",
     "走 JNI_OnLoad → RegisterNatives：在 so 里搜 `RegisterNatives` 的导入，"
     "再看传给它的 JNINativeMethod 数组（每项 3 指针）。判据：`readelf --dyn-syms libx.so | grep RegisterNatives` 命中，"
     "且 JNI_OnLoad 里 `FindClass` 的字符串能在 `strings -a` 找到对应类名。"),
    ("apk-dex-stringid",
     "想在 dex 里快速定位某个字符串的引用，怎么走？",
     "三步：`strings -a classes.dex | grep -n <目标>` 先确认在；再用 `jadx -d out app.apk` 反编译后全文搜；"
     "或直接读 string_ids 表（偏移 0x3C 处 4 字节为 string_ids_size，0x40 为 off）。判据："
     "string_ids_off + i*4 指向的 data 项首字节是 uleb128 长度，长度与字符串字节数一致才算命中。"),
    ("apk-manifest-perm",
     "怎么快速列出危险权限与它们的声明位置？",
     "`aapt dump permissions app.apk` 直接出 uses-permission 列表；`apktool` 出来的 manifest 里"
     "`grep 'uses-permission' -A1` 看具体名。判据：危险组集中在 SMS/CALL_LOG/CONTACTS/LOCATION，"
     "与业务无关的（如 READ_SMS + 无短信功能）优先看其调用点。"),
    ("apk-exported",
     "exported=true 的 Activity 怎么确认真的能被外部拉起？",
     "需要同时满足：exported=true、无 permission 保护、intent-filter 或显式组件名可达。判据："
     "`grep -B2 -A6 'android:exported=\"true\"' out/AndroidManifest.xml` 看该组件是否带 "
     "`android:permission`；用 `adb shell am start -n pkg/.Act` 在自有测试机上验证返回 `Starting:` 而非 `Permission Denial`。"),
    ("apk-debuggable",
     "debuggable 标志怎么影响后续分析？",
     "debuggable=true 允许 `run-as` 与 JDWP 附加。判据：manifest application 上 "
     "`android:debuggable=\"true\"`（或 build 里 debuggable 变体）；运行时 `adb shell run-as <pkg> id` "
     "返回 uid 而非 `Package ... is not debuggable` 即确认。"),
    ("apk-split-apks",
     "split APK（.apks / base + config）怎么合起来分析？",
     "先看 base 的 manifest 是否含 `android:isFeatureSplit` 与 split 名；合并用 `apktool` 逐包解再对齐资源。"
     "判据：`unzip -l app.apks | grep split_config` 出现 ABI/密度分包；"
     "`bundletool build-apks --mode=universal` 可产出单包用于静态比对。"),
    ("apk-dex-try-catch",
     "dex 里 try/catch 表被清掉会怎样？",
     "方法体仍能反编译但异常路径丢失，控制流看起来像直线。判据：`jadx` 输出的方法里没有 try 块，"
     "而 smali 中 `code_item` 的 tries_size 字段（方法体头偏移 0x0C 处 2 字节）为 0；"
     "若该方法里仍有 `throw` 指令却无 try，说明表被改过。"),
]

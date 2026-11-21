# src/ 与 lib/ 的关系（2026-11-21 定档）

## 结论

**`lib/index.js` 是唯一真相源（single source of truth）。`src/*.ts` 是 2026-11-12 之前的旧版骨架，已停止维护。**

## 为什么

```text
lib/index.js   153 KB · 纯 ESM · 无需编译 · 直接由 DSH 加载（运行时产物）
              包含全部实装能力：门控、文本工具协议、意图路由、压缩提示词、
              统计、launcher、listModels、续写/密度护栏…
src/*.ts       合计 45 KB · 只是早期骨架
              grep 结果：compactSystemText / textToolProtocol / gateHit /
              holdText / nsfwGate 在 src 里 0 命中
→ 二者不是"编译产物"关系，src 也不是 lib 的上游；lib 是手写运行时文件
```

## 纪律

1. **改适配器只改 `lib/index.js`**，改前 `cp lib/index.js lib/index.js.bak-<主题>-<ts>`，改后 `node --check`，并在 `PATCHES.md` 追加一节
2. `src/*.ts` 只当历史参考：不要按它重建 lib，也不要以为它和 lib 同步
3. 重建环境时：直接把 `lib/` 复制过去即可（`package.json` 的 `main` 指向 `lib/index.js`，无需 build）
4. `lib/` 在本目录 `.gitignore` 里被排除，但仓库根已 `git add -f lib/index.js` 强制纳入版本控制——
   因为不带它就复现不出当前行为；新增 lib 文件时同样用 `-f`

## 若将来要回到 TypeScript

那是一次独立的搬迁工作（不是"同步"）：需要以 `lib/index.js` 为行为规范，重写 `src/`，
再用行为回归（`_work/quant/harness_dsh_adapt.mjs`、`harness_effort_matrix.mjs`、
`probe_kitty_routing.mjs`、`test_nsfw_density.mjs`）逐项对齐后才可替换。当前不做。

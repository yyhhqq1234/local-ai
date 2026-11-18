# 退役记录：@dsh-external/dsh-ninfer-local（2026-11-18）

## 起因

插件面板显示 `@dsh-external/dsh-ninfer-local` 异常：
`an adapter for provider "ninfer" is already registered`。

根因：该包（2026-11-08 版）与 `plugins/dsh-local-ai`（2026-11-12 主线）同源，
两者 `cordis.patch.yml` 都写 `registerAdapter: true` 且 provider 同为 `ninfer`。
`llm.registerAdapter()` 对已注册 provider 抛 `LlmError(DUPLICATE_ADAPTER)`（all-or-nothing），
后加载者整个 fiber 变 `[failed]`。旧包 `engineDir` 还指向已废弃的 `ninfer-csunx`
/ `_tools/ninfer-build`，模型路径全为死链。

## 处置（操作者 2026-11-18 批准「彻底摘除」）

```
1) plugins/dsh-ninfer-local/lib/index.js      加 listProviders() 预检 + ctx.effect 内 try/catch
                                              （DUPLICATE_ADAPTER 只放弃路由，不再打挂 fiber）
2) plugins/dsh-ninfer-local/cordis.patch.yml  disabled: true / registerAdapter: false
3) profiles/desktop/package.json  deps:7      删除该 link 依赖（bundles 早已不含）
4) profiles/desktop/node_modules/@dsh-external/dsh-ninfer-local   junction 删除（rmdir）
5) plugins/dsh-ninfer-local → _work/retired/dsh-ninfer-local-20261118
```

## 备份

```
工作区：_work/ops/desktop-package.json.bak-20261118223332
profile：~/.dsh/profiles/desktop/package.json.bak-rmninfer-1795012421136
归档：  _work/retired/dsh-ninfer-local-20261118（含 lib/index.js.bak-dupfix-20261115023743）
```

## 回滚

```powershell
Copy-Item "$env:USERPROFILE\.dsh\profiles\desktop\package.json.bak-rmninfer-1795012421136" `
          "$env:USERPROFILE\.dsh\profiles\desktop\package.json" -Force
pnpm --dir "$env:USERPROFILE\.dsh\profiles\desktop" install --offline
Move-Item "D:\BaiduNetdiskDownload\Local-AI\_work\retired\dsh-ninfer-local-20261118" `
          "D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-ninfer-local"
# 需要它重新出模型路由时：cordis.patch.yml 里 disabled 去掉、registerAdapter 改 true
# 且必须把 provider 改成非 'ninfer'（例如 ninfer27b），否则仍与主线撞名
```

## 验证（摘除后）

```
llm.listProviders()  → ninfer 唯一（NInfer 本地 · 5070Ti 12G）
ninfer_status        → profile=llama-cpp / 8080 / kittyrev9b-Q5_K_M-im.gguf
plugins/             → _scaffold-ref, dsh-local-ai
profile deps/bundles → 均不含 @dsh-external/dsh-ninfer-local
node_modules junction→ 已不存在
```

## 遗留

- 面板（插件包清单）若仍显示该行，是前端缓存：先 Ctrl+F5；仍不行则重启 DSH（inventory 在启动时扫描 profile）。
- 27B 侧若要单独暴露一个可选 provider，须另开包（不要复用 `ninfer` 这个名字）。

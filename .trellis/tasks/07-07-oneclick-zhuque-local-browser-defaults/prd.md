# Windows 一键包本机朱雀链路标准化

## 背景

本地源码运行已验证：`AI检测 + 降重` 在非 browser-agent 模式下会使用本机可见浏览器链路，点击「打开朱雀页面」后打开/聚焦本机朱雀窗口，并可同步朱雀账号与剩余次数。

Windows 一键包需要继承这套默认行为，普通用户不应安装 Chrome 插件，也不应被引导手动启动 CDP/Profile。当前一键包模板和启动脚本还没有显式写入 Zhuque 本地浏览器默认配置，后续打包可能因为默认/历史 `.env` 漂移导致体验不一致。

## 目标

1. 一键包首次运行生成的 `.env` 默认包含本地 Zhuque 浏览器配置：
   ```env
   ZHUQUE_DETECT_TRANSPORT=auto
   ZHUQUE_DETECT_HEADLESS=false
   ZHUQUE_DETECT_AUTO_SYSTEM_BROWSER=true
   ZHUQUE_SERVER_HEADLESS_FALLBACK=false
   ```
2. `runtime/start.ps1` 对已有 `.env` 缺失这些键的用户自动补齐默认值。
3. 一键包 README 说明：
   - 本地一键包不需要 Chrome 插件。
   - 点击「打开朱雀页面」后使用本机可见 Chrome/Edge/Brave。
   - 如需强制指定浏览器，可设置 `ZHUQUE_DETECT_BROWSER_EXECUTABLE`。
4. 一键包内置打开朱雀页面不依赖 `zhuque_pkg/capture_zhuque_creds.py` 外部脚本；legacy 脚本仅作源码兼容兜底。
5. PyInstaller 显式收集 Playwright Python 控制代码，但不打包 Chromium 浏览器本体。
6. 保持 VPS/browser-agent 文档和代码不变。
7. 加静态测试覆盖一键包模板/启动脚本/README 的本地朱雀默认值。

## 非目标

- 本轮不删除 `zhuque_pkg`。
- 本轮不把 Playwright Chromium 打包进一键包。
- 本轮不改 browser-agent 插件。
- 本轮不发布 GitHub Release；只准备代码和构建命令。

## 验收标准

- `package/windows-oneclick/.env.template` 包含本地 Zhuque 默认配置。
- `package/windows-oneclick/runtime/start.ps1` 会 `Set-Default` 并 `Write-DotEnv` 持久化本地 Zhuque 配置。
- `package/windows-oneclick/README.txt` 明确一键包 Zhuque 使用本机浏览器，不需要插件。
- 测试通过：
  ```bash
  package/venv/bin/python -m pytest package/backend/tests/test_frontend_redeem_entry.py -q -k oneclick
  ```
- 构建命令文档明确：
  ```powershell
  cd package
  .\build-oneclick.ps1 -PostgresZip C:\path\postgresql-windows-x64-binaries.zip -CreateZip
  ```

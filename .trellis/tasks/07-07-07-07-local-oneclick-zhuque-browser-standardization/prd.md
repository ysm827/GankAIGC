# 本地/一键包朱雀浏览器链路标准化

## 背景

VPS/Docker 朱雀检测已经走 browser-agent 插件链路，避免服务器 headless 触发朱雀验证码/风控。本地源码运行和 Windows 一键包不应强制用户安装插件，而应自动托管本机可见 Chrome/Edge/Brave，复用一个朱雀窗口完成登录、验证码、检测和剩余次数同步。

当前本地链路仍散落在兼容捕获工具、`ZhuqueService`、`ZhuqueAPI` 与旧命名接口中，用户文案仍偏“扫码登录/无头 API”，不利于后续一键包体验标准化。

## 目标

第一阶段先做低风险标准化：

1. 增加本地浏览器传输层包装，明确 `local_browser` 语义。
2. 新增/暴露更清晰的本地朱雀接口，前端可调用“打开本机朱雀页面 / 同步本机朱雀状态”。
3. 工作台在非 browser-agent 模式下展示“本机浏览器模式”，不显示插件配对入口。
4. 保留 legacy 本地窗口兜底能力，不重写检测核心，不删除旧接口。
5. 更新 README 中本地/一键包链路说明；VPS 插件链路保持不变。

## 非目标

- 不删除 legacy 本地窗口兜底能力。
- 不重写 `ZhuqueAPI.detect()` 页面检测核心。
- 不改变 VPS `browser_agent` 插件链路。
- 不本轮打包 Windows 一键包产物。
- 不要求本地用户安装 Chrome 插件。

## 用户体验验收

### 本地源码 / 一键包模式

- 工作台选择 `AI检测 + 降重` 后，朱雀卡片展示：
  - `检测传输：本机浏览器模式`
  - `朱雀账号：xxx / 已登录 / 未登录`
  - `剩余次数：N 次 / 检测后同步`
- 主按钮为 `打开朱雀页面` 或等价文案，不再主推 VPS 插件配对。
- 点击打开时：
  - 优先聚焦已存在的本机朱雀检测窗口；
  - 没有窗口才通过 legacy `zhuque_capture_window.py --sync-session` 打开一个专用窗口；
  - 不要求用户手动运行 PowerShell/CDP 命令。
- 点击同步时读取当前用户隔离目录下状态，刷新账号和剩余次数。

### VPS/browser-agent 模式

- 原插件流程保持不变：配对码、插件在线、打开朱雀登录、剩余次数同步都继续可用。
- 本地新增接口不能触发 VPS server-headless 朱雀检测。

## 技术验收

- 新增 `LocalBrowserZhuqueTransport` 或等价包装层，提供：
  - `status()`
  - `open_page()`
  - `sync_status()`
  - `focus_window()`
  - `detect()`
- 新增 API 客户端函数和后端路由时需保持旧路由兼容。
- 新增静态测试覆盖本地模式 UI 文案、新 API 函数、VPS 插件文案不回退。
- 更新 README / package README。
- 构建并同步 `package/static`。

## 风险

- 本地浏览器/CDP/Playwright 跨 Windows/WSL/Linux 行为复杂；第一阶段只封装和统一入口，不大幅改底层启动逻辑。
- 旧 standalone Zhuque 包与 backend `zhuque_api.py` 曾存在重复逻辑；第一阶段不清理，避免破坏一键包。

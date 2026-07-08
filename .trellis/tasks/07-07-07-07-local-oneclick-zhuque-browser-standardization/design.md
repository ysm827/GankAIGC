# 设计：本地/一键包朱雀浏览器链路标准化

## 约束

- VPS `browser_agent` 不动。
- 本地默认 `ZHUQUE_DETECT_TRANSPORT=auto`，行为应等价本机浏览器链路。
- 当前 `ZhuqueService` 已能在非 browser-agent 时使用 `ZhuqueAPI` 与内部兼容捕获工具，第一阶段包装现有能力。
- 当前 per-user 目录已迁到 `package/data/zhuque/users/user_<id>/` 或 `ZHUQUE_USER_DATA_DIR`。

## 数据流

### 本地打开页面

```text
WorkspacePage
  → POST /api/optimization/zhuque/local/open
  → LocalBrowserZhuqueTransport.open_page()
  → ZhuqueService.focus_detection_window()
     ├─ 成功：聚焦现有检测页，返回 reused
     └─ 失败：fallback 到 package/backend/app/tools/zhuque_capture_window.py --sync-session
  → 返回统一状态 payload
```

### 本地同步状态

```text
WorkspacePage
  → POST /api/optimization/zhuque/local/sync
  → LocalBrowserZhuqueTransport.sync_status()
  → ZhuqueAPI.status() / credential_status() / readiness refresh
  → 返回 connected/user_name/remaining_uses/button_enabled/message
```

### 本地检测

```text
OptimizationService
  → ZhuqueService.detect()
  → 非 browser-agent 时仍用现有 ZhuqueAPI.detect()
```

第一阶段 `detect()` 只通过包装层暴露等价能力，不改变核心检测。

## 新增/调整文件

- `package/backend/app/services/zhuque_local_browser_transport.py`
  - 包装当前用户的 `ZhuqueService`。
  - 统一本地状态返回字段。
- `package/backend/app/routes/optimization.py`
  - 新增：
    - `POST /api/optimization/zhuque/local/open`
    - `POST /api/optimization/zhuque/local/sync`
    - `POST /api/optimization/zhuque/local/focus`
  - 旧 `/zhuque/browser/start?mode=local_window` 保持兼容。
- `package/frontend/src/api/index.js`
  - 新增 local Zhuque API 函数。
- `package/frontend/src/pages/WorkspacePage.jsx`
  - 非 browser-agent 模式主按钮从“扫码登录/已登录”标准化为本机浏览器动作。
  - 本地刷新按钮调用 local sync。
- README 文档。

## 统一状态 payload

```json
{
  "transport": "local_browser",
  "auth_mode": "local_browser",
  "login_mode": "local_browser",
  "ready": true,
  "connected": true,
  "page_found": true,
  "has_token": true,
  "user_name": "木木",
  "remaining_uses": 19,
  "quota_text": "剩余 19 次",
  "button_enabled": true,
  "message": "本机朱雀页面已登录",
  "actions": []
}
```

## 错误处理

- 找不到浏览器/Playwright：返回 `manual_required` + 中文动作说明，不让用户自己猜。
- 已有窗口：优先 `reused`，不重复打开。
- 无状态：返回 `ready=false` / `connected=false` / `remaining_uses=-1`，前端显示 `检测后同步`。

## 测试

- 后端：新增/扩展 `test_zhuque_integration.py` 覆盖 local open/sync/focus 路由。
- 前端静态：覆盖 local API 函数和工作台本地模式文案。
- 构建：`npm run build` 并同步 `package/static`。

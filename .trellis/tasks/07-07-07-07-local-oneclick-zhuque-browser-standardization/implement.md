# 实施清单

## Phase 1：计划与约束

- [x] 写 PRD。
- [x] 写设计。
- [x] 启动任务。

## Phase 2：后端本地传输层

- [x] 新建 `zhuque_local_browser_transport.py`。
- [x] 包装当前用户 `ZhuqueService`，提供 `status/open_page/sync_status/focus_window/detect`。
- [x] 在 `optimization.py` 增加 local open/sync/focus 路由。
- [x] 保持旧 `browser/start?mode=local_window` 行为兼容。

## Phase 3：前端本地模式 UI

- [x] `api/index.js` 新增 local Zhuque API 函数。
- [x] `WorkspacePage.jsx` 非 browser-agent 模式主按钮改为打开本机朱雀页面。
- [x] 本地同步按钮调用 local sync。
- [x] VPS browser-agent 模式不回退。

## Phase 4：文档

- [x] README 补本地/一键包链路标准化说明。
- [x] package/README 补本地/一键包默认配置说明。

## Phase 5：测试与构建

- [x] 后端 local route 测试。
- [x] 前端静态测试。
- [x] `cd package/frontend && npm run build`。
- [x] 同步 `package/static`。
- [x] 目标 pytest。

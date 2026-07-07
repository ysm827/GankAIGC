# 实施清单

## Phase 1：计划

- [x] 创建任务。
- [x] 写 PRD。
- [x] 写设计。
- [x] 启动任务。

## Phase 2：实现

- [x] 更新 `package/windows-oneclick/.env.template`。
- [x] 更新 `package/windows-oneclick/runtime/start.ps1` 的默认值和写出字段。
- [x] 更新 `package/windows-oneclick/README.txt`。
- [x] 更新 `package/app.spec`，确保 PyInstaller 收入 Playwright 控制代码。
- [x] 新增/更新静态测试。

## Phase 3：验证

- [x] `package/venv/bin/python -m pytest package/backend/tests/test_release_workflow.py -q`
- [x] `package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q -k 'local_browser_transport_opens_builtin_page or local_open or local_sync or reuses_existing_detection_window'`
- [x] `git diff --check`
- [ ] 如改动前端静态资源则重建；本任务不需要重建前端。

## 打包命令

Windows PowerShell：

```powershell
cd package
.\build-oneclick.ps1 -PostgresZip C:\path\postgresql-windows-x64-binaries.zip -CreateZip
```

或已有解压目录：

```powershell
cd package
.\build-oneclick.ps1 -PostgresRoot C:\pgsql -CreateZip
```

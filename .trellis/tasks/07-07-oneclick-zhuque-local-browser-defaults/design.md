# 设计：Windows 一键包本机朱雀链路标准化

## 范围

本任务修改一键包配置模板、启动脚本、README、PyInstaller spec 和静态测试，并补一个后端内置本机朱雀页面打开方法；不改 Zhuque 检测/结果解析核心。

## 当前链路

```text
start.bat
  → runtime/start.ps1
  → Ensure-EnvFile()
  → Write-DotEnv()
  → GankAIGC.exe 读取 .env
  → WorkspacePage 本地模式 openZhuqueLocalBrowser()
  → LocalBrowserZhuqueTransport.open_page()
  → ZhuqueService.open_detection_page()
  → ZhuqueAPI.open_detect_page()
```

同步朱雀账号/剩余次数：

```text
WorkspacePage refresh
  → LocalBrowserZhuqueTransport.sync_status()
  → ZhuqueService.refresh_free_quota()
  → ZhuqueAPI._peek_quota_status_with_page()
  → 复用/打开本机可见朱雀页面读取按钮文本、账号名、localStorage token
```

一键包不打包 Playwright Chromium 浏览器本体，因此 quota sync 禁止启动 `pw.chromium.launch(headless=True)` 的 bundled browser 路径。

## 设计

### `.env.template`

增加 Zhuque 本地默认值：

```env
ZHUQUE_DETECT_TRANSPORT=auto
ZHUQUE_DETECT_HEADLESS=false
ZHUQUE_DETECT_AUTO_SYSTEM_BROWSER=true
ZHUQUE_SERVER_HEADLESS_FALLBACK=false
ZHUQUE_DETECT_BROWSER_EXECUTABLE=
```

### `runtime/start.ps1`

- `Ensure-EnvFile()` 中 `Set-Default` 上述键。
- `Write-DotEnv()` 把这些键写入持久化 `.env`。
- 这样首次运行和旧包升级缺失键时都会补齐。

### 后端内置打开本机朱雀页面

一键包里 `sys.executable` 是 `GankAIGC.exe`，不能当普通 Python 解释器去执行内部兼容捕获工具。因此 `LocalBrowserZhuqueTransport.open_page()` 必须先调用内置 `open_detection_page()`，成功后不走 legacy capture script。legacy script 只保留为源码/兼容兜底。

### PyInstaller spec

`playwright` 在后端里是动态导入；一键包必须显式加入 `hidden_imports` / `collect_submodules` / `collect_data_files`，确保 exe 内有 Playwright Python driver 控制代码。浏览器本体仍优先使用用户系统 Chrome/Edge/Brave，不打包 Chromium 浏览器。

### README

`windows-oneclick/README.txt` 增加：

```text
朱雀 AI 检测/降重：一键包默认使用本机可见浏览器，不需要安装 Chrome 插件。
```

并说明强制指定 Edge/Brave 的 `.env` 示例。

### 测试

在现有静态测试文件中新增一键包断言，读取：

- `package/windows-oneclick/.env.template`
- `package/windows-oneclick/runtime/start.ps1`
- `package/windows-oneclick/README.txt`

断言模板、启动脚本、README 三方一致。

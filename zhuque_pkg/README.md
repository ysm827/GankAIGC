# 朱雀无头 API 工具包

本目录是 GankAIGC 使用的朱雀新链路：

1. `capture_zhuque_creds.py`：只负责一次性打开朱雀页面，完成微信扫码授权并保存 `creds_latest.json`。
2. `zhuque_api.py`：读取 `creds_latest.json`，直接调用朱雀 WebSocket API 完成文本检测。

检测链路不依赖旧版本地页面控制/调试端口。可见浏览器只用于扫码授权页；凭证保存后，后续检测走无头 API。

## 安装

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

在 WSL / Linux 受限环境中，浏览器内核可装到项目内可写目录：

```bash
PLAYWRIGHT_BROWSERS_PATH=../package/.playwright-browsers python -m playwright install chromium
```

## 微信扫码保存凭证

```bash
python capture_zhuque_creds.py
```

常用命令：

```bash
python capture_zhuque_creds.py --switch             # 退出旧账号后重新扫码
python capture_zhuque_creds.py --load               # 查看当前凭证摘要
python capture_zhuque_creds.py --export-json-creds  # 导出给无头 API 使用的 JSON
```

输出文件：

| 文件 | 说明 |
| --- | --- |
| `creds_latest.json` | 最新朱雀凭证，GankAIGC 默认读取它 |
| `creds_YYYYMMDD_HHMMSS.json` | 历史凭证备份 |
| `browser_state.json` | Playwright 会话缓存 |
| `qrcode_latest.png` | 二维码截图，便于排查扫码页 |

## 无头 API 调用

```python
import asyncio
from zhuque_api import ZhuqueAPI

async def main():
    api = ZhuqueAPI()
    print(api.credential_status())
    result = await api.detect("需要检测的长文本" * 50)
    print(result)

asyncio.run(main())
```

可用环境变量：

- `ZHUQUE_CREDENTIALS_FILE`：覆盖凭证文件路径。
- `ZHUQUE_CHROME_EXECUTABLE`：扫码授权页使用的 Linux Chrome/Chromium 路径。
- `PLAYWRIGHT_BROWSERS_PATH`：Playwright 浏览器内核目录。

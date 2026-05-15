# GankAIGC 安全修复计划

> **勾选规则：** 每个修复项一开始都保持未勾选。只有在代码修复完成，并且对应验证命令通过后，才把该项从 `- [ ]` 改成 `- [x]`。

**目标：** 修复 2026-05-14 安全审计发现的问题，同时尽量不改变无关业务行为。

**范围：** 本计划覆盖 `package/` 下的一体化 FastAPI/React 应用、Docker 部署文件、依赖锁文件，以及必要的安全回归测试。

**优先级：** 先修复可被外部直接利用、可能泄露凭据的问题；再修 SSRF、特权运维操作、依赖漏洞和浏览器侧加固。

---

## 当前问题总览

| 编号 | 严重程度 | 状态 | 问题 | 主要文件 |
| --- | --- | --- | --- | --- |
| SEC-001 | 严重 | 已完成 | 未登录路径穿越，可读取 `package/static` 外的服务端文件 | `package/main.py` |
| SEC-002 | 高危 | 已完成 | 用户可控模型 `base_url` 会造成后端 SSRF | `provider_config_service.py`、`optimization.py`、`ai_service.py`、`word_formatter/routes.py` |
| SEC-003 | 高危 | 待修复 | Docker 在线更新挂载 Docker socket，并执行配置中的 shell 命令 | `docker-compose.yml`、`update_service.py`、`admin.py` |
| SEC-004 | 高危 | 已完成 | 前端生产依赖存在已知安全公告 | `package/frontend/package.json`、`package-lock.json` |
| SEC-005 | 高危/中危 | 已完成 | 后端依赖存在已知安全公告 | `package/backend/requirements.txt`、`package/requirements.txt` |
| SEC-006 | 中危 | 已完成 | Word Formatter 上传接口先完整读入内存再检查大小，默认无限制 | `word_formatter/routes.py`、`config.py` |
| SEC-007 | 中危 | 已完成 | 管理后台配置接口会把完整系统模型 API Key 返回给浏览器 | `admin.py`、`ConfigManager.jsx` |
| SEC-008 | 中低危 | 已完成 | 浏览器 token 存在 `localStorage`，安全响应头不足 | `api/index.js`、`AdminDashboard.jsx`、应用中间件 |

---

## SEC-001：静态文件路径穿越

**风险说明：** 未登录请求可以读取 `package/static` 目录之外的文件。已确认请求 `GET /%2e%2e%2fmain.py` 会返回 `package/main.py` 源码。

**修复思路：** 服务静态文件前，先对请求路径做解码、规范化和真实路径校验。任何解析后落在 `STATIC_DIR` 外的路径都拒绝。

**实施清单：**

- [x] 新增回归测试 `package/backend/tests/test_package_static_security.py`，导入 `package/main.py` 时使用安全的测试环境变量，并断言这些请求都返回 `404`：
  - `/%2e%2e%2fmain.py`
  - `/..%2Fmain.py`
  - `/%2E%2E/main.py`
  - `/%2e%2e%2f.env`
- [x] 新增正向测试：确认 `package/static` 内真实存在的文件仍能正常返回。
- [x] 修改 `package/main.py` 的静态文件兜底路由：
  - 安全解码路由路径；
  - 拒绝绝对路径和包含 `..` 的路径；
  - 计算 `static_root = Path(STATIC_DIR).resolve()`；
  - 计算 `target = (static_root / file_path).resolve()`；
  - 只有当 `target.is_relative_to(static_root)` 且 `target.is_file()` 时才返回文件。
- [x] 保留合法 SPA 路由回退到 `index.html` 的行为。
- [x] 运行 `cd package/backend; python -m pytest tests/test_package_static_security.py -q`。
- [x] 运行 `cd package/backend; python -m pytest -q`。

**完成标准：** 编码后的路径穿越请求不再能返回源码、配置或其他服务端文件；正常前端资源和 SPA 路由仍可用。

---

## SEC-002：BYOK 模型地址 SSRF

**风险说明：** 已登录用户可以保存或提交任意 `base_url`。后端随后会通过 `AsyncOpenAI` 主动请求这些地址，攻击者可能借此访问内网服务、localhost、云厂商元数据地址或攻击者控制的地址。

**修复思路：** 增加一个统一的模型服务 URL 校验器。保存用户自带 API 配置、提交临时 BYOK 配置、后台模型配置、健康检查和 Word Formatter BYOK 路径都必须共用这套校验。

**实施清单：**

- [x] 新建 `package/backend/app/utils/url_security.py`。
- [x] 实现 `validate_external_https_url(value: str) -> str`，规则如下：
  - 必须是 `https://`；
  - 必须有 hostname；
  - 禁止 URL 中带用户名密码；
  - 禁止 `localhost`、`.localhost` 和单标签域名；
  - 使用 `socket.getaddrinfo` 解析 DNS；
  - 所有解析出的 IPv4/IPv6 地址都不能是 loopback、private、link-local、multicast、reserved、unspecified；
  - 禁止云元数据地址，例如 `169.254.169.254`；
  - 只去掉末尾 `/`，不要破坏原有路径。
- [x] 新增测试 `package/backend/tests/test_url_security.py`，覆盖允许的公网 HTTPS URL，以及应拒绝的 localhost、私网、link-local、http、带用户名密码 URL。
- [x] 在 `ProviderConfigService.save_config` 中使用该校验器。
- [x] 在保存 `OptimizationCreate.polish_config/enhance_config/emotion_config.base_url` 前使用该校验器。
- [x] 在后台模型配置保存或模型连接测试前使用同一个校验器。
- [x] 在 Word Formatter BYOK 服务创建前使用同一个校验器。
- [x] 增加安全本地代理兼容模式：
  - 默认仍只允许公网 HTTPS Base URL；
  - 只有 `ALLOW_LOCAL_MODEL_PROXY=true` 且当前热加载后的 `SERVER_HOST` 为 `127.0.0.1`、`localhost` 或 `::1` 时，才允许本地 HTTP 代理；
  - 本地代理只允许 `127.0.0.1`、`localhost`、`::1`、`host.docker.internal`，并且必须显式填写合法端口；
  - `SERVER_HOST=0.0.0.0`、公网 `http://`、`192.168.*`、`10.*`、`172.16-31.*` 继续拒绝。
- [x] 运行 `cd package/backend; python -m pytest tests/test_url_security.py tests/test_provider_config_api.py tests/test_optimization_billing.py -q`。
- [x] 运行 `cd package/backend; python -m pytest -q`。

**完成标准：** 后端在创建任何出站请求前，就拒绝内网地址、localhost、非 HTTPS 地址和云元数据地址。

---

## SEC-003：Docker 在线更新权限边界

**风险说明：** app 容器挂载了 `/var/run/docker.sock`，并且后台可以触发 shell 命令控制 Docker。如果后台凭据或 JWT 密钥泄露，风险会扩大到宿主机 Docker 控制权。

**修复思路：** 默认关闭在线更新能力，默认 app 服务不挂 Docker socket。更新应尽量作为显式运维流程，而不是普通 app 容器可触发的宿主机控制能力。

**实施清单：**

- [ ] 将 `package/backend/app/config.py` 中的 `VPS_UPDATE_ENABLED` 默认值改为 `False`。
- [ ] 从 `docker-compose.yml` 默认 `app` 服务中移除 Docker socket 挂载。
- [ ] 保留独立 `updater` profile，并在文档中明确说明启用它等于授予 Docker 控制能力。
- [ ] 将 `update_service.start_vps_update` 中的 `subprocess.Popen(..., shell=True)` 改成固定 argv 命令，或在未显式配置时完全禁用直接命令执行。
- [ ] 如果仍保留命令执行，只允许固定的 compose 更新命令，拒绝任意 `VPS_UPDATE_COMMAND`。
- [ ] 确保 `/api/admin/update/run` 在未满足所有显式开启条件时返回清晰的禁用提示。
- [ ] 更新 `docs/docker-deployment.md`，说明在线更新的安全边界和风险。
- [ ] 运行 `cd package/backend; python -m pytest tests/test_admin_update_api.py tests/test_docker_compose.py -q`。

**完成标准：** 默认 Docker 部署中，app 容器不再拥有 Docker socket 控制权；在线更新无法被改造成任意 shell 命令执行。

---

## SEC-004：前端依赖安全公告

**风险说明：** `npm audit --omit=dev --json` 报告生产依赖存在安全问题，涉及 `axios`、`react-router-dom`、`react-router`、`@remix-run/router`、`follow-redirects`。

**修复思路：** 将生产依赖升级到安全版本，同时保持现有 React/Vite 应用兼容。升级后重新构建并尽量运行 e2e 测试。

**实施清单：**

- [x] 将 `axios` 升级到当前审计建议的安全版本。
- [x] 升级 `react-router-dom`，确保其传递依赖 `react-router` 和 `@remix-run/router` 的安全公告被清除。
- [x] 使用选定版本刷新 `package/frontend/package-lock.json`。
- [x] 运行 `cd package/frontend; npm audit --omit=dev`。
- [x] 运行 `cd package/frontend; npm run build`。
- [x] 如果浏览器测试依赖可用，运行 `cd package/frontend; npm run test:e2e`。

**完成标准：** 前端生产依赖审计不再有 high/moderate 问题，并且前端构建通过。

---

## SEC-005：后端依赖安全公告

**风险说明：** `uvx pip-audit -r requirements.txt -f json` 报告 `fastapi`、`python-multipart`、`starlette`、`python-jose`、`python-dotenv` 和测试依赖 `pytest` 存在已知问题。

**修复思路：** 同步升级后端依赖文件和打包依赖文件，然后运行后端测试。

**实施清单：**

- [x] 升级 `fastapi` 到能带入安全版 `starlette` 的版本；如有必要，显式固定兼容的安全版 `starlette`。
- [x] 升级 `python-multipart` 到 `>=0.0.27`。
- [x] 升级 `python-jose[cryptography]` 到 `>=3.4.0`；如果兼容性不好，再评估迁移到维护更活跃的 JWT 库。
- [x] 升级 `python-dotenv` 到 `>=1.2.2`。
- [x] 如果 `pytest` 仍在运行时依赖中，升级到安全版本；更好的做法是把测试依赖从生产 requirements 中拆出去。
- [x] 同步修改 `package/requirements.txt` 和 `package/backend/requirements.txt`。
- [x] 运行 `cd package/backend; python -m pytest -q`。
- [x] 运行 `cd package/backend; uvx pip-audit -r requirements.txt`。

**完成标准：** 后端测试通过，并且 pip 审计中没有未处理的高影响运行时漏洞。

---

## SEC-006：Word Formatter 上传 DoS

**风险说明：** 如果开启 `WORD_FORMATTER_ENABLED=true`，旧上传接口会先 `await file.read()` 把整个文件读进内存，再检查大小；同时 `MAX_UPLOAD_FILE_SIZE_MB` 默认是 `0`，表示无限制。

**修复思路：** 设置保守的默认上传大小上限，并在读取过程中分块校验，超过限制立即拒绝。

**实施清单：**

- [x] 将 `MAX_UPLOAD_FILE_SIZE_MB` 默认值从 `0` 改为有限值，例如 `20`。
- [x] 在 `word_formatter/routes.py` 增加辅助函数，例如 `read_upload_with_limit(file, max_size_mb)`，分块读取并在超过限制时中止。
- [x] 在以下接口中使用该辅助函数：
  - `/word-formatter/format/file`
  - `/word-formatter/preprocess/file`
  - `/word-formatter/format-check/file`
- [x] 新增测试：超大上传应在创建任务或解析文件前被拒绝。
- [x] 新增测试：小型上传仍可分块读取并接受。
- [x] 运行 `cd package/backend; python -m pytest tests/test_word_formatter_security.py tests/test_word_formatter_billing.py -q`。

**完成标准：** 超大上传不会被完整读入内存，接口会提前拒绝。

---

## SEC-007：后台配置接口泄露 API Key

**风险说明：** `/api/admin/config` 会把完整系统模型 API Key 返回给前端。任何浏览器侧风险、插件、截图、前端漏洞或管理员 token 泄露，都可能暴露模型凭据。

**修复思路：** 后台配置查询只返回“是否已配置”和后四位，不再返回完整 key。保存配置时，空的 key 字段表示不修改已有密钥。

**实施清单：**

- [x] 修改 `GET /api/admin/config` 响应，用 `api_key_set: bool` 和 `api_key_last4: str` 替代完整 `api_key`。
- [x] 修改 `ConfigManager.jsx`，API Key 输入框显示空占位，不再预填完整密钥。
- [x] 修改配置保存逻辑：未提交或为空的 API Key 不覆盖已有值。
- [x] 新增后端测试：`GET /api/admin/config` 响应中不包含完整 key。
- [x] 新增后端测试：只更新模型名、不提交 API Key 时，旧 API Key 保持不变。
- [x] 运行 `cd package/backend; python -m pytest tests/test_auth_api.py tests/test_operations_api.py -q`。
- [x] 运行 `cd package/frontend; npm run build`。

**完成标准：** 保存后，完整模型 API Key 不再从服务端返回到浏览器。

---

## SEC-008：Token 存储与浏览器安全加固

**风险说明：** 用户和管理员 JWT 存在 `localStorage`。目前 React 默认会转义文本，XSS 风险较低，但依赖漏洞或未来引入 HTML 渲染后，`localStorage` token 会扩大影响。当前安全响应头也不够完整。

**修复思路：** 分阶段加固。第一阶段先增加安全响应头，降低 XSS 和点击劫持影响；第二阶段再评估把 JWT 迁移到 `HttpOnly` Cookie。

**实施清单：**

- [x] 增加安全响应头中间件：
  - `Content-Security-Policy`
  - `X-Frame-Options` 或 CSP `frame-ancestors`
  - `Referrer-Policy`
  - `X-Content-Type-Options`
  - `Permissions-Policy`
- [x] 确保 CSP 不影响 Vite 构建后的静态资源、API 请求和 SSE 流式接口。
- [x] 新增测试：API 响应和 SPA 响应都带有预期安全响应头。
- [x] 记录后续设计：如何把 `localStorage` JWT 替换为 `HttpOnly; Secure; SameSite=Lax/Strict` Cookie。
- [x] 运行 `cd package/backend; python -m pytest -q`。
- [x] 运行 `cd package/frontend; npm run build`。

**完成标准：** 基础浏览器安全响应头已启用，并且 token 迁移方案有明确后续路径。

**后续 Cookie 迁移设计：**

- 新增双 token 返回模式：登录接口继续返回 `access_token` 兼容旧前端，同时可选设置 `HttpOnly; Secure; SameSite=Lax` Cookie。
- 前端 Axios 切换为 `withCredentials: true` 后，先从 Cookie 鉴权；旧版 `Authorization: Bearer ...` 保留一个版本周期。
- 管理员和普通用户 token 分开 Cookie 名称，并设置较短管理员过期时间。
- 增加登出接口清除 Cookie，前端退出登录同时清理旧 `localStorage` token。
- 生产 HTTPS 下启用 `Secure`；本地开发可通过配置允许非 Secure Cookie，避免影响 `http://localhost:9800` 调试。
- 迁移完成后再删除 `localStorage` token 读写逻辑，并增加 CSRF 防护策略。

---

## 总体验证命令

完成选定修复后，运行：

```powershell
cd package/backend
python -m pytest -q
uvx pip-audit -r requirements.txt
```

```powershell
cd package/frontend
npm audit --omit=dev
npm run build
npm run test:e2e
```

人工冒烟检查：

- [ ] `GET /%2e%2e%2fmain.py` 返回 `404`。
- [ ] 登录、工作台、开始降 AI、会话详情、导出仍可用。
- [ ] 管理员登录、配置查看/保存、运维状态、数据库只读查看仍可用。
- [ ] 默认配置下 BYOK 拒绝 `http://127.0.0.1:...`、`https://localhost/...`、`https://169.254.169.254/...`。
- [ ] 开启本地代理模式且 `SERVER_HOST=127.0.0.1` 时，BYOK 接受 `http://127.0.0.1:8317/v1`。
- [ ] `SERVER_HOST=0.0.0.0` 时，即使开启本地代理模式，也拒绝 `http://127.0.0.1:8317/v1`。
- [ ] BYOK 接受已知的公网 HTTPS OpenAI 兼容接口。

---

## 完成记录

| 日期 | 项目 | 结果 | 备注 |
| --- | --- | --- | --- |
| 2026-05-14 | 创建初始安全修复计划 | 待执行 | 等待确认后再开始改代码 |
| 2026-05-14 | SEC-001 静态文件路径穿越 | 已完成 | 聚焦测试 `tests/test_package_static_security.py -q` 已通过；完整后端测试 `python -m pytest -q` 已通过，209 passed |
| 2026-05-14 | SEC-004 前端依赖安全公告 | 已完成 | `npm audit --omit=dev` 已通过，0 vulnerabilities；`npm run build` 已通过；`npm run test:e2e` 已通过，4 passed |
| 2026-05-14 | SEC-007 后台配置接口 API Key 脱敏 | 已完成 | 相关后端测试 `tests/test_auth_api.py tests/test_operations_api.py -q` 已通过；前端 `npm run build` 已通过；完整后端测试 `python -m pytest -q` 已通过，211 passed |
| 2026-05-14 | SEC-005 后端依赖安全公告 | 已完成 | 完整后端测试 `python -m pytest -q` 已通过，211 passed；`uvx pip-audit -r requirements.txt` 已通过，No known vulnerabilities found |
| 2026-05-14 | SEC-002 BYOK 模型地址 SSRF | 已完成 | 聚焦回归测试已通过，24 passed；相关后端测试已通过，95 passed；完整后端测试 `python -m pytest -q` 已通过，236 passed |
| 2026-05-15 | SEC-002 本地模型代理兼容 | 已完成 | 增加 `ALLOW_LOCAL_MODEL_PROXY` 安全开关；仅本机绑定允许本地 HTTP 代理，公网绑定继续拒绝 |
| 2026-05-15 | SEC-006 Word Formatter 上传 DoS | 已完成 | 分块读取上传并默认限制 20MB；聚焦测试已通过，8 passed；完整后端测试 `python -m pytest -q` 已通过，265 passed |
| 2026-05-15 | SEC-008 Token 存储与浏览器安全加固 | 已完成 | 增加 CSP、点击劫持、MIME、来源和权限策略安全头；聚焦测试 `tests/test_security_headers.py -q` 已通过 |

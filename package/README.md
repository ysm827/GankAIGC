# GankAIGC - 可执行文件打包

本目录包含将前后端项目打包为普通可执行文件和 Windows 一键整合包的代码与配置。

当前稳定主线是「账号注册 + 用户登录 + 邀请码注册 + 兑换码充值啤酒 + 啤酒流水 + 降 AI 工作台 + 后台运维状态」。Word 排版相关后端代码仍作为实验模块保留，但默认关闭，前端不暴露排版入口。

当前应用版本写在 `VERSION`，后台左上角版本号和 Docker 镜像内版本显示都会读取这个文件。

## 目录结构

```
package/
├── backend/           # 后端代码（修改版，支持 exe 模式）
├── frontend/          # 前端代码（修改版，生产环境配置）
├── static/            # 前端生产构建产物，python main.py 和 exe 会读取这里
├── main.py            # 统一入口文件
├── VERSION            # 应用版本号
├── app.spec           # PyInstaller 打包配置
├── requirements.txt   # Python 依赖
├── build.sh           # Linux/macOS 构建脚本
├── build.ps1          # Windows 普通 exe 构建脚本
├── build-oneclick.ps1 # Windows 一键整合包构建脚本
├── windows-oneclick/  # 一键包 start/stop/env 模板
└── README.md          # 本文件
```

## 本地构建

<details>
<summary><strong>展开查看普通 exe 和一键包构建命令</strong></summary>

### 前置条件

- Python 3.11 或 3.12（推荐 3.11，避免 Python 3.13 与旧版 PyInstaller 兼容问题）
- Node.js 18+
- pip 和 npm

### 构建步骤

**Linux/macOS:**
```bash
cd package
chmod +x build.sh
./build.sh
```

**Windows 普通 exe:**
```powershell
cd package
.\build.ps1
```

普通 exe 位于 `dist/GankAIGC.exe`，运行时仍需要外部 PostgreSQL。

**Windows 一键整合包（内置便携 PostgreSQL）:**
```powershell
cd package

# 传入已解压 PostgreSQL 目录
.\build-oneclick.ps1 -PostgresRoot C:\pgsql -CreateZip

# 或传入 PostgreSQL Windows binaries ZIP
.\build-oneclick.ps1 -PostgresZip C:\Downloads\postgresql-windows-x64-binaries.zip -CreateZip
```

一键包位于 `dist/GankAIGC-Windows/`，压缩包位于 `dist/GankAIGC-Windows-OneClick.zip`。

</details>

### 前端生产静态包

修改 `frontend/src/` 后，需要重新构建并同步到 `static/`，否则 `python main.py`、Docker 和 exe 仍会使用旧页面：

```powershell
cd package/frontend
npm ci
npm run build
cd ../..
robocopy package\frontend\dist package\static /MIR
git add package/frontend
git add -f package/static
```

`package/static` 被 `.gitignore` 忽略，提交生产包时需要 `git add -f package/static`。

## 发布方式

当前公开 Release 主要发布 Windows 一键整合包：

```text
GankAIGC-Windows-OneClick.zip
```

上传前建议本地重新构建：

```powershell
cd package
.\build-oneclick.ps1 -PostgresZip C:\Downloads\postgresql-windows-x64-binaries.zip -CreateZip
```

然后用 GitHub CLI 覆盖 Release 附件：

```powershell
gh release upload v1.0.9 .\dist\GankAIGC-Windows-OneClick.zip --clobber
```

GitHub Actions 工作流会在推送 `v*` 标签时构建普通 Windows/Linux/macOS 可执行文件；当前公开 Release 仍优先使用本地构建并上传的 Windows 一键整合包。

### 标签发布

```bash
git tag -a v1.0.9 -m "GankAIGC v1.0.9"
git push origin v1.0.9
```

发布新版本时同时更新：

- `VERSION`
- `backend/app/config.py` 中的 `DEFAULT_APP_VERSION`
- 根目录 README 的使用说明，如部署或后台行为有变化

### 常见构建产物

- `GankAIGC-Windows.zip` - GitHub Actions 自动构建的 Windows 普通可执行文件，需要外部 PostgreSQL
- `GankAIGC-Windows-OneClick.zip` - Windows 一键整合包，内置便携 PostgreSQL
- `GankAIGC-Linux.tar.gz` - GitHub Actions 自动构建的 Linux 可执行文件
- `GankAIGC-macOS.tar.gz` - GitHub Actions 自动构建的 macOS 可执行文件

## 运行说明

普通 exe：

1. 下载对应平台的可执行文件。
2. 解压到任意目录。
3. 首次运行会自动创建 `.env` 配置文件模板。
4. 编辑 `.env`，填入 PostgreSQL `DATABASE_URL`、API Key、管理员密码和密钥。
5. 再次运行程序。

Windows 一键整合包：

1. 解压 `GankAIGC-Windows-OneClick.zip`。
2. 双击 `start.bat`。
3. 首次运行会自动初始化 `data/` 下的 PostgreSQL，并生成 `.env`。
4. 后台密码会显示在窗口中，并保存到 `logs/first-run-admin.txt`。
5. 停止服务双击 `stop.bat`。

### 配置文件说明

`.env` 文件会保存在可执行文件同目录下。数据库只支持 PostgreSQL，请在 `.env` 中配置 `DATABASE_URL`。

源码运行时降 AI 任务会先进入 PostgreSQL 队列。exe / `python main.py` 默认启用 inline worker；Docker 部署则由独立 worker 服务消费队列。worker 会定期刷新心跳，长时间无心跳的处理中任务会自动恢复为排队状态。

Docker 部署默认还会启动 `backup` 服务，每天自动备份 PostgreSQL 到宿主机 `backups/`。后台「运维状态」可以查看数据库、worker、备份、版本更新和初始化检查。

模型 Base URL 默认要求公网 HTTPS 地址。Windows 一键包本机使用 `cliproxy`、`new-api` 等本地代理时，后台把 `SERVER_HOST` 设为 `127.0.0.1`，打开“允许本地 HTTP 模型代理”，Base URL 填 `http://127.0.0.1:端口/v1`。不要写成 `https://127.0.0.1:端口/v1`。公网或 VPS 部署不要开启本地代理模式，必须使用公网 HTTPS Base URL。

Docker 更新采用手动 SSH 模式：后台只检测 GitHub Release 并提供复制命令，不直接控制 Docker，也不挂载 Docker socket。VPS 上升级通常执行：

```bash
git fetch --tags origin main
git pull --ff-only origin main
docker compose --env-file .env.docker up -d --build
```

### 访问地址

- 用户界面: http://localhost:9800
- 管理后台: http://localhost:9800/admin
- API 文档: http://localhost:9800/docs

## 与原项目的区别

1. **运行方式**：原项目需要分别启动前端和后端服务，exe 版本一键启动
2. **配置位置**：exe 版本的 `.env` 在 exe 同目录，数据库连接由 `DATABASE_URL` 指向 PostgreSQL
3. **前端访问**：exe 版本前后端在同一端口，无需代理

## 技术细节

### 前端修改
- 修改 `vite.config.js` 添加生产环境构建配置
- 修改 API 配置，生产环境直接使用根路径
- 后台用户管理分为用户列表、邀请码管理、兑换码、啤酒流水和 API 配置；用户列表支持搜索、状态筛选、API 配置筛选、封禁/启用、充值和无限啤酒。

### 后端修改
- 修改 `config.py`，支持动态获取 exe 目录下的配置文件
- 数据库统一使用 PostgreSQL
- 增加浏览器安全响应头、模型 Base URL 安全校验、Docker 手动升级边界和 PostgreSQL 备份状态读取。

### 统一入口
- `main.py` 创建 FastAPI 应用
- 挂载静态文件服务前端页面
- 处理 SPA 路由（admin、workspace 等）
- 自动打开浏览器

### PyInstaller 配置
- 包含所有必要的隐式导入
- 包含前端静态文件
- 包含后端应用代码
- 排除不必要的大型库

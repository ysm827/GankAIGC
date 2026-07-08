GankAIGC Windows 一键整合包
===========================

一、启动和停止
--------------
1. 双击 start.bat。
2. 首次运行会自动初始化内置 PostgreSQL，并生成 .env。
3. 浏览器打开 http://localhost:9800。
4. 后台地址：http://localhost:9800/admin。
5. 停止服务请双击 stop.bat。

二、目录说明
------------
- GankAIGC.exe：应用程序。
- postgres/：便携 PostgreSQL 运行文件。
- data/：数据库数据，请勿随便删除。
- logs/：启动日志、数据库日志和首次生成的后台密码。
- .env：配置文件，可修改 API Key、模型、端口、后台密码、朱雀浏览器路径等。
- .env.template：默认配置模板。

三、朱雀 AI 检测/降重
---------------------
一键包默认走本机可见浏览器链路：
- 不需要安装 GankAIGC Chrome 插件。
- 不需要执行 playwright install。
- 不会使用服务器/VPS 的无头浏览器探测朱雀。
- 默认优先复用或打开 Windows 本机 Chrome / Edge / Brave 的朱雀窗口。

使用步骤：
1. 进入工作台，选择「AI检测 + 降重」。
2. 点击「打开朱雀页面」。
3. 在弹出的朱雀窗口里完成登录、验证码或人工验证。
4. 回到 GankAIGC，点击「剩余次数」右侧刷新按钮。
5. 正常会同步显示「朱雀账号」和「剩余次数」。

如果已经在朱雀窗口登录但次数没刷新：
1. 保持朱雀窗口不要关闭。
2. 再点一次「打开朱雀页面」，让系统聚焦同一个朱雀窗口。
3. 等待页面加载完成后，再点「剩余次数」右侧刷新按钮。
4. 如果仍未同步，先双击 stop.bat，再双击 start.bat 后重试。

如需强制指定浏览器，可编辑 .env，例如：

  ZHUQUE_DETECT_BROWSER_EXECUTABLE=C:\Program Files\Microsoft\Edge\Application\msedge.exe

或：

  ZHUQUE_DETECT_BROWSER_EXECUTABLE=C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe

朱雀本机默认配置如下，通常不需要修改：

  ZHUQUE_DETECT_TRANSPORT=auto
  ZHUQUE_DETECT_HEADLESS=false
  ZHUQUE_DETECT_AUTO_SYSTEM_BROWSER=true
  ZHUQUE_SERVER_HEADLESS_FALLBACK=false

四、常见问题
------------
1. 提示 127.0.0.1:9800 端口被占用

   可在 PowerShell 查看占用进程：

     Get-NetTCPConnection -LocalPort 9800 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess

     $pid9800 = Get-NetTCPConnection -LocalPort 9800 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique
     Get-Process -Id $pid9800 | Select-Object Id,ProcessName,Path

   如果确认可以关闭该进程：

     Get-NetTCPConnection -LocalPort 9800 -State Listen |
       Select-Object -ExpandProperty OwningProcess -Unique |
       ForEach-Object { Stop-Process -Id $_ -Force }

   如果不想关闭原进程，可编辑 .env：

     SERVER_PORT=9801

   然后重新双击 start.bat，并打开：

     http://localhost:9801

2. 提示 55432 端口被占用

   编辑 .env：

     POSTGRES_PORT=55433

   然后重新双击 start.bat。

3. 忘记首次生成的后台密码

   查看：

     logs/first-run-admin.txt

4. 启动异常或窗口一闪而过

   查看：

     logs/start.log
     logs/app.log
     logs/postgres.log

五、升级新版一键包
------------------
推荐方式：
1. 先双击旧目录里的 stop.bat。
2. 备份旧目录里的 .env、data/、logs/。
3. 将新版 ZIP 解压到一个新目录。
4. 如需保留旧数据，把旧目录的 .env、data/、logs/ 复制到新目录覆盖。
5. 双击新目录里的 start.bat。

注意：
- 不要删除 data/，否则用户、邀请码、兑换码、会话、朱雀状态等数据会丢失。
- 如果只是临时测试新版，建议解压到新目录，不要直接覆盖旧目录。

"""
朱雀凭证捕获工具 v2.0 — 方案A: 微信扫码登录 → 自动提取凭证
============================================================
真实点击链（已实测验证）:
  1. 点击 .user-info → 打开 Element UI 下拉菜单
  2. 点击"登录"下拉项 → 打开登录弹窗（Google + 微信双选项）
  3. 点击"微信登录" → 加载 QR iframe (open.weixin.qq.com/qrconnect?...)
  4. 用户微信扫码 → OAuth 回调 → 自动检测登录态

关键参数:
  - WeChat AppID: wxeb4ab5b8ff535d2b
  - OAuth scope: snsapi_login
  - 回调: https://matrix.tencent.com/ai-detect/
  - 配额: 20次/天/微信账号

用法:
    python capture_zhuque_creds.py                        # 可见浏览器，扫码后自动保存
    python capture_zhuque_creds.py --sync-session         # 打开朱雀页，按网页内真实登录/退出状态同步凭证
    python capture_zhuque_creds.py --load                 # 加载 creds_latest.json 查看
    python capture_zhuque_creds.py --load creds_20250616_120000.json
    python capture_zhuque_creds.py --export-shell          # 导出为 shell 环境变量
    python capture_zhuque_creds.py --export-json-creds     # 导出为 zhuque_api_headless.py 可用的 creds JSON

输出:
    creds_<timestamp>.json   # 完整凭证（含所有 localStorage + cookies）
    creds_latest.json        # 最新凭证
    qrcode_latest.png        # 二维码截图（供调试）
"""
import asyncio, json, sys, time, os, re, subprocess, urllib.error, urllib.request
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PwTimeout

TEMP = Path(__file__).parent.resolve()
MATRIX_URL = "https://matrix.tencent.com/ai-detect/"
WAIT_TIMEOUT = 180  # 等待扫码的秒数（超时则退出）
POLL_INTERVAL = 0.35
STORAGE_STATE_FILE = TEMP / "browser_state.json"  # 持久化 browser context（cookies+localStorage）
LATEST_CREDENTIALS_FILE = TEMP / "creds_latest.json"
SESSION_STATUS_FILE = TEMP / "session_status.json"
DEFAULT_WINDOWS_CDP_PORT = 9223


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_wsl() -> bool:
    if os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def _run_text(args: list[str], timeout: float = 3.0) -> str:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (completed.stdout or "").strip()


def _wsl_to_windows_path(path: str | Path) -> str:
    text = str(path)
    converted = _run_text(["wslpath", "-w", text], timeout=2.0)
    if converted:
        return converted
    match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", text)
    if match:
        drive, rest = match.groups()
        windows_rest = rest.replace("/", "\\")
        return f"{drive.upper()}:\\{windows_rest}"
    return text


def _windows_to_wsl_path(path: str) -> Path | None:
    text = (path or "").strip().strip('"')
    if not text:
        return None
    converted = _run_text(["wslpath", "-u", text], timeout=2.0)
    if converted:
        return Path(converted)
    match = re.match(r"^([a-zA-Z]):\\(.*)$", text)
    if match:
        drive, rest = match.groups()
        linux_rest = rest.replace("\\", "/")
        return Path(f"/mnt/{drive.lower()}/{linux_rest}")
    return None


def _windows_local_app_data() -> str:
    env_value = os.environ.get("ZHUQUE_WINDOWS_CHROME_USER_DATA_DIR")
    if env_value:
        return env_value

    local_app_data = _run_text(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "[Environment]::GetFolderPath('LocalApplicationData')",
        ],
        timeout=3.0,
    )
    if local_app_data:
        return local_app_data

    # Fallback for minimal WSL images without powershell.exe in PATH.
    users_root = Path("/mnt/c/Users")
    if users_root.exists():
        for candidate in users_root.iterdir():
            local = candidate / "AppData" / "Local"
            if local.exists():
                return _wsl_to_windows_path(local)
    return r"C:\GankAIGC"


def _windows_chrome_profile_dir() -> str:
    configured = os.environ.get("ZHUQUE_WINDOWS_CHROME_USER_DATA_DIR")
    if configured:
        return configured
    base = _windows_local_app_data().rstrip("\\/")
    return base + r"\GankAIGC\ZhuqueChromeProfile"


def _cdp_port() -> int:
    try:
        return int(os.environ.get("ZHUQUE_CDP_PORT") or DEFAULT_WINDOWS_CDP_PORT)
    except (TypeError, ValueError):
        return DEFAULT_WINDOWS_CDP_PORT


def _windows_host_ip() -> str:
    try:
        resolv_conf = Path("/etc/resolv.conf").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^nameserver\s+([0-9.]+)", resolv_conf, flags=re.MULTILINE)
    return match.group(1) if match else ""


def _cdp_endpoints(port: int | None = None) -> list[str]:
    cdp_port = port or _cdp_port()
    hosts = ["127.0.0.1", "localhost"]
    host_ip = _windows_host_ip()
    if host_ip and host_ip not in hosts:
        hosts.append(host_ip)
    return [f"http://{host}:{cdp_port}" for host in hosts]


def _cdp_endpoint(port: int | None = None) -> str:
    return _cdp_endpoints(port)[0]


def _wait_for_cdp(port: int, timeout: float = 8.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for endpoint in _cdp_endpoints(port):
            try:
                with urllib.request.urlopen(f"{endpoint}/json/version", timeout=0.5) as response:
                    if response.status == 200:
                        return endpoint
            except (OSError, urllib.error.URLError):
                continue
        time.sleep(0.25)
    return ""


def _pick_local_storage_token(local_storage: dict) -> tuple[str, str]:
    """Return (token, key) from known or token-like localStorage entries."""
    preferred_keys = [
        "aiGenAccessToken",
        "access_token",
        "accessToken",
        "token",
    ]
    for key in preferred_keys:
        value = local_storage.get(key)
        if value:
            return _unwrap_token_value(value), key

    for key, value in local_storage.items():
        lower_key = str(key).lower()
        if value and "token" in lower_key and ("access" in lower_key or "auth" in lower_key):
            return _unwrap_token_value(value), str(key)
    return "", ""


def _unwrap_token_value(value) -> str:
    """Zhuque stores aiGenAccessToken as either a raw token or JSON {value, expiry, uid}."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("value") or value.get("token") or value.get("access_token") or "")
    text = str(value)
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return text
    if isinstance(parsed, dict):
        return str(parsed.get("value") or parsed.get("token") or parsed.get("access_token") or text)
    return text


def _parse_remaining_uses(text: str) -> int:
    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else -1


def _normalise_login_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip()).lower()


def _is_login_prompt_text(text: str) -> bool:
    """Return True for Zhuque's logged-out account label.

    The live page renders the top-right login entry as `.user-name = Login`.
    Treating that label as a real username caused GankAIGC to save anonymous
    quota text like "Detect now(16 left)" as if it belonged to a logged-in
    account. Only a non-login account label, token, or auth cookie is login.
    """
    normalised = _normalise_login_text(text)
    return normalised in {
        "login",
        "log in",
        "signin",
        "sign in",
        "登录",
        "微信登录",
        "扫码登录",
    }


def _pick_cookie_value(cookies: list, names: tuple[str, ...]) -> tuple[str, str]:
    """Return (cookie value, cookie name) from Playwright cookie dicts."""
    wanted = {name.lower() for name in names}
    for cookie in cookies or []:
        name = str(cookie.get("name", ""))
        if name.lower() in wanted and cookie.get("value"):
            return str(cookie["value"]), name
    return "", ""


async def inspect_auth_state(page) -> dict:
    """Inspect page login state without assuming Zhuque keeps the same token key forever."""
    browser_state = await page.evaluate("""
        (() => {
            const localStorageValues = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                localStorageValues[k] = localStorage.getItem(k);
            }
            const un = document.querySelector('.user-name');
            const ui = document.querySelector('.user-info');
            let quotaEl = null, bestLen = Infinity;
            const submitBtn = document.querySelector('.submit-btn')
                || [...document.querySelectorAll('button')].find(b => /立即检测|Detect/i.test(b.textContent || ''));
            const loginPromptVisible = [...document.querySelectorAll('.user-name, .user-info, button, a')]
                .some(el => {
                    const rects = el.getClientRects ? el.getClientRects() : [];
                    const visible = rects && rects.length > 0;
                    const txt = (el.textContent || '').trim();
                    return visible && /^(Login|Log in|Sign in|登录|扫码登录|微信登录)$/i.test(txt);
                });
            for (const el of document.querySelectorAll('*')) {
                const txt = (el.textContent || '').trim();
                if (/(今日剩余|剩余.*次|可用.*次|\\d+\\s*left)/i.test(txt) && txt.length < bestLen && txt.length < 100) {
                    quotaEl = el; bestLen = txt.length;
                }
            }
            return {
                localStorage: localStorageValues,
                userName: un ? un.textContent.trim() : '',
                userInfoText: ui ? ui.textContent.trim() : '',
                loginPromptVisible,
                quotaText: quotaEl ? quotaEl.textContent.trim() : '',
                submitButtonText: submitBtn ? submitBtn.textContent.trim() : '',
                url: location.href
            };
        })()
    """)
    cookies = await page.context.cookies()
    local_storage = browser_state.get("localStorage", {})
    token, token_source = _pick_local_storage_token(local_storage)
    cookie_token, cookie_token_source = _pick_cookie_value(cookies, ("ACCESS_TOKEN", "access_token", "accessToken"))
    fp = local_storage.get("fp") or ""
    user_name = (browser_state.get("userName") or "").strip()
    login_prompt_visible = bool(browser_state.get("loginPromptVisible")) or _is_login_prompt_text(user_name)
    if login_prompt_visible:
        user_name = ""
    quota_text = (browser_state.get("quotaText") or browser_state.get("submitButtonText") or "").strip()
    ready = bool(token or cookie_token or (user_name and (fp or cookies)))
    return {
        **browser_state,
        "cookies": cookies,
        "token": token or cookie_token,
        "tokenSource": token_source or cookie_token_source,
        "fp": fp,
        "ready": ready,
        "userName": user_name,
        "loginPromptVisible": login_prompt_visible,
        "quotaText": quota_text,
        "remainingUses": _parse_remaining_uses(quota_text),
    }


def find_browser_executable():
    """优先复用系统 Chromium 内核浏览器，避免必须下载 Playwright 内置 Chromium。"""
    env_path = os.environ.get("ZHUQUE_CHROME_EXECUTABLE")
    windows_env_path = _windows_to_wsl_path(env_path) if _is_wsl() and env_path else None
    candidates = [
        env_path,
        windows_env_path,
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
        "/usr/bin/msedge",
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
        "/snap/bin/chromium",
        "/snap/bin/brave",
    ]
    if _is_wsl():
        candidates.extend(
            [
                "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
                "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
                "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
                "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                "/mnt/c/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe",
                "/mnt/c/Program Files (x86)/BraveSoftware/Brave-Browser/Application/brave.exe",
            ]
        )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def is_windows_browser_executable(executable: str | None) -> bool:
    if not executable:
        return False
    text = str(executable).lower()
    return text.endswith(".exe") or text.startswith("/mnt/")


def launch_windows_chrome_for_cdp(executable: str, *, port: int | None = None) -> tuple[bool, str, str]:
    """Launch the user's Windows Chrome/Edge in a small app window and expose CDP.

    Playwright cannot directly launch a Windows .exe from Linux as a normal browser
    process, but it can connect over Chrome DevTools Protocol after Windows Chrome
    is started with --remote-debugging-port. This keeps the visible scan window in
    the user's real Windows desktop while preserving backend credential sync.
    """
    cdp_port = port or _cdp_port()
    existing_endpoint = _wait_for_cdp(cdp_port, timeout=0.6)
    if existing_endpoint:
        return True, f"已连接现有 Windows Chrome 调试端口 {cdp_port}", existing_endpoint

    profile_dir = _windows_chrome_profile_dir()
    chrome_path = str(executable)
    width = int(os.environ.get("ZHUQUE_LOGIN_WINDOW_WIDTH") or 520)
    height = int(os.environ.get("ZHUQUE_LOGIN_WINDOW_HEIGHT") or 760)
    args = [
        chrome_path,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir}",
        f"--app={MATRIX_URL}",
        f"--window-size={width},{height}",
        "--window-position=120,80",
        "--remote-debugging-address=0.0.0.0",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
    ]
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        return False, f"启动 Windows Chrome 失败: {exc}", ""

    endpoint = _wait_for_cdp(cdp_port, timeout=10.0)
    if not endpoint:
        return False, f"Windows Chrome 已启动但调试端口 {cdp_port} 未就绪", ""
    return True, f"已启动 Windows Chrome 小窗并连接调试端口 {cdp_port}", endpoint

# ===================== 凭证提取 =====================

async def extract_credentials(page) -> dict:
    """从已登录页提取完整凭证：localStorage + cookies + 用户信息 + 配额"""
    # 先通过 Playwright context 获取所有 cookies（含 HttpOnly）
    all_cookies = await page.context.cookies()

    creds = await page.evaluate("""
        (() => {
            // localStorage 全部
            const ls = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                ls[k] = localStorage.getItem(k);
            }
            // 用户信息
            const un = document.querySelector('.user-name');
            const ua = document.querySelector('.user-info img, .avatar img');
            // 配额文字 — 找最具体的元素（textContent最短的）
            let quotaEl = null, bestLen = Infinity;
            const submitBtn = document.querySelector('.submit-btn')
                || [...document.querySelectorAll('button')].find(b => /立即检测|Detect/i.test(b.textContent || ''));
            for (const el of document.querySelectorAll('*')) {
                const txt = (el.textContent || '').trim();
                if (/(今日剩余|剩余.*次|可用.*次|\\d+\\s*left)/i.test(txt) && txt.length < bestLen && txt.length < 100) {
                    quotaEl = el; bestLen = txt.length;
                }
            }
            return {
                localStorage: ls,
                userName: un ? un.textContent.trim() : '',
                avatarUrl: ua ? ua.src || '' : '',
                quotaText: quotaEl ? quotaEl.textContent.trim() : (submitBtn ? submitBtn.textContent.trim() : ''),
                submitButtonText: submitBtn ? submitBtn.textContent.trim() : '',
                url: location.href,
                timestamp: new Date().toISOString()
            };
        })()
    """)
    creds['cookies'] = all_cookies
    creds['cookieString'] = '; '.join([f"{c['name']}={c['value']}" for c in all_cookies])
    token, token_source = _pick_local_storage_token(creds.get("localStorage", {}))
    if not token:
        token, token_source = _pick_cookie_value(all_cookies, ("ACCESS_TOKEN", "access_token", "accessToken"))
    if token:
        creds["access_token"] = token
        creds["access_token_source"] = token_source
    if creds.get("localStorage", {}).get("fp"):
        creds["fp"] = creds["localStorage"]["fp"]
    creds["remainingUses"] = _parse_remaining_uses(creds.get("quotaText") or creds.get("submitButtonText") or "")
    return creds


def write_session_status(status: dict) -> None:
    """Write live Zhuque page state for the backend status endpoint.

    This file is intentionally non-secret: it contains UI state only, never raw
    tokens/cookies. It lets GankAIGC refresh login/logout state without waiting
    for the heavier credential parser/cache path.
    """
    payload = {
        "connected": bool(status.get("connected")),
        "ready": bool(status.get("ready")),
        "has_token": bool(status.get("has_token")),
        "remaining_uses": status.get("remaining_uses", -1),
        "user_name": status.get("user_name") or "",
        "quota_text": status.get("quota_text") or "",
        "message": status.get("message") or "",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp_file = SESSION_STATUS_FILE.with_suffix(".tmp")
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_file.replace(SESSION_STATUS_FILE)


def _auth_state_status(auth_state: dict, *, message: str = "") -> dict:
    return {
        "connected": bool(auth_state.get("ready")),
        "ready": bool(auth_state.get("ready")),
        "has_token": bool(auth_state.get("token")),
        "remaining_uses": auth_state.get("remainingUses", -1),
        "user_name": (auth_state.get("userName") or "").strip(),
        "quota_text": (auth_state.get("quotaText") or auth_state.get("submitButtonText") or "").strip(),
        "message": message,
    }


def _logged_out_status_from_auth_state(auth_state: dict = None, *, message: str) -> dict:
    """Build a non-secret logged-out status while preserving live free quota.

    The anonymous Zhuque page can still expose a usable quota such as
    ``Detect now(16 left)``. Keep that real-time page value in
    ``session_status.json`` so the workspace can show it, but never treat it as
    a logged-in credential or persist it into ``creds_latest.json``.
    """
    quota_text = ""
    remaining_uses = -1
    if auth_state:
        quota_text = (auth_state.get("quotaText") or auth_state.get("submitButtonText") or "").strip()
        try:
            remaining_uses = int(auth_state.get("remainingUses", -1))
        except (TypeError, ValueError):
            remaining_uses = -1
        if remaining_uses < 0:
            remaining_uses = _parse_remaining_uses(quota_text)

    return {
        "connected": False,
        "ready": False,
        "has_token": False,
        "remaining_uses": remaining_uses if remaining_uses >= 0 else -1,
        "user_name": "",
        "quota_text": quota_text,
        "message": message,
    }


def write_logged_out_status(message: str = "朱雀网页显示未登录", auth_state: dict = None) -> None:
    write_session_status(_logged_out_status_from_auth_state(auth_state, message=message))


def save_credentials(creds: dict) -> tuple[Path, Path]:
    """保存当前朱雀登录凭证；退出登录时才会删除 latest。"""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    creds_file = TEMP / f"creds_{timestamp}.json"
    with open(creds_file, 'w', encoding='utf-8') as f:
        json.dump(creds, f, ensure_ascii=False, indent=2)
    with open(LATEST_CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(creds, f, ensure_ascii=False, indent=2)
    return creds_file, LATEST_CREDENTIALS_FILE


async def save_browser_state(ctx) -> None:
    """持久化浏览器会话。登录态和退出态都要保存，避免下次恢复旧状态。"""
    state = await ctx.storage_state()
    with open(STORAGE_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    print(f"  [save] 浏览器会话已保存: {STORAGE_STATE_FILE.name}")


def clear_latest_credentials(reason: str = "", auth_state: dict = None) -> bool:
    """只在朱雀网页里真实退出后清理 latest 凭证，不删除历史快照。"""
    removed = False
    if LATEST_CREDENTIALS_FILE.exists():
        LATEST_CREDENTIALS_FILE.unlink()
        removed = True
    write_logged_out_status(reason or "朱雀网页显示未登录", auth_state=auth_state)
    suffix = f" | {reason}" if reason else ""
    if removed:
        print(f"  [logout-sync] 已清除最新朱雀凭证: {LATEST_CREDENTIALS_FILE.name}{suffix}")
    else:
        print(f"  [logout-sync] 朱雀网页已退出，当前无最新凭证{suffix}")
    return removed


def auth_signature(auth_state: dict) -> tuple:
    """用于判断登录用户/凭证是否变化，避免每秒重复写文件。"""
    token = auth_state.get("token") or ""
    return (
        bool(auth_state.get("ready")),
        (auth_state.get("userName") or "").strip(),
        token[:48],
        auth_state.get("fp") or "",
        auth_state.get("remainingUses"),
    )


async def save_logged_in_snapshot(page, ctx, reason: str = "") -> tuple[Path, Path]:
    """提取当前页面登录态并保存为 GankAIGC 可用凭证。"""
    creds = await extract_credentials(page)
    creds_file, latest_file = save_credentials(creds)
    await save_browser_state(ctx)
    write_session_status({
        "connected": True,
        "ready": True,
        "has_token": bool(creds.get("access_token")),
        "remaining_uses": creds.get("remainingUses", -1),
        "user_name": creds.get("userName") or "",
        "quota_text": creds.get("quotaText") or creds.get("submitButtonText") or "",
        "message": "朱雀网页已登录",
    })
    label = f"（{reason}）" if reason else ""
    print(f"  [sync] 已同步朱雀登录态{label}: {creds.get('userName') or '未知用户'}")
    print(f"   凭证: {latest_file}")
    return creds_file, latest_file


async def sync_session_until_closed(page, ctx, *, trigger_login_when_missing: bool = False) -> dict:
    """打开真实朱雀页面，按用户在网页内的登录/退出操作同步本地凭证。

    语义：
    - 不自动退出账号；
    - 只有观察到朱雀网页处于未登录态，才删除 creds_latest.json；
    - 观察到登录态就保存/更新 creds_latest.json；
    - 用户关闭窗口后退出，最后一次观察到的状态就是 GankAIGC 状态。
    """
    print("\n[sync] 已进入朱雀真实状态同步模式")
    print("   可在打开的朱雀网页内扫码登录、退出登录或切换账号。")
    print("   GankAIGC 只认网页内真实状态；关闭窗口后保留最后一次同步结果。\n")

    last_signature = None
    logged_out_synced = False
    login_triggered = False
    logged_out_streak = 0

    while True:
        try:
            if page.is_closed():
                print("  [sync] 朱雀窗口已关闭，结束同步")
                break
            auth_state = await inspect_auth_state(page)
        except Exception as exc:
            if page.is_closed():
                print("  [sync] 朱雀窗口已关闭，结束同步")
                break
            print(f"  [sync] 状态读取失败，继续等待: {exc}")
            await asyncio.sleep(POLL_INTERVAL)
            continue

        if auth_state.get("ready"):
            logged_out_streak = 0
            logged_out_synced = False
            write_session_status(_auth_state_status(auth_state, message="朱雀网页已登录"))
            signature = auth_signature(auth_state)
            if signature != last_signature:
                await save_logged_in_snapshot(page, ctx, reason="检测到登录态")
                last_signature = signature
            await asyncio.sleep(POLL_INTERVAL)
            continue

        logged_out_streak += 1
        write_logged_out_status("朱雀网页显示未登录", auth_state=auth_state)

        if trigger_login_when_missing and not login_triggered and logged_out_streak >= 2:
            login_triggered = True
            print("  [sync] 当前未登录，尝试打开微信扫码登录入口...")
            try:
                triggered = await trigger_login_flow(page)
                await page.screenshot(path=str(TEMP / "qrcode_latest.png"))
                print(f"\n[shot] 二维码截图已保存: {TEMP / 'qrcode_latest.png'}")
                if not triggered:
                    print("  [sync] 未能自动打开二维码，请在朱雀网页内手动点击登录/微信登录。")
            except Exception as exc:
                print(f"  [sync] 自动打开登录入口失败，请手动操作: {exc}")

        # 连续两次确认未登录后，才认为用户已在朱雀网页退出。
        # 如果已经明确看到登录入口，马上按真实网页退出态同步；若只是页面
        # 初始化空白/抖动，则仍保留两次轮询确认，避免误删。
        logged_out_visible = bool(auth_state.get("loginPromptVisible"))
        if (logged_out_visible or logged_out_streak >= 2) and not logged_out_synced:
            clear_latest_credentials("朱雀网页显示未登录", auth_state=auth_state)
            try:
                await save_browser_state(ctx)
            except Exception as exc:
                print(f"  [sync] 保存退出态浏览器会话失败: {exc}")
            last_signature = None
            logged_out_synced = True

        await asyncio.sleep(POLL_INTERVAL)

    return {"status": "closed"}


async def wait_for_login(page, timeout=WAIT_TIMEOUT):
    """轮询检测登录：兼容 localStorage token、cookie token 和已登录用户态。"""
    print(f"\n[wait] 等待微信扫码登录（最长 {timeout}s）...")
    print("   请在手机微信中扫描浏览器显示的二维码\n")

    start = time.time()
    last_ls_keys = set()

    while time.time() - start < timeout:
        try:
            auth_state = await inspect_auth_state(page)
            token = auth_state.get("token") or ""
            if auth_state.get("ready"):
                elapsed = time.time() - start
                print(f"\n[OK] 检测到登录态！（耗时 {elapsed:.0f}s）")
                if token:
                    print(f"   Token 来源: {auth_state.get('tokenSource') or '?'}，前60字符: {token[:60]}...")
                elif auth_state.get("userName"):
                    print(f"   用户: {auth_state.get('userName')}（未暴露 localStorage token，改用 cookie/fp 凭证）")
                return True

            # 显示 localStorage 变化
            cur_keys = list((auth_state.get("localStorage") or {}).keys())
            cur_set = set(cur_keys or [])
            new_keys = cur_set - last_ls_keys
            if new_keys:
                print(f"   [note] localStorage 新增: {new_keys}")
            last_ls_keys = cur_set

            await asyncio.sleep(POLL_INTERVAL)
        except Exception as e:
            # 页面可能跳转
            await asyncio.sleep(POLL_INTERVAL)

    print(f"\n[FAIL] 超时（{timeout}s），未检测到登录。请重试。")
    return False


# ===================== 退出登录（切号用）=====================

async def perform_logout(page) -> bool:
    """
    点击用户头像 → 下拉菜单中点击"退出登录"
    返回 True 如果成功退出
    """
    print("\n[logout] 执行退出登录...")

    # Step 1: 点击用户头像/用户名触发下拉菜单
    print("  [1/3] 点击 .user-info 打开菜单...")
    try:
        await page.wait_for_selector('.user-info', state='visible', timeout=5000)
        await page.click('.user-info')
        await asyncio.sleep(1.5)
    except Exception as e:
        print(f"  [WARN] 点击 .user-info 失败: {e}")
        await page.evaluate("document.querySelector('.user-info')?.click()")
        await asyncio.sleep(1.5)

    # Step 2: 查找并点击"退出登录"
    logout_clicked = await page.evaluate("""() => {
        // Element UI dropdown 中的菜单项
        const candidates = document.querySelectorAll(
            '.el-dropdown-menu__item, li, .el-popper li, [role="menuitem"], span, div'
        );
        for (const el of candidates) {
            const txt = (el.textContent || '').trim();
            if (txt === '退出登录' || txt === '退出' || txt === '登出' || txt === '退出登录 ') {
                el.click();
                return 'clicked: ' + txt;
            }
        }
        // fallback: 找包含"退出"文本的可见元素
        const all = document.querySelectorAll('li, span, div, button');
        for (const el of all) {
            const txt = (el.textContent || '').trim();
            if ((txt.includes('退出') || txt.includes('Logout') || txt.includes('Sign out')) && el.offsetParent !== null) {
                el.click();
                return 'fallback: ' + txt;
            }
        }
        return 'NOT FOUND';
    }""")
    print(f"  结果: {logout_clicked}")
    await asyncio.sleep(2)

    # Step 3: 验证退出 — 等待 token 清空或页面跳转
    print("  [3/3] 验证退出状态...")
    for i in range(10):
        token = await page.evaluate("localStorage.getItem('aiGenAccessToken') || ''")
        if not token:
            # 二次确认：等页面稳定
            await asyncio.sleep(1.5)
            token2 = await page.evaluate("localStorage.getItem('aiGenAccessToken') || ''")
            if not token2:
                print("  [OK] 已退出登录，localStorage token 已清除")
                return True
        print(f"  [{i}] 等待退出...（token: {'存在' if token else '无'}）")
        await asyncio.sleep(1)

    # 最终检查
    token = await page.evaluate("localStorage.getItem('aiGenAccessToken') || ''")
    if token:
        print("  [WARN] Token 仍在，但继续尝试重新登录...")
    return not bool(token)

async def trigger_login_flow(page) -> bool:
    """
    真实点击链（已测试通过）:
      Step 1: 点击 .user-info 打开下拉菜单
      Step 2: 点击下拉菜单中的"登录"
      Step 3: 点击弹窗中的"微信登录"选项
    返回 True 如果成功显示 QR 二维码 iframe
    """
    print("\n[login] 触发登录流程...")

    # ====== Step 1: 点击 user-info ======
    print("  [1/3] 点击 .user-info 打开下拉菜单...")
    try:
        # 先确保 .user-info 存在且可点击
        await page.wait_for_selector('.user-info', state='visible', timeout=5000)
        await page.click('.user-info')
        await asyncio.sleep(1)
    except Exception as e:
        print(f"  [WARN] 点击 .user-info 失败: {e}")
        # 尝试 JS 方式
        await page.evaluate("document.querySelector('.user-info')?.click()")
        await asyncio.sleep(1)

    # 检查下拉菜单是否打开
    dropdown_open = await page.evaluate("""() => {
        const menus = document.querySelectorAll('.el-dropdown-menu, .el-popper');
        for (const m of menus) {
            if (m.offsetParent !== null && m.innerText.trim()) return true;
        }
        return false;
    }""")
    print(f"  下拉菜单打开: {dropdown_open}")

    # ====== Step 2: 点击下拉菜单中的"登录" ======
    print("  [2/3] 点击下拉菜单'登录'...")
    login_item_clicked = await page.evaluate("""() => {
        // Element UI dropdown: .el-dropdown-menu__item 或 li
        const candidates = document.querySelectorAll(
            '.el-dropdown-menu__item, li, .el-popper li, [role="menuitem"]'
        );
        for (const el of candidates) {
            const txt = (el.textContent || '').trim();
            if (txt === '登录' || txt === '登录账号') {
                el.click();
                return 'clicked: ' + txt;
            }
        }
        // fallback: 找包含"登录"文本的可见元素
        const all = document.querySelectorAll('li, span, div');
        for (const el of all) {
            if (el.textContent?.trim() === '登录' && el.offsetParent !== null) {
                el.click();
                return 'fallback clicked';
            }
        }
        return 'NOT FOUND';
    }""")
    print(f"  结果: {login_item_clicked}")
    await asyncio.sleep(1.5)

    # ====== Step 3: 检查登录弹窗是否打开，点击"微信登录" ======
    dialog_opened = await page.evaluate("""() => {
        const wrapper = document.querySelector('.el-dialog__wrapper[aria-label="登录"]');
        if (!wrapper) return {open: false, reason: 'no wrapper'};
        const display = window.getComputedStyle(wrapper).display;
        return {open: display !== 'none', display};
    }""")
    print(f"  登录弹窗: {dialog_opened}")

    if not dialog_opened.get('open'):
        # 弹窗没开，可能：1) 已登录 2) 点击错元素 3) Vue 未响应
        # 检查是否已登录
        has_token = await page.evaluate("!!localStorage.getItem('aiGenAccessToken')")
        if has_token:
            print("  ℹ️ 已登录，跳过弹窗触发")
            return True
        print("  [FAIL] 弹窗未打开，可能点击链未触发。尝试备用方法...")
        # 备用：直接用 JS 修改 display
        await page.evaluate("""() => {
            const w = document.querySelector('.el-dialog__wrapper[aria-label="登录"]');
            if (w) w.style.display = '';
        }""")
        await asyncio.sleep(1)

    # 点击"微信登录"
    print("  [3/3] 点击'微信登录'选项...")
    wechat_clicked = await page.evaluate("""() => {
        const options = document.querySelectorAll('.login-option');
        for (const opt of options) {
            const img = opt.querySelector('img[alt="wechat"]');
            if (img || opt.textContent.includes('微信登录')) {
                opt.click();
                return 'clicked';
            }
        }
        // fallback
        const wechatImg = document.querySelector('img[alt="wechat"]');
        if (wechatImg) {
            wechatImg.closest('div')?.click();
            return 'img clicked';
        }
        return 'no wechat option';
    }""")
    print(f"  结果: {wechat_clicked}")
    await asyncio.sleep(2)

    # ====== 验证 QR iframe 是否加载 ======
    qr_loaded = await page.evaluate("""() => {
        const iframes = document.querySelectorAll('iframe');
        for (const f of iframes) {
            if (f.src.includes('open.weixin.qq.com') || f.src.includes('qrconnect')) {
                return {found: true, src: f.src.substring(0, 300)};
            }
        }
        return {found: false, totalIframes: iframes.length};
    }""")
    print(f"  QR iframe: {qr_loaded}")

    if qr_loaded.get('found'):
        print("  [OK] 微信二维码已加载！")
        return True
    else:
        print("  [WARN] 未检测到二维码 iframe，但可能正在加载...")
        # 再等几秒
        await asyncio.sleep(3)
        qr_retry = await page.evaluate("""() => {
            const iframes = document.querySelectorAll('iframe');
            for (const f of iframes) {
                if (f.src.includes('open.weixin.qq.com') || f.src.includes('qrconnect')) {
                    return {found: true, src: f.src.substring(0, 300)};
                }
            }
            return {found: false};
        }""")
        return qr_retry.get('found', False)


# ===================== 主流程 =====================

async def open_matrix_page(page) -> None:
    """Open Zhuque page without requiring networkidle, which can hang on long-lived assets."""
    print(f"\n[open] 打开 {MATRIX_URL}")
    try:
        await page.goto(MATRIX_URL, wait_until="domcontentloaded", timeout=60000)
    except PwTimeout as exc:
        print(f"  [WARN] 页面 domcontentloaded 等待超时，继续尝试检查当前页面: {exc}")
    except Exception as exc:
        print(f"  [WARN] 页面打开异常，继续尝试检查当前页面: {exc}")
    try:
        await page.wait_for_load_state("load", timeout=15000)
    except Exception:
        print("  [note] load 状态未完全结束，可能有长连接/埋点请求；继续登录检测")
    await asyncio.sleep(1)


async def capture_flow(headless=False, force_login=False, sync_session=False):
    """打开浏览器 → 触发/同步登录 → 提取凭证 → 保存。"""
    pw = await async_playwright().start()

    browser_executable = find_browser_executable()
    browser = None
    ctx = None
    windows_chrome_mode = (
        sync_session
        and not headless
        and not _is_truthy_env("ZHUQUE_DISABLE_WINDOWS_CHROME")
        and _is_wsl()
        and is_windows_browser_executable(browser_executable)
    )

    try:
        if windows_chrome_mode:
            ok, message, cdp_endpoint = launch_windows_chrome_for_cdp(browser_executable)
            print(f"  [browser] {message}")
            if not ok:
                print("  [browser] 回退到 Playwright 内置/本机 Chromium")
                windows_chrome_mode = False

        if windows_chrome_mode:
            browser = await pw.chromium.connect_over_cdp(cdp_endpoint)
            contexts = browser.contexts
            ctx = contexts[0] if contexts else await browser.new_context()
            existing_pages = [candidate for candidate in ctx.pages if not candidate.is_closed()]
            page = next((candidate for candidate in existing_pages if "matrix.tencent.com/ai-detect" in candidate.url), None)
            if page is None:
                page = existing_pages[0] if existing_pages else await ctx.new_page()
            print(f"  [browser] 使用 Windows Chrome 小窗: {browser_executable}")
        else:
            launch_kwargs = {
                "headless": headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            }
            if browser_executable and not is_windows_browser_executable(browser_executable):
                launch_kwargs["executable_path"] = browser_executable
                print(f"  [browser] 使用系统浏览器: {browser_executable}")
            else:
                if browser_executable and is_windows_browser_executable(browser_executable):
                    print("  [browser] Windows Chrome 仅支持同步扫码小窗模式，当前回退到 Playwright 内置 Chromium")
                else:
                    print("  [browser] 未找到系统 Chromium 内核浏览器，尝试使用 Playwright 内置 Chromium")

            browser = await pw.chromium.launch(**launch_kwargs)
            ctx_kwargs = {
                "viewport": {"width": 1280, "height": 720},
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            }
            if STORAGE_STATE_FILE.exists():
                ctx_kwargs["storage_state"] = str(STORAGE_STATE_FILE)
                print(f"  [load] 恢复浏览器会话（{STORAGE_STATE_FILE.name}）")
            ctx = await browser.new_context(**ctx_kwargs)
            page = await ctx.new_page()

        print(f"\n{'='*60}")
        print("  朱雀凭证捕获工具 v2.0")
        if sync_session and windows_chrome_mode:
            mode_label = "Windows Chrome 小窗状态同步"
        elif sync_session:
            mode_label = "真实网页状态同步"
        else:
            mode_label = "可见浏览器" if not headless else "无头（仅测试已登录态）"
        print(f"  模式: {mode_label}")
        print(f"{'='*60}")

        # 打开页面。不要等待 networkidle：朱雀页面有长连接/埋点请求，可能永远不 idle。
        await open_matrix_page(page)

        if sync_session:
            return await sync_session_until_closed(page, ctx, trigger_login_when_missing=True)

        # 检查是否已登录。朱雀前端偶尔会调整 token 存储 key，所以这里不只看 aiGenAccessToken。
        auth_state = await inspect_auth_state(page)
        token = auth_state.get("token") or ""
        user_name = (auth_state.get("userName") or "").strip()
        needs_login = False

        if token:
            print(f"  [info] 浏览器已有登录态: {user_name}")
            print(f"   Token 来源: {auth_state.get('tokenSource') or '?'}，前60字符: {token[:60]}...")

            if force_login:
                print("\n  [switch] 强制切号模式 — 先退出当前账号")
                ok = await perform_logout(page)
                if not ok:
                    print("  [WARN] 退出可能未完全成功，但继续流程...")
                needs_login = True
                token = ""
                user_name = ""
            else:
                print("   （非切号模式，直接提取已有凭证）")
        elif auth_state.get("ready"):
            print(f"  [info] 浏览器已有登录态: {user_name or '未知用户'}（未发现显式 token，使用 cookie/fp 凭证）")
            if force_login:
                print("\n  [switch] 强制切号模式 — 先退出当前账号")
                ok = await perform_logout(page)
                if not ok:
                    print("  [WARN] 退出可能未完全成功，但继续流程...")
                needs_login = True
            else:
                print("   （非切号模式，直接提取已有凭证）")
        else:
            print("  [user] 当前状态: 未登录（游客）")
            needs_login = True

        # ====== 按需触发登录流程 ======
        if needs_login:
            if headless:
                print("\n[FAIL] 无头模式无法显示二维码供扫码，请用可见模式运行")
                print("   用法: python capture_zhuque_creds.py [--switch]")
                return None

            triggered = await trigger_login_flow(page)
            await page.screenshot(path=str(TEMP / "qrcode_latest.png"))
            print("\n[shot] 二维码截图已保存: temp/qrcode_latest.png")

            if not triggered:
                print("\n" + "!"*50)
                print("  未能自动触发二维码")
                print("  请手动操作：点击右上角「登录」→「微信登录」")
                print("!"*50 + "\n")

            success = await wait_for_login(page, WAIT_TIMEOUT)
            if not success:
                print("\n[FAIL] 登录未完成，退出")
                return None

        print("\n[pack] 提取凭证...")
        creds = await extract_credentials(page)

        creds_file, latest_file = save_credentials(creds)

        print("\n[OK] 凭证已保存:")
        print(f"   {creds_file}")
        print(f"   {latest_file}")
        print("\n[info] 凭证摘要:")
        print(f"   用户:  {creds.get('userName', '?')}")
        print(f"   配额:  {creds.get('quotaText', '?')}")
        ls = creds.get("localStorage", {})
        print(f"   Token: {ls.get('aiGenAccessToken', '')[:60]}...")
        print(f"   FP:    {ls.get('fp', '')}")
        print(f"   Cook:  {len(creds.get('cookies', []))} 个")

        key_cookies = ["ACCESS_TOKEN", "DEFAULT_COOKIES", "JSESSIONID"]
        for c in creds.get("cookies", []):
            if c["name"] in key_cookies:
                print(f"     [cookie] {c['name']}: {c['value'][:50]}...")

        await save_browser_state(ctx)
        return creds
    finally:
        if browser:
            await browser.close()
        await pw.stop()

# ===================== 凭证加载/导出 =====================

def load_creds(filepath=None):
    if filepath is None:
        filepath = TEMP / "creds_latest.json"
    else:
        filepath = Path(filepath)
    if not filepath.exists():
        print(f"[FAIL] 文件不存在: {filepath}")
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def print_creds_summary(creds):
    print(f"\n[info] 凭证文件")
    print(f"   用户: {creds.get('userName', '?')}")
    print(f"   配额: {creds.get('quotaText', '?')}")
    print(f"   时间: {creds.get('timestamp', '?')}")
    ls = creds.get('localStorage', {})
    print(f"   Token: {ls.get('aiGenAccessToken', '')[:60]}...")
    print(f"   FP: {ls.get('fp', '')}")
    print(f"   localStorage ({len(ls)} keys):")
    for k, v in ls.items():
        print(f"     {k}: {str(v)[:60]}")
    cookies = creds.get('cookies', [])
    print(f"   Cookies ({len(cookies)}):")
    for c in cookies:
        print(f"     {c['name']}: {c['value'][:50]}{'...' if len(c['value'])>50 else ''}")


def export_shell(creds_file=None):
    """导出为 shell 环境变量"""
    creds = load_creds(creds_file)
    if not creds:
        return
    ls = creds.get('localStorage', {})
    token = ls.get('aiGenAccessToken', '')
    fp = ls.get('fp', '')
    cookie_str = creds.get('cookieString', '')
    print(f'export ZHUQUE_TOKEN="{token}"')
    print(f'export ZHUQUE_FP="{fp}"')
    print(f'export ZHUQUE_COOKIES="{cookie_str}"')
    # 单独 key cookies
    for c in creds.get('cookies', []):
        if c['name'] in ['ACCESS_TOKEN', 'DEFAULT_COOKIES']:
            print(f'export ZHUQUE_{c["name"]}="{c["value"]}"')


def export_json_creds(creds_file=None):
    """
    导出为 zhuque_api_headless.py 可直接使用的 JSON 格式
    输出到 stdout，可管道到文件
    """
    creds = load_creds(creds_file)
    if not creds:
        return
    ls = creds.get('localStorage', {})
    # 提取关键字段
    exported = {
        "access_token": ls.get('aiGenAccessToken', ''),
        "fp": ls.get('fp', ''),
        "cookies": creds.get('cookieString', ''),
        "cookies_list": creds.get('cookies', []),
        "user_name": creds.get('userName', ''),
        "quota_text": creds.get('quotaText', ''),
        "captured_at": creds.get('timestamp', ''),
        "localStorage": ls,
    }
    print(json.dumps(exported, ensure_ascii=False, indent=2))


# ===================== CLI =====================

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="朱雀凭证捕获工具 — 微信扫码登录自动提取凭证",
        epilog=(
            "示例: python capture_zhuque_creds.py                  # 打开浏览器扫码\n"
            "      python capture_zhuque_creds.py --sync-session   # 同步真实网页登录/退出状态\n"
            "      python capture_zhuque_creds.py --switch         # 旧切号：退出→重新扫码\n"
            "      python capture_zhuque_creds.py --load           # 查看已保存凭证\n"
            "      python capture_zhuque_creds.py --export-shell   # 导出环境变量"
        )
    )
    pg = p.add_mutually_exclusive_group()
    pg.add_argument("--load", nargs="?", const="latest", metavar="FILE",
                    help="加载凭证文件并显示摘要 (默认: creds_latest.json)")
    pg.add_argument("--export-shell", nargs="?", const="latest", metavar="FILE",
                    help="导出为 shell 环境变量")
    pg.add_argument("--export-json-creds", nargs="?", const="latest", metavar="FILE",
                    help="导出为 zhuque_api_headless.py 可用的 JSON credentials")
    p.add_argument("--sync-session", action="store_true",
                   help="真实状态同步：打开朱雀页，不自动退出；登录则保存凭证，网页内退出才清除凭证")
    p.add_argument("--switch", action="store_true",
                   help="旧切号模式：先自动退出当前登录，再扫码换号")
    p.add_argument("--headless", action="store_true",
                   help="无头模式（仅当已有登录态时可用，无法扫码）")
    args = p.parse_args()

    if args.load:
        creds = load_creds(None if args.load == "latest" else args.load)
        if creds:
            print_creds_summary(creds)
    elif args.export_shell:
        export_shell(None if args.export_shell == "latest" else args.export_shell)
    elif args.export_json_creds:
        export_json_creds(None if args.export_json_creds == "latest" else args.export_json_creds)
    else:
        asyncio.run(capture_flow(headless=args.headless, force_login=args.switch, sync_session=args.sync_session))

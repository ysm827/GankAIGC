"""Remote Zhuque QR login sessions for VPS deployments.

The visible browser window used by the old local workflow runs on the backend
host. On a VPS that is useless to a user browsing from another computer, so this
service runs a headless Chromium on the server, screenshots the WeChat QR code,
and exposes a polling API. Credentials are stored under a per-user directory.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.config import settings
from app.services.zhuque_service import zhuque_user_dir

logger = logging.getLogger(__name__)

MATRIX_URL = "https://matrix.tencent.com/ai-detect/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
REMOTE_LOGIN_TIMEOUT_SECONDS = 180
REMOTE_LOGIN_QR_REFRESH_SECONDS = 0.9
REMOTE_LOGIN_POLL_SECONDS = 0.55


def _playwright_browsers_path() -> Path:
    """Return the project-local Playwright browser cache used by packaged runs."""
    return Path(__file__).resolve().parents[3] / ".playwright-browsers"


def _playwright_executable_path() -> str | None:
    """Use an installed Chromium executable if Playwright's default cache misses.

    Local/one-click runs install browsers under `package/.playwright-browsers`.
    Without this, Playwright looks in `~/.cache/ms-playwright` and remote QR
    login fails even though the project already has Chromium available.
    """
    browser_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or _playwright_browsers_path())
    candidates = [
        *browser_root.glob("chromium-*/chrome-linux64/chrome"),
        *browser_root.glob("chromium-*/chrome-linux/chrome"),
        *browser_root.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"),
        *browser_root.glob("chromium_headless_shell-*/chrome-headless-shell-linux/chrome-headless-shell"),
    ]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _parse_remaining_uses(text: str) -> int:
    import re

    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else -1


def _normalise_login_text(text: str) -> str:
    import re

    return re.sub(r"\s+", "", str(text or "").strip()).lower()


def _is_login_prompt_text(text: str) -> bool:
    return _normalise_login_text(text) in {
        "login",
        "log in",
        "signin",
        "sign in",
        "登录",
        "微信登录",
        "扫码登录",
    }


def _pick_local_storage_token(local_storage: dict) -> tuple[str, str]:
    token_keys = [
        "aiGenAccessToken",
        "access_token",
        "accessToken",
        "token",
        "authToken",
    ]
    for key in token_keys:
        value = local_storage.get(key)
        token = _unwrap_token_value(value)
        if token:
            return token, key
    for key, value in local_storage.items():
        lower_key = str(key).lower()
        if "token" in lower_key and ("access" in lower_key or "auth" in lower_key):
            token = _unwrap_token_value(value)
            if token:
                return token, str(key)
    return "", ""


def _unwrap_token_value(value) -> str:
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


def _pick_cookie_value(cookies: list, names: tuple[str, ...]) -> tuple[str, str]:
    wanted = {name.lower() for name in names}
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "")
        if name.lower() in wanted and cookie.get("value"):
            return str(cookie["value"]), name
    return "", ""


def _auth_state_from_browser_snapshot(browser_state: dict, cookies: list) -> dict:
    local_storage = browser_state.get("localStorage", {}) or {}
    token, token_source = _pick_local_storage_token(local_storage)
    if not token:
        token, token_source = _pick_cookie_value(cookies, ("ACCESS_TOKEN", "access_token", "accessToken"))
    user_name = (
        browser_state.get("userName")
        or browser_state.get("user_name")
        or browser_state.get("userInfoText")
        or ""
    ).strip()
    if _is_login_prompt_text(user_name):
        user_name = ""
    quota_text = (
        browser_state.get("quotaText")
        or browser_state.get("quota_text")
        or browser_state.get("submitButtonText")
        or ""
    ).strip()
    remaining_uses = browser_state.get("remainingUses", browser_state.get("remaining_uses", -1))
    try:
        remaining_uses = int(remaining_uses)
    except (TypeError, ValueError):
        remaining_uses = _parse_remaining_uses(quota_text)
    has_anonymous_fp = bool((local_storage.get("fp") or browser_state.get("fp")) and not token)
    ready = bool(token or user_name)
    return {
        "ready": ready,
        "token": token,
        "tokenSource": token_source,
        "fp": local_storage.get("fp") or browser_state.get("fp") or "",
        "hasAnonymousFp": has_anonymous_fp,
        "userName": user_name,
        "quotaText": quota_text,
        "submitButtonText": browser_state.get("submitButtonText") or "",
        "remainingUses": remaining_uses,
        "loginPromptVisible": bool(browser_state.get("loginPromptVisible")),
        "localStorage": local_storage,
        "cookies": cookies or [],
        "url": browser_state.get("url") or MATRIX_URL,
        "timestamp": browser_state.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def credentials_from_auth_state(auth_state: dict) -> dict:
    cookies = auth_state.get("cookies") or []
    local_storage = auth_state.get("localStorage", {}) or {}
    creds = {
        "localStorage": local_storage,
        "userName": auth_state.get("userName") or "",
        "avatarUrl": auth_state.get("avatarUrl") or "",
        "quotaText": auth_state.get("quotaText") or auth_state.get("submitButtonText") or "",
        "submitButtonText": auth_state.get("submitButtonText") or "",
        "url": auth_state.get("url") or MATRIX_URL,
        "timestamp": auth_state.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cookies": cookies,
        "cookieString": "; ".join([f"{c.get('name')}={c.get('value')}" for c in cookies if c.get("name")]),
    }
    token = auth_state.get("token") or ""
    token_source = auth_state.get("tokenSource") or ""
    if not token:
        token, token_source = _pick_local_storage_token(local_storage)
    if not token:
        token, token_source = _pick_cookie_value(cookies, ("ACCESS_TOKEN", "access_token", "accessToken"))
    if token:
        creds["access_token"] = token
        creds["access_token_source"] = token_source
    if local_storage.get("fp") or auth_state.get("fp"):
        creds["fp"] = local_storage.get("fp") or auth_state.get("fp")
    creds["remainingUses"] = auth_state.get("remainingUses", _parse_remaining_uses(creds["quotaText"] or creds["submitButtonText"]))
    return creds


def _page_navigation_context_destroyed(exc: Exception) -> bool:
    message = str(exc).lower()
    return "execution context was destroyed" in message or "navigation" in message and "context" in message


async def _evaluate_after_navigation(page, script: str, *, retries: int = 3):
    last_exc = None
    for attempt in range(max(1, retries)):
        try:
            return await page.evaluate(script)
        except Exception as exc:
            last_exc = exc
            if not _page_navigation_context_destroyed(exc) or attempt >= retries - 1:
                raise
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            with contextlib.suppress(Exception):
                await page.wait_for_timeout(300)
    raise last_exc or RuntimeError("page.evaluate failed")


async def inspect_auth_state(page) -> dict:
    browser_state = await _evaluate_after_navigation(
        page,
        r"""
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
                if (/(今日剩余|剩余.*次|可用.*次|\d+\s*left)/i.test(txt) && txt.length < bestLen && txt.length < 100) {
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
                url: location.href,
                timestamp: new Date().toISOString()
            };
        })()
        """
    )
    cookies = await page.context.cookies()
    return _auth_state_from_browser_snapshot(browser_state, cookies)


async def trigger_login_flow(page) -> bool:
    """Open Zhuque's WeChat QR login dialog through the real page click chain."""
    try:
        await page.wait_for_selector(".user-info", state="visible", timeout=5000)
        await page.click(".user-info")
    except Exception:
        await _evaluate_after_navigation(page, "document.querySelector('.user-info, .user-name')?.click()")
    await page.wait_for_timeout(800)

    await _evaluate_after_navigation(
        page,
        r"""
        () => {
            const isVisible = (el) => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const menuCandidates = document.querySelectorAll('.el-dropdown-menu__item, .el-popper li, [role="menuitem"]');
            for (const el of menuCandidates) {
                const txt = (el.textContent || '').trim();
                if (isVisible(el) && ['Login', 'Log in', 'Sign in', '登录', '登录账号', '账号登录'].includes(txt)) {
                    el.click();
                    return true;
                }
            }
            const candidates = document.querySelectorAll('li, button, a');
            for (const el of candidates) {
                const txt = (el.textContent || '').trim();
                if (isVisible(el) && ['Login', 'Log in', 'Sign in', '登录', '登录账号', '账号登录'].includes(txt)) {
                    el.click();
                    return true;
                }
            }
            return false;
        }
        """
    )
    await page.wait_for_timeout(1200)

    try:
        await page.wait_for_selector(".login-dialog .login-option, .login-option", state="visible", timeout=8000)
        await page.click(".login-dialog .login-option, .login-option", timeout=5000)
    except Exception:
        await _evaluate_after_navigation(
            page,
            r"""
            () => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const options = document.querySelectorAll('.login-option, [class*="login-option"], [class*="wechat"], [class*="weixin"]');
                for (const opt of options) {
                    const img = opt.querySelector('img[alt*="wechat" i], img[alt*="weixin" i], img[src*="wechat" i], img[src*="weixin" i]');
                    const txt = (opt.textContent || '').trim();
                    if (isVisible(opt) && (img || /微信|wechat|weixin/i.test(txt))) {
                        opt.click();
                        return true;
                    }
                }
                const wechatImg = document.querySelector('img[alt*="wechat" i], img[alt*="weixin" i], img[src*="wechat" i], img[src*="weixin" i]');
                if (wechatImg) { wechatImg.closest('div')?.click(); return true; }
                const textNodes = [...document.querySelectorAll('button, a, span, div, li')]
                    .filter(isVisible)
                    .find(el => /微信|wechat|weixin/i.test((el.textContent || '').trim()));
                if (textNodes) { textNodes.click(); return true; }
                return false;
            }
            """
        )
    with contextlib.suppress(Exception):
        await page.wait_for_function(
            "() => [...document.querySelectorAll('iframe')].some(f => /open\\.weixin\\.qq\\.com|qrconnect/i.test(f.src || ''))",
            timeout=10000,
        )
    return await _evaluate_after_navigation(
        page,
        r"""
        () => [...document.querySelectorAll('iframe')]
            .some(f => /open\.weixin\.qq\.com|qrconnect/i.test(f.src || ''))
        """
    )


@dataclass
class ZhuqueRemoteLoginSession:
    session_id: str
    user_id: int
    user_dir: Path
    status: str = "starting"
    message: str = "正在启动朱雀扫码会话"
    connected: bool = False
    has_token: bool = False
    has_anonymous_fp: bool = False
    user_name: str = ""
    remaining_uses: int = -1
    quota_text: str = ""
    qr_image_data: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + REMOTE_LOGIN_TIMEOUT_SECONDS)
    task: Optional[asyncio.Task] = None
    browser: object = None
    playwright: object = None
    force_login: bool = True

    @property
    def credential_file(self) -> Path:
        return self.user_dir / "creds_latest.json"

    @property
    def storage_state_file(self) -> Path:
        return self.user_dir / "browser_state.json"

    @property
    def qrcode_file(self) -> Path:
        return self.user_dir / "qrcode_latest.png"

    @property
    def session_status_file(self) -> Path:
        return self.user_dir / "session_status.json"

    def touch(self) -> None:
        self.updated_at = time.time()

    def public_payload(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "auth_mode": "headless_api",
            "login_mode": "remote_wechat_qr",
            "credential_file": str(self.credential_file),
            "connected": self.connected,
            "ready": self.connected,
            "has_token": self.has_token,
            "has_anonymous_fp": self.has_anonymous_fp,
            "user_name": self.user_name,
            "remaining_uses": self.remaining_uses,
            "quota_text": self.quota_text,
            "qr_image_data": self.qr_image_data,
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.expires_at)),
            "message": self.message,
        }


class ZhuqueRemoteLoginService:
    def __init__(self):
        self._sessions: dict[int, ZhuqueRemoteLoginSession] = {}

    def _write_session_status(self, session: ZhuqueRemoteLoginSession, status: dict) -> None:
        payload = {
            "connected": bool(status.get("connected")),
            "ready": bool(status.get("ready")),
            "has_token": bool(status.get("has_token")),
            "has_anonymous_fp": bool(status.get("has_anonymous_fp") or status.get("hasAnonymousFp")),
            "anonymous_fp": status.get("anonymous_fp") or status.get("fp") or "",
            "remaining_uses": status.get("remaining_uses", -1),
            "user_name": status.get("user_name") or "",
            "quota_text": status.get("quota_text") or "",
            "message": status.get("message") or "",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp_file = session.session_status_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        tmp_file.replace(session.session_status_file)

    async def start(self, user_id: int, *, force_login: bool = True) -> dict:
        existing = self._sessions.get(user_id)
        if existing and existing.status in {"starting", "qr_ready", "waiting"}:
            return existing.public_payload()

        user_dir = zhuque_user_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        session = ZhuqueRemoteLoginSession(
            session_id=uuid4().hex,
            user_id=user_id,
            user_dir=user_dir,
        )
        session.force_login = force_login
        self._sessions[user_id] = session
        session.task = asyncio.create_task(self._run(session))
        return session.public_payload()

    def status(self, user_id: int, session_id: str | None = None) -> dict:
        session = self._sessions.get(user_id)
        if not session or (session_id and session.session_id != session_id):
            return {
                "session_id": session_id or "",
                "status": "not_found",
                "auth_mode": "headless_api",
                "login_mode": "remote_wechat_qr",
                "credential_file": str(zhuque_user_dir(user_id) / "creds_latest.json"),
                "connected": False,
                "ready": False,
                "has_token": False,
                "has_anonymous_fp": False,
                "user_name": "",
                "remaining_uses": -1,
                "quota_text": "",
                "qr_image_data": "",
                "expires_at": "",
                "message": "扫码会话不存在或已结束，请重新点击扫码登录",
            }
        if time.time() > session.expires_at and session.status in {"starting", "qr_ready", "waiting"}:
            session.status = "expired"
            session.message = "朱雀扫码登录已超时，请重新打开二维码"
            session.touch()
            self._schedule_close(session)
        return session.public_payload()

    async def cancel(self, user_id: int, session_id: str | None = None) -> dict:
        session = self._sessions.get(user_id)
        if not session or (session_id and session.session_id != session_id):
            return self.status(user_id, session_id)
        session.status = "cancelled"
        session.message = "已取消朱雀扫码登录"
        session.touch()
        if session.task and not session.task.done():
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.task
        await self._close_session(session)
        return session.public_payload()

    async def logout(self, user_id: int) -> dict:
        """Clear the current user's saved Zhuque credentials.

        This only logs GankAIGC out of its saved Zhuque credential snapshot. It
        cannot remotely sign the user's WeChat account out of Tencent, but the
        next detect/readiness call will use Zhuque's anonymous/free path unless
        the user scans again.
        """
        session = self._sessions.get(user_id)
        if session and session.task and not session.task.done():
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.task
        user_dir = zhuque_user_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        anonymous_fp = ""
        state_has_token = False
        state_file = user_dir / "browser_state.json"
        if state_file.exists():
            with contextlib.suppress(Exception):
                state = json.loads(state_file.read_text(encoding="utf-8"))
                origins = state.get("origins") if isinstance(state, dict) else []
                for origin in origins or []:
                    if not isinstance(origin, dict):
                        continue
                    for item in origin.get("localStorage") or []:
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("name") or "")
                        value = str(item.get("value") or "")
                        if "token" in name.lower() and value:
                            state_has_token = True
                        if name == "fp":
                            anonymous_fp = value
                            break
                    if anonymous_fp or state_has_token:
                        break
        if state_has_token:
            anonymous_fp = ""
        for filename in (
            "creds_latest.json",
            *(("browser_state.json",) if state_has_token else ()),
            "qrcode_latest.png",
        ):
            with contextlib.suppress(FileNotFoundError):
                (user_dir / filename).unlink()
        status_file = user_dir / "session_status.json"
        payload = {
            "connected": False,
            "ready": False,
            "has_token": False,
            "has_anonymous_fp": bool(anonymous_fp),
            "anonymous_fp": anonymous_fp,
            "remaining_uses": -1,
            "user_name": "",
            "quota_text": "",
            "message": "已退出朱雀登录，未登录时将使用朱雀免费次数",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp_file = status_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        tmp_file.replace(status_file)
        logged_out = ZhuqueRemoteLoginSession(
            session_id=uuid4().hex,
            user_id=user_id,
            user_dir=user_dir,
            status="logged_out",
            message=payload["message"],
            connected=False,
            has_token=False,
            has_anonymous_fp=bool(anonymous_fp),
            remaining_uses=-1,
        )
        self._sessions[user_id] = logged_out
        return logged_out.public_payload()

    def _schedule_close(self, session: ZhuqueRemoteLoginSession) -> None:
        async def closer():
            await self._close_session(session)

        try:
            asyncio.create_task(closer())
        except RuntimeError:
            pass

    async def _close_session(self, session: ZhuqueRemoteLoginSession) -> None:
        if session.browser:
            with contextlib.suppress(Exception):
                await session.browser.close()
            session.browser = None
        if session.playwright:
            with contextlib.suppress(Exception):
                await session.playwright.stop()
            session.playwright = None

    async def _run(self, session: ZhuqueRemoteLoginSession) -> None:
        try:
            try:
                from playwright.async_api import async_playwright
            except Exception as exc:
                session.status = "manual_required"
                session.message = f"当前 Python 环境未安装 Playwright，无法在 VPS 生成朱雀二维码: {exc}"
                session.touch()
                return

            session.status = "starting"
            session.message = "正在打开朱雀登录页"
            session.touch()
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_playwright_browsers_path()))
            session.playwright = await async_playwright().start()
            launch_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            executable_path = _playwright_executable_path()
            launch_kwargs = {"headless": True, "args": launch_args}
            if executable_path:
                launch_kwargs["executable_path"] = executable_path
            session.browser = await session.playwright.chromium.launch(**launch_kwargs)
            context_kwargs = {
                "viewport": {"width": 1280, "height": 860},
                "user_agent": DEFAULT_USER_AGENT,
            }
            if session.storage_state_file.exists() and not session.force_login:
                context_kwargs["storage_state"] = str(session.storage_state_file)
            ctx = await session.browser.new_context(**context_kwargs)
            page = await ctx.new_page()
            await page.goto(MATRIX_URL, wait_until="domcontentloaded", timeout=60000)
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("load", timeout=12000)
            await page.wait_for_timeout(1000)

            initial_state = await inspect_auth_state(page)
            if initial_state.get("ready") and not session.force_login:
                await self._persist_logged_in(session, ctx, initial_state)
                return

            qr_opened = await trigger_login_flow(page)
            session.status = "qr_ready" if qr_opened else "waiting"
            session.message = "请使用微信扫描二维码登录朱雀" if qr_opened else "正在调起朱雀微信登录二维码；若长时间不显示，请重试"
            session.touch()

            deadline = time.time() + REMOTE_LOGIN_TIMEOUT_SECONDS
            last_qr_capture = 0.0
            while time.time() < deadline:
                auth_state = await inspect_auth_state(page)
                if auth_state.get("ready"):
                    await self._persist_logged_in(session, ctx, auth_state)
                    return

                now = time.time()
                if now - last_qr_capture >= REMOTE_LOGIN_QR_REFRESH_SECONDS:
                    await self._refresh_qr_image(session, page)
                    last_qr_capture = now
                session.status = "qr_ready" if session.qr_image_data else "waiting"
                session.message = "请使用微信扫描二维码登录朱雀" if session.qr_image_data else "正在调起朱雀微信登录二维码；若长时间不显示，请重试"
                session.touch()
                await asyncio.sleep(REMOTE_LOGIN_POLL_SECONDS)

            session.status = "expired"
            session.message = "朱雀扫码登录已超时，请重新打开二维码"
            self._write_session_status(session, {
                "connected": False,
                "ready": False,
                "has_token": False,
                "has_anonymous_fp": bool(initial_state.get("hasAnonymousFp") or initial_state.get("fp")),
                "anonymous_fp": initial_state.get("fp") or "",
                "remaining_uses": -1,
                "user_name": "",
                "quota_text": "",
                "message": session.message,
            })
            session.touch()
        except Exception as exc:
            logger.exception("Zhuque remote login failed for user %s", session.user_id)
            session.status = "error"
            session.message = f"朱雀远程扫码登录失败: {exc}"
            session.touch()
        finally:
            if session.status in {"logged_in", "expired", "error", "cancelled", "manual_required"}:
                await self._close_session(session)

    async def _refresh_qr_image(self, session: ZhuqueRemoteLoginSession, page) -> None:
        target = None
        with contextlib.suppress(Exception):
            iframe = await page.query_selector("iframe[src*='open.weixin.qq.com'], iframe[src*='qrconnect']")
            if iframe:
                target = iframe
        screenshot = None
        if target:
            with contextlib.suppress(Exception):
                screenshot = await target.screenshot(type="png")
        if screenshot:
            session.qrcode_file.write_bytes(screenshot)
            session.qr_image_data = "data:image/png;base64," + base64.b64encode(screenshot).decode("ascii")

    async def _persist_logged_in(self, session: ZhuqueRemoteLoginSession, ctx, auth_state: dict) -> None:
        creds = credentials_from_auth_state(auth_state)
        session.user_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        snapshot_file = session.user_dir / f"creds_{timestamp}.json"
        for target in (snapshot_file, session.credential_file):
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(creds, handle, ensure_ascii=False, indent=2)
        with contextlib.suppress(Exception):
            state = await ctx.storage_state()
            with open(session.storage_state_file, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False)

        remaining_uses = creds.get("remainingUses", -1)
        try:
            remaining_uses = int(remaining_uses)
        except (TypeError, ValueError):
            remaining_uses = _parse_remaining_uses(creds.get("quotaText") or creds.get("submitButtonText") or "")
        session.status = "logged_in"
        session.connected = True
        session.has_token = bool(creds.get("access_token"))
        session.has_anonymous_fp = bool(creds.get("fp") and not session.has_token)
        session.user_name = creds.get("userName") or ""
        session.remaining_uses = remaining_uses
        session.quota_text = creds.get("quotaText") or creds.get("submitButtonText") or ""
        session.message = "朱雀扫码登录成功，已保存当前用户专属凭证"
        session.touch()
        self._write_session_status(session, {
            "connected": True,
            "ready": True,
            "has_token": session.has_token,
            "has_anonymous_fp": bool(creds.get("fp") and not session.has_token),
            "anonymous_fp": creds.get("fp") if not session.has_token else "",
            "remaining_uses": session.remaining_uses,
            "user_name": session.user_name,
            "quota_text": session.quota_text,
            "message": session.message,
        })


zhuque_remote_login_service = ZhuqueRemoteLoginService()

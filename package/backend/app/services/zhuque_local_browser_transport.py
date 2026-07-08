"""Local visible-browser transport wrapper for Zhuque desktop/one-click deployments.

This layer standardizes the local-browser contract around the backend
`ZhuqueService`/`ZhuqueAPI` implementation. It must not be used for VPS
`browser_agent` mode.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional


class LocalBrowserZhuqueTransport:
    """Adapter around a per-user ZhuqueService for local visible browser mode."""

    source = "local_browser"

    def __init__(self, service: Any, *, user_id: int):
        self.service = service
        self.user_id = int(user_id)

    def _base_payload(self, payload: dict[str, Any] | None = None, *, status: str | None = None) -> dict[str, Any]:
        payload = payload or {}
        ready = bool(payload.get("ready") or payload.get("connected") or payload.get("has_token"))
        remaining_uses = payload.get("remaining_uses", -1)
        try:
            remaining_uses = int(remaining_uses)
        except (TypeError, ValueError):
            remaining_uses = -1
        connected = bool(payload.get("connected") or payload.get("has_token") or payload.get("logged_in") or payload.get("status") == "logged_in")
        ready = bool(ready or connected)
        return {
            "status": status or payload.get("status") or ("logged_in" if connected else "missing_credentials"),
            "transport": self.source,
            "auth_mode": self.source,
            "login_mode": self.source,
            "connected": connected,
            "logged_in": connected,
            "ready": ready,
            "page_found": bool(payload.get("page_found") or connected),
            "has_token": connected,
            "has_anonymous_fp": bool(payload.get("has_anonymous_fp")),
            "remaining_uses": remaining_uses,
            "button_enabled": bool(payload.get("button_enabled", remaining_uses != 0)),
            "credential_file": payload.get("credential_file", ""),
            "user_name": payload.get("user_name", "") or payload.get("userName", ""),
            "quota_text": payload.get("quota_text", "") or payload.get("quotaText", ""),
            "captured_at": payload.get("captured_at", ""),
            "message": payload.get("message", ""),
            "actions": payload.get("actions", []),
        }

    def status(self) -> dict[str, Any]:
        """Return persisted local Zhuque credential/session status without opening a new window."""
        api = self.service._ensure_api()
        payload = api.credential_status()
        cached_remaining = getattr(self.service, "cached_remaining_uses", lambda: None)()
        if cached_remaining is not None:
            payload = {
                **payload,
                "remaining_uses": cached_remaining,
                "quota_text": f"剩余 {cached_remaining} 次",
                "button_enabled": cached_remaining > 0,
            }
        normalized = self._base_payload(payload)
        normalized["message"] = normalized["message"] or (
            "本机朱雀页面已登录" if normalized["connected"] else "本机朱雀页面未登录；请打开朱雀页面完成登录/验证码"
        )
        return normalized

    async def sync_status(self) -> dict[str, Any]:
        """Refresh local Zhuque status/quota through the existing no-consume probe."""
        refresh_free_quota = getattr(self.service, "refresh_free_quota", None)
        if callable(refresh_free_quota):
            payload = await refresh_free_quota()
        else:
            payload = await self.service.readiness()
        normalized = self._base_payload(payload)
        normalized["status"] = "synced" if normalized["ready"] or normalized["page_found"] else normalized["status"]
        normalized["message"] = normalized["message"] or "本机朱雀状态已同步"
        return normalized

    async def focus_window(self) -> dict[str, Any]:
        """Focus an existing reusable Zhuque detection window when present."""
        focus_detection_window = getattr(self.service, "focus_detection_window", None)
        if not callable(focus_detection_window):
            return self._base_payload({"message": "当前朱雀检测服务不支持窗口聚焦"}, status="unavailable")
        result = await focus_detection_window()
        if isinstance(result, dict) and result.get("available"):
            focused = self._base_payload(
                {
                    **result,
                    "ready": True,
                    "connected": bool(result.get("connected") or result.get("has_token") or result.get("logged_in")),
                    "page_found": True,
                    "message": result.get("message") or "已聚焦本机朱雀检测窗口",
                },
                status="focused",
            )
            with_status = await self.sync_status()
            return {
                **focused,
                **with_status,
                "status": "focused" if with_status.get("connected") or with_status.get("has_token") else focused.get("status", "focused"),
                "message": with_status.get("message") or focused.get("message") or "已聚焦本机朱雀检测窗口",
            }
        return self._base_payload(result if isinstance(result, dict) else {}, status="not_found")

    async def open_page(
        self,
        *,
        open_capture: Optional[Callable[[], dict[str, Any] | Awaitable[dict[str, Any]]]] = None,
    ) -> dict[str, Any]:
        """Focus current window first; otherwise invoke the legacy visible-window launcher."""
        focused = await self.focus_window()
        if focused.get("status") == "focused" or focused.get("page_found"):
            focused["message"] = focused.get("message") or "已复用本机朱雀页面"
            return focused

        open_detection_page = getattr(self.service, "open_detection_page", None)
        if callable(open_detection_page):
            opened = await open_detection_page()
            if isinstance(opened, dict) and (opened.get("available") or opened.get("status") == "opened"):
                payload = self._base_payload(
                    {
                        **opened,
                        "ready": True,
                        "page_found": True,
                        "message": opened.get("message") or "已打开本机朱雀页面",
                    },
                    status="opened",
                )
                payload["url"] = opened.get("url", "")
                return payload
            focused = self._base_payload(opened if isinstance(opened, dict) else focused, status="manual_required")

        if open_capture is None:
            focused["message"] = focused.get("message") or "未找到可复用的本机朱雀页面"
            return focused
        launched = open_capture()
        if hasattr(launched, "__await__"):
            launched = await launched  # type: ignore[assignment]
        payload = self._base_payload(launched if isinstance(launched, dict) else {}, status=(launched or {}).get("status", "started") if isinstance(launched, dict) else "started")
        payload["sync_session"] = bool((launched or {}).get("sync_session", True)) if isinstance(launched, dict) else True
        payload["command"] = (launched or {}).get("command") if isinstance(launched, dict) else None
        payload["session_id"] = (launched or {}).get("session_id", "") if isinstance(launched, dict) else ""
        payload["qr_image_data"] = (launched or {}).get("qr_image_data", "") if isinstance(launched, dict) else ""
        payload["expires_at"] = (launched or {}).get("expires_at", "") if isinstance(launched, dict) else ""
        payload["message"] = payload.get("message") or "已打开本机朱雀页面，请在该窗口完成登录/验证码"
        return payload

    async def detect(self, text: str) -> dict[str, Any]:
        """Delegate detection to the existing local Zhuque service."""
        return await self.service.detect(text)

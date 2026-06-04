import os
import platform
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from app.config import settings


ZHUQUE_DETECT_URL = "https://matrix.tencent.com/ai-detect/"


def _candidate_chrome_paths() -> list[Path]:
    candidates: list[Path] = []
    if os.name == "nt":
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
        candidates.append(Path("C:/Program Files/Google/Chrome/Application/chrome.exe"))
        candidates.append(Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"))
    elif platform.system() == "Darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            candidates.append(Path(name))
    return candidates


def find_chrome_executable() -> Optional[str]:
    for candidate in _candidate_chrome_paths():
        if candidate.is_absolute() and candidate.exists():
            return str(candidate)

    if os.name != "nt":
        import shutil

        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            resolved = shutil.which(name)
            if resolved:
                return resolved
    return None


def get_zhuque_user_data_dir(port: int) -> str:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return str(Path(base) / f"GankAIGC-Chrome-CDP-{port}")


def launch_zhuque_chrome() -> dict:
    chrome_path = find_chrome_executable()
    if not chrome_path:
        raise RuntimeError("未找到 Chrome 浏览器，请先安装 Google Chrome 后再使用朱雀 AI 检测")

    port = int(settings.ZHUQUE_CDP_PORT)
    user_data_dir = get_zhuque_user_data_dir(port)
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        ZHUQUE_DETECT_URL,
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {
        "status": "started",
        "port": port,
        "url": ZHUQUE_DETECT_URL,
        "user_data_dir": user_data_dir,
    }


def get_zhuque_browser_status() -> dict:
    port = int(settings.ZHUQUE_CDP_PORT)
    version_url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=1.5) as response:
            if response.status == 200:
                return {
                    "status": "connected",
                    "connected": True,
                    "port": port,
                    "url": ZHUQUE_DETECT_URL,
                    "message": "Chrome CDP 已连接",
                }
    except (OSError, urllib.error.URLError, TimeoutError):
        pass

    return {
        "status": "disconnected",
        "connected": False,
        "port": port,
        "url": ZHUQUE_DETECT_URL,
        "message": f"未连接到 Chrome CDP 端口 {port}",
    }

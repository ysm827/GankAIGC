# GankAIGC Zhuque Browser Agent

Chrome extension MVP for VPS deployments where Zhuque detects/fights server-side headless browsers.

## Purpose

When GankAIGC runs on a VPS, Zhuque detection should execute in the user's local Chrome instead of the VPS Chromium process.

Flow:

```text
GankAIGC VPS creates Zhuque browser-agent job
↓
Chrome extension claims job
↓
Extension opens/reuses https://matrix.tencent.com/ai-detect/
↓
User's local Chrome session/IP/login state performs Zhuque detection
↓
Extension returns result to VPS
```

## Load unpacked extension

1. Open Chrome: `chrome://extensions`.
2. Enable `Developer mode`.
3. Click `Load unpacked`.
4. Select this `browser-extension/` directory.

## Host permissions

MVP manifest includes:

```json
"host_permissions": [
  "https://matrix.tencent.com/*",
  "http://127.0.0.1:9800/*",
  "http://localhost:9800/*"
]
```

For a real VPS domain, add your GankAIGC origin before loading the extension, for example:

```json
"https://gankaigc.example.com/*"
```

Do not add `<all_urls>`.

## Pairing

1. In GankAIGC workspace, generate a browser-agent pairing code.
2. Open the extension popup.
3. Enter:
   - GankAIGC server URL, e.g. `https://gankaigc.example.com`.
   - Pairing code, e.g. `GANK-7K29`.
   - Device name.
4. Click `配对插件`.

The extension stores only the server URL, agent id, and agent token in `chrome.storage.local`.

## Runtime

- Keep Chrome open while VPS tasks run.
- Log in to Zhuque in the local Chrome tab when prompted.
- If CAPTCHA appears, complete it in the local Zhuque tab; the backend will keep waiting until the job completes or times out.

## Current MVP limitations

- Developer-mode/unpacked extension only.
- One recent online agent is selected by backend.
- DOM/network extraction is best-effort and may need adjustments if Zhuque changes page structure.
- Official Chrome Web Store packaging is out of scope for the MVP.

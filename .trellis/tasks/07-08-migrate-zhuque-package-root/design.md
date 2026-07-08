# Design: move root `zhuque_pkg` into backend internals

## Current shape

```text
GankAIGC/
  zhuque_pkg/
    capture_zhuque_creds.py       # legacy visible capture script still referenced
    zhuque_api.py                 # old standalone API copy, not imported by backend core
    README.md
    requirements.txt
    users/                        # ignored runtime credentials/cache
```

Backend core Zhuque code already lives under:

```text
package/backend/app/services/zhuque_api.py
package/backend/app/services/zhuque_service.py
package/backend/app/services/zhuque_local_browser_transport.py
package/backend/app/services/zhuque_browser_agent_transport.py
package/backend/app/services/zhuque_remote_login_service.py
```

## Target shape

```text
GankAIGC/
  package/
    backend/
      app/
        services/
          zhuque_api.py
          zhuque_service.py
          zhuque_local_browser_transport.py
          zhuque_browser_agent_transport.py
          zhuque_remote_login_service.py
        tools/
          zhuque_capture_window.py
    data/
      zhuque/
        users/                    # ignored local/source runtime data
```

## Data root contract

`zhuque_user_data_root()` keeps env override first:

```text
ZHUQUE_USER_DATA_DIR -> if configured
package/data/zhuque/users -> default source/local fallback
```

One-click remains configured via `.env`:

```text
ZHUQUE_USER_DATA_DIR=data\zhuque\users
```

## Legacy capture script contract

The old visible capture script is moved to:

```text
package/backend/app/tools/zhuque_capture_window.py
```

Routes should locate it via a new helper that prefers this internal tool. The legacy command copy should be updated from:

```text
python zhuque_pkg/capture_zhuque_creds.py --sync-session
```

to:

```text
python package/backend/app/tools/zhuque_capture_window.py --sync-session
```

The actual subprocess still runs the script by absolute path using `sys.executable`, so runtime behavior is unchanged.

## Files to remove

- Runtime local cache:
  - `zhuque_pkg/__pycache__/`
  - `zhuque_pkg/users/`
- Old root source files:
  - `zhuque_pkg/README.md`
  - `zhuque_pkg/capture_zhuque_creds.py` after move
  - `zhuque_pkg/requirements.txt`
  - `zhuque_pkg/zhuque_api.py`

`zhuque_pkg/zhuque_api.py` is intentionally removed because backend imports `app.services.zhuque_api` as the canonical implementation.

## Documentation/spec updates

Replace user-facing and spec paths:

```text
zhuque_pkg/users/user_<id>/...
```

with:

```text
package/data/zhuque/users/user_<id>/...
```

Update references that describe the legacy capture script path.

## Risk and rollback

Risk: tests that dynamically import the old script path need updating.

Rollback: restore `zhuque_pkg/capture_zhuque_creds.py`, revert route path helper and default data root.

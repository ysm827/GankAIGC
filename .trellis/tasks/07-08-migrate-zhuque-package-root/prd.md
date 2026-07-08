# Migrate Zhuque package out of repo root

## Goal

Remove the visually abrupt root-level `zhuque_pkg/` package from the repository while preserving Zhuque local/one-click/browser-agent behavior.

## User value

- The repository root should not contain a standalone Zhuque package that looks unrelated to GankAIGC.
- Runtime Zhuque cache/credentials should live under an app data directory, not under a root source package.
- Legacy local-window capture functionality should remain available from an internal backend tool location until it is fully retired.

## Confirmed facts

- Git tracks only four files under the old root package:
  - `zhuque_pkg/README.md`
  - `zhuque_pkg/capture_zhuque_creds.py`
  - `zhuque_pkg/requirements.txt`
  - `zhuque_pkg/zhuque_api.py`
- Ignored local/runtime data exists under:
  - `zhuque_pkg/__pycache__/`
  - `zhuque_pkg/users/`
- Backend core Zhuque implementation lives in `package/backend/app/services/`.
- Backend still uses the old root package for:
  - default local source runtime data: `zhuque_pkg/users`
  - legacy visible capture script path: `zhuque_pkg/capture_zhuque_creds.py`
- Windows one-click already defaults to `data\zhuque\users`.

## Requirements

1. Delete local ignored Zhuque cache from the working tree.
2. Move the legacy visible Zhuque capture script into the backend tree.
3. Change local/source default Zhuque runtime data root to `package/data/zhuque/users`.
4. Remove the root-level `zhuque_pkg/` source directory from Git.
5. Remove or update code, tests, docs, and specs that reference the old root path.
6. Keep one-click behavior unchanged.
7. Preserve compatibility behavior of legacy local-window capture endpoints where tests cover it.

## Acceptance criteria

- `git ls-files zhuque_pkg` returns no files.
- `test -d zhuque_pkg` is false after cleanup.
- `git grep zhuque_pkg -- package README.md .trellis/spec` returns no active code/public doc references.
- `package/backend/app/tools/zhuque_capture_window.py` exists and is used by the legacy capture route.
- Default source/local Zhuque data root is `package/data/zhuque/users` unless `ZHUQUE_USER_DATA_DIR` is configured.
- Tests pass:
  - `package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q`
  - `package/venv/bin/python -m pytest package/backend/tests/test_release_workflow.py -q`

## Out of scope

- Rewriting the full Zhuque real-page detector.
- Removing browser-agent mode.
- Rebuilding the one-click ZIP unless source changes require a new release artifact.
- Preserving old local Zhuque login cache; users may need to log in again after the cleanup.

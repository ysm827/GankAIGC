# Implementation checklist

## Phase 1: cleanup and move

- [x] Delete ignored local runtime cache: `zhuque_pkg/__pycache__`, `zhuque_pkg/users`.
- [x] Create `package/backend/app/tools/`.
- [x] Move `zhuque_pkg/capture_zhuque_creds.py` to `package/backend/app/tools/zhuque_capture_window.py`.
- [x] Remove remaining tracked `zhuque_pkg` source files.

## Phase 2: update code

- [x] Update `zhuque_service.zhuque_user_data_root()` default to `package/data/zhuque/users`.
- [x] Update comments mentioning `zhuque_pkg/users`.
- [x] Update `_zhuque_capture_script_path()` to prefer the internal backend tool.
- [x] Update legacy command text and missing-script message.
- [x] Update `_default_credentials_file()` fallback away from `zhuque_pkg`.

## Phase 3: update tests/docs/specs

- [x] Update tests that import or assert old capture script paths.
- [x] Update `.gitignore` from old `zhuque_pkg` runtime files to `package/data/zhuque/`.
- [x] Update README/package README/spec references.
- [x] Ensure `git grep zhuque_pkg` has no active code/doc references.

## Phase 4: validation

- [x] `git diff --check`
- [x] `package/venv/bin/python -m pytest package/backend/tests/test_zhuque_integration.py -q`
- [x] `package/venv/bin/python -m pytest package/backend/tests/test_release_workflow.py -q`
- [x] `git ls-files zhuque_pkg` is empty.

# Implementation Plan

## Ordered Checklist

1. Add API format constants/helpers and Anthropic native request/response support in `ai_service.py`.
2. Extend settings, schemas, SQLAlchemy models, and startup DB migration for API format storage.
3. Extend provider config service and optimization session creation/retry/init flows to carry api format.
4. Extend operations service and admin/user routes for model test/list with `api_format`.
5. Extend admin `ConfigManager.jsx` and user `ApiSettingsPage.jsx` UI.
6. Add/adjust backend static tests and protocol unit tests:
   - response extraction for Anthropic payloads
   - admin config save/load API format
   - provider config persistence/test uses Anthropic protocol
   - operations model list for Anthropic returns Claude IDs
   - frontend static checks for API format selectors/payloads
7. Run targeted pytest.
8. Run frontend build and sync `package/frontend/dist` to `package/static`.
9. Run `git diff --check`, stage static bundle, commit.

## Validation Commands

```bash
package/venv/bin/python -m pytest \
  package/backend/tests/test_ai_service_response.py \
  package/backend/tests/test_auth_api.py::test_admin_config_updates_model_api_format \
  package/backend/tests/test_provider_config_api.py \
  package/backend/tests/test_operations_api.py \
  package/backend/tests/test_frontend_redeem_entry.py::test_config_manager_separates_sub_model_gateway_from_zhuque_detector \
  package/backend/tests/test_frontend_redeem_entry.py::test_config_manager_system_config_layout_matches_aurora_actions -q

cd package/frontend && npm run build
cd package/frontend && rm -rf ../static && cp -a dist ../static
git diff --check
```

If local PostgreSQL sandbox blocks tests with `connection is bad`, rerun the same pytest command with approved elevated execution.

## Risky Files / Rollback Points

- `package/backend/app/services/ai_service.py`: core model call path.
- `package/backend/app/services/operations_service.py`: admin/user connection test path.
- `package/backend/app/models/models.py` and `package/backend/app/database.py`: schema additions only; avoid destructive migration.
- `package/frontend/src/components/ConfigManager.jsx` and `package/frontend/src/pages/ApiSettingsPage.jsx`: must keep existing fields and static bundle sync.

Rollback is low-risk by setting all `api_format` values to `openai_chat` and reverting the commit.

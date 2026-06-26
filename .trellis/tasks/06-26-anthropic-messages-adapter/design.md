# Design: Anthropic Messages native adapter

## Architecture

Introduce a small provider-protocol layer in backend services rather than scattering `if api_format` branches through routes and optimization code.

### API format constants

Use stable internal values:

- `openai_chat` — existing OpenAI Compatible Chat Completions behavior.
- `anthropic` — Anthropic Messages native behavior, matching `cc-switch` terminology.

User-visible labels are mapped in frontend only:

- `OpenAI Compatible`
- `Anthropic Messages（原生）`

### Storage

System config:

- Add `MODEL_API_FORMAT` setting in `config.py`, default `openai_chat`.
- Add it to `/api/admin/config` response under `system.model_api_format`.
- Allow `/api/admin/config` updates to save this field into `.env`.

User BYOK config:

- Add `api_format` column to `user_provider_configs`, default `openai_chat`.
- Add startup migration in `database.py`.
- Add `api_format` to `ProviderConfigUpdateRequest`, `ProviderConfigResponse`, and runtime provider config.
- Existing rows without the column default to `openai_chat`.

Optimization sessions:

- Add per-stage api format columns so queued/retried sessions keep the format used at creation time:
  - `polish_api_format`
  - `enhance_api_format`
  - `emotion_api_format`
- Add startup migration in `database.py`.
- Runtime fallback: if old sessions have no format, resolve to system/BYOK runtime value or `openai_chat`.
- Compression uses system `MODEL_API_FORMAT` for now because compression is system-level.

## Backend Protocol Layer

Add helpers in `ai_service.py`:

- `normalize_api_format(value) -> "openai_chat" | "anthropic"`
- `ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"`
- `ANTHROPIC_MODEL_IDS = [...]`
- For Anthropic native:
  - Convert OpenAI-style messages to Anthropic Messages:
    - collect `system` messages into the top-level `system` string
    - map non-system roles to Anthropic `user`/`assistant`
    - ensure the first non-system message is `user`; this app usually sends `system` then `user`.
  - Non-stream call via `httpx.AsyncClient.post(<base>/v1/messages)`.
  - Stream call via `stream=true` and SSE parsing for `content_block_delta` / `text_delta` events.
  - Request body includes `model`, `max_tokens`, `messages`, optional `system`, optional `temperature` when not using reasoning mode.
  - Ignore `reasoning_effort` for Anthropic native in MVP; do not retry with OpenAI-specific params.

Keep `AIService.complete()` and `stream_complete()` public methods stable so optimization code does not need separate code paths.

## Operations Model Test/List

Add `api_format` argument to:

- `get_model_config`
- `get_model_probe_config`
- `test_model_connection`
- `list_provider_models`
- `test_provider_model_connection`

Behavior:

- `openai_chat`: current behavior unchanged.
- `anthropic`:
  - test sends `POST /v1/messages` with `max_tokens=8`, user `ping`.
  - list returns `ANTHROPIC_MODEL_IDS` and message `已载入 N 个 Claude 模型`.

## Frontend

Admin `ConfigManager.jsx`:

- Add `MODEL_API_FORMAT` to form state.
- Fetch from `response.data.system.model_api_format`.
- Include selector in model gateway card.
- Pass `api_format` to `model-test` and `model-list` payloads.
- For Anthropic selected, placeholder may remain generic but help text/option label makes protocol clear.

User `ApiSettingsPage.jsx`:

- Add `api_format` state and selector.
- Save/load `api_format`.
- Update helper text so users understand Anthropic native needs official endpoint/API key.

## Compatibility / Migration

- Default is `openai_chat`; existing `.env`, DB rows, sessions, and tests keep current behavior.
- Adding nullable/default string columns is non-destructive.
- Rollback: switch selector back to OpenAI Compatible or set `MODEL_API_FORMAT=openai_chat`.

## Security

- Reuse existing base URL validation.
- API key remains encrypted for BYOK and masked in responses.
- Audit logs continue to include base URL/model/count only; no plaintext key.
- Do not log request content unless existing verbose logging is enabled.

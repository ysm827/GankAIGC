# Add Anthropic Messages native adapter

## Goal

Allow GankAIGC to use Claude through Anthropic Messages native API in addition to the existing OpenAI Compatible `/v1/chat/completions` flow, so admins and BYOK users can select an API format instead of being forced to route Claude through an OpenAI-compatible proxy.

## Confirmed Facts

- Current backend model calls are OpenAI-compatible only:
  - `AIService` uses `AsyncOpenAI(...).chat.completions.create(...)`.
  - Admin model test/list uses `AsyncOpenAI` and `GET <base_url>/models`.
  - System config only stores model/base URL/API key fields; no API format field exists.
- User BYOK config also only stores base URL/API key/model fields.
- `cc-switch` models API format as a provider metadata field with values including `anthropic`, `openai_chat`, `openai_responses`, and `gemini_native`; the relevant product idea is selecting a protocol format, not hardcoding provider names.
- Anthropic Messages native API uses different request/response semantics from OpenAI Chat:
  - `POST /v1/messages`
  - auth header `x-api-key` / `X-Api-Key`
  - `anthropic-version: 2023-06-01`
  - required `model`, `max_tokens`, `messages`
  - response text comes from `content[].text`
  - streaming yields text deltas rather than OpenAI `choices[].delta.content`.

## Requirements

- Add API format support with two user-visible options:
  - `OpenAI Compatible`
  - `Anthropic Messages（原生）`
- Preserve existing OpenAI-compatible behavior as the default for current deployments.
- Admin system model gateway configuration must persist API format to `.env` and return it from `/api/admin/config`.
- User BYOK provider configuration must persist API format and expose it in masked config response.
- All optimization stages must route through the selected format:
  - polish
  - enhance
  - emotion polish
  - compression for system config
- Admin connection test and user provider test must call the correct protocol for the selected API format.
- Model discovery behavior:
  - OpenAI Compatible keeps current `/models` discovery.
  - Anthropic native may return a curated Claude model list locally because Anthropic native model enumeration is not equivalent to OpenAI `/models` in this app.
- Base URL validation remains enforced; local proxy allowance continues to use the existing security switch.
- Do not leak full API keys in responses, logs, audit details, or frontend state.
- Existing configs without an API format must behave exactly as `OpenAI Compatible`.

## Acceptance Criteria

- [ ] Admin UI shows an `API 格式` selector above/near model gateway fields.
- [ ] User BYOK API settings page shows the same `API 格式` selector.
- [ ] Saving admin config writes `MODEL_API_FORMAT` and reloads settings.
- [ ] Saving user BYOK config stores and returns `api_format` without returning plaintext API key.
- [ ] OpenAI-compatible test/list behavior remains unchanged when `api_format=openai_chat`.
- [ ] Anthropic-native test sends a Messages request to `/v1/messages` using `x-api-key` and `anthropic-version` headers.
- [ ] Anthropic-native optimization calls return generated text from `content[].text`.
- [ ] Anthropic-native streaming yields text deltas and still strips `<think>` tags.
- [ ] Anthropic-native model discovery returns real Claude model IDs curated in code, not fake OpenAI models.
- [ ] Existing tests for provider config, admin config, operations model tests, AI response extraction, and frontend static contracts pass.
- [ ] Frontend production bundle is rebuilt and synced to `package/static`.

## Out of Scope

- OpenAI Responses native adapter.
- Gemini native `generateContent` adapter.
- Tool calling, vision, file upload, prompt caching, and Anthropic beta feature headers.
- Per-stage mixed API formats inside one saved provider; MVP uses one selected format for a gateway config.

## Notes

- Recommended default scope: implement both admin system model config and BYOK user config, otherwise Claude native would work in one mode but fail in another.

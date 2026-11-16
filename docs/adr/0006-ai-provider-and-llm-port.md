# ADR-0006: AI provider, `LlmClient` port and usage limits

- Status: Accepted
- Date: 2026-11-15
- Story: CN-01

## Context

The AI assistant suggests candidate receivables for one unmatched credit and explains why ([SPEC.md](../SPEC.md), "Asistente de IA"). It never decides: the server validates the output, recalculates every amount, and a person accepts or rejects. The feature must cost almost nothing, must not let the provider train on customer data, must have a hard spending stop, and must be fully optional (`AI_ENABLED=false`). Demo organizations never call a real provider.

Three providers were compared on 2026-11-15 from their official pages, assuming about 1 500 input and 500 output tokens per call:

| Provider and model | USD per 1M tokens (input / output) | Cost per call | Trains on API data by default | Hard spend stop |
| --- | --- | --- | --- | --- |
| OpenAI `gpt-6-luna` | 0.10 / 0.50 | ~0.0004 | No | Project or organization hard limit (applied with a short delay) and prepaid balance |
| Anthropic `claude-haiku-5-5` | 0.10 / 0.50 | ~0.0004 | No | Monthly spend limit and prepaid balance |
| Google `gemini-3.1-flash-lite` | 0.25 / 1.50 | ~0.0011 | No on paid tier, yes on free tier | Project cap marked experimental; prepaid balance |

## Decision

**Provider: OpenAI, model `gpt-6-luna`, through the official `openai` Python SDK.** OpenAI and Anthropic are equivalent on price, structured output and data use; OpenAI is chosen because the owner already has an account and API key, so no new billing relationship is needed. The model id is a setting (`AI_MODEL`, default `gpt-6-luna`) and is stored with every suggestion.

**Account setup (owner actions, outside the repository):**

- a dedicated OpenAI project named `concilia` with its own API key, so its budget and key revocation affect nothing else;
- a project budget of US$5 per month as a hard limit, plus prepaid credit without automatic recharge as a second stop;
- the organization's data-sharing controls checked to be off, so inputs and outputs are never offered for training;
- the key stored only in the server's environment (`OPENAI_API_KEY`) and in the local environment of whoever runs `make record-ai`, never in the repository or in CI logs.

**Request settings.**

- Only the fields listed in SPEC are sent: the credit's date, amount and description, and for each candidate its alias, document number, customer name, available balance, issue date and due date.
- Structured output with a strict JSON Schema generated from the Pydantic response model. Strict mode requires every field to be present and forbids objects with free-form keys, so optional fields are nullable and `applied` is a list of `{alias, cents}` pairs (SPEC updated accordingly).
- `store=false`, so the provider keeps no application state; only its abuse-monitoring logs (up to 30 days) remain.
- Reasoning effort at the lowest level that keeps suggestion quality, starting at `low`, so output stays near the estimate. Actual usage is measured from `input_tokens` and `output_tokens`, stored in every `ai_suggestions` row.
- SDK retries disabled and a 30-second timeout: the job queue owns retries ([ADR-0005](0005-job-queue-in-postgresql.md)), so failures are not retried twice.

**The provider is never trusted.** The response is parsed and validated with the same Pydantic model in the `ai` application layer, whatever the provider guarantees. Invalid output is stored with `valid = false` and never shown. Aliases not sent are dropped, applied amounts over the available balance are dropped, and the server recalculates every amount and difference (`server_applied`).

**Port and adapters.**

- `ai.application.LlmClient` is a `typing.Protocol` with one async method. It takes the rendered prompt and the response schema, and returns the raw output, the model id and the token counts.
- `OpenAiLlmClient` (infrastructure) implements it with the SDK.
- `FakeLlmClient` (infrastructure) is deterministic. Tests feed it inline fixtures, including invalid output and invented aliases. Demo organizations feed it the recorded responses for the current `dataset_version`, translated by document number as SPEC describes.

**Which client is used.**

| Situation | Client |
| --- | --- |
| `AI_ENABLED=false` | None: the feature is hidden and its endpoints return 404, in every organization |
| Demo organization | `FakeLlmClient` with recordings, always |
| Other organization, `OPENAI_API_KEY` set | `OpenAiLlmClient` |
| Other organization, no key | None: the feature is shown as unavailable for that organization |

`make record-ai` uses `OpenAiLlmClient` against a regular (non-demo) organization loaded with the demo dataset, as SPEC describes.

**Prompts are versioned files.** Each prompt lives in `backend/src/concilia/ai/prompts/` and has a `prompt_version`. A test pins the SHA-256 of each prompt file to its version, so editing a prompt without bumping its version fails CI. That bump in turn fails the recordings test until `make record-ai` is run again.

**Usage limits.** On top of the provider budget, the application limits AI jobs counted at enqueue time: 50 per organization per Lima day (SPEC) and `AI_GLOBAL_DAILY_LIMIT` across the instance, 200 by default in production. At ~US$0.0004 per call, a month at the global limit costs about US$2.40, below the US$5 budget. Demo organizations do not count and never reach the provider.

**Errors and logs.** Provider failures map to job error codes (`ai_timeout`, `ai_rate_limited`, `ai_budget_exhausted`, `ai_provider_error`). Prompts, responses and customer data never reach logs or error messages; they live only in `ai_suggestions`, inside the organization.

## Consequences

- Monthly AI cost is bounded three times: by the provider budget, by the prepaid balance, and by the application's daily limits.
- Switching provider means writing one adapter and changing settings. The rest of the feature, the stored suggestions and the demo recordings stay as they are.
- OpenAI's hard limit takes effect with a short delay, so spending can slightly exceed US$5 in a burst. The application's daily limits make such a burst impossible in practice.
- The model may be retired; the setting and the stored model id make a change visible and reversible.
- Optional contract tests against the real provider run only by hand with a GitHub secret, never in the default CI.

## Alternatives considered

- **Anthropic `claude-haiku-5-5`.** Same price and data terms, with a spend limit that stops requests immediately. Not chosen only because the owner already has an OpenAI account; it remains the first fallback.
- **Google `gemini-3.1-flash-lite`.** Rejected: 2.5 to 3 times the price, a spend cap marked experimental, free-tier terms that allow training on data, and a model scheduled for retirement on 2027-05-07.
- **A self-hosted open model.** Rejected: it would not fit the server or the budget.

## References

- Pricing: https://developers.openai.com/api/docs/pricing.md
- Model: https://developers.openai.com/api/docs/models/gpt-6-luna
- Structured outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- Data controls and retention: https://developers.openai.com/api/docs/guides/your-data
- Spend limits: https://developers.openai.com/api/docs/guides/spend-limits
- Python SDK: https://pypi.org/project/openai/

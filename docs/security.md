# Security and privacy model

## Data classes

| Class | Examples | Default handling |
|---|---|---|
| Public | public article URL, public topic | may enter a workflow |
| Derived | Story Plan, shot prompts, SRT | store only as job artifacts |
| Sensitive | article body, generated narration, media | local storage only by explicit job |
| Secret | API keys, cookies, Authorization headers | reject from job input |

## Rules

- API input has a strict schema and unknown fields are rejected.
- Provider/model/API key fields are server-owned and never accepted from the job request.
- Error responses are coarse; raw upstream response bodies are not persisted.
- Idempotency keys are stored only as SHA-256 fingerprints, never as raw keys.
- Worker failure messages are truncated and redact common credential fields.
- Filesystem queue state uses atomic rename/replace operations; Redis uses an atomic reliable-list handoff. Both use leases for crash recovery.
- The worker writes only generated artifacts and job metadata.
- The default local demo uses a silent WAV and deterministic FFmpeg; no external network call is required.
- The public repository contains no real credential, private media, or production endpoint.

Before enabling a hosted provider, add server-side authentication, rate limits,
cost budgets, concurrency limits and an explicit retention policy. Redis mode
shares queue metadata across processes but does not protect local artifacts or
catalog files; use a shared volume or object-storage adapter for that boundary.
Never expose Redis, the dashboard or the MCP stdio bridge directly to the
public internet.

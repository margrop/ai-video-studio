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
- When `AIVS_API_KEY` is set, every `/v1` route requires a constant-time checked Bearer token or `X-AIVS-API-Key`; `/health` remains public for probes.
- `/v1` requests use the service-owned fixed-window rate limit. Redis-backed deployments share counters across API replicas; filesystem mode limits per process.
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

## HTTP boundary configuration

For a private local installation, leave `AIVS_API_KEY` empty. Before putting a
reverse proxy or public network in front of the service, set a long random
secret and keep it only in the server/Compose secret environment:

```dotenv
AIVS_API_KEY=replace-with-a-long-random-secret
AIVS_RATE_LIMIT_PER_MINUTE=120
AIVS_RATE_LIMIT_WINDOW_SECONDS=60
```

The dashboard shell remains a static page, while its `/v1` data and artifact
requests are protected. A browser client must attach the key as an
`Authorization: Bearer ...` header or `X-AIVS-API-Key`; query-string keys are
not accepted. Rate-limit counters do not log or persist the API key itself.

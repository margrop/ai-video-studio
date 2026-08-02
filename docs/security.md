# Security and privacy model

## Data classes

| Class | Examples | Default handling |
|---|---|---|
| Public | public article URL, public topic | may enter a workflow |
| Derived | Story Plan, shot prompts, SRT | store only as job artifacts |
| Sensitive | article body, generated narration, media | service-owned filesystem or object store |
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
- The worker writes only generated artifacts and job metadata. In S3 mode it
  uploads staged artifacts to the configured bucket after render completion;
  object-store credentials remain server-side.
- The default local demo uses a silent WAV and deterministic FFmpeg; no external network call is required.
- The public repository contains no real credential, private media, or production endpoint.

Before enabling a hosted provider, add server-side authentication, rate limits,
cost budgets, concurrency limits and an explicit retention policy. Redis and
PostgreSQL modes share queue metadata across processes. S3 mode protects generated artifact
delivery through the API boundary, while catalog and approval files still need
a shared volume until their database adapter lands.
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

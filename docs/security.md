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
- The worker writes only generated artifacts and job metadata.
- The default local demo uses a silent WAV and deterministic FFmpeg; no external network call is required.
- The public repository contains no real credential, private media, or production endpoint.

Before enabling a hosted provider, add server-side rate limits, cost budgets, concurrency limits and an explicit retention policy. Phase 1's file queue is for localhost or trusted development networks, not an internet-facing deployment.

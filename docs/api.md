# API v1

## Create a job

`POST /v1/jobs`

```json
{
  "topic": "介绍 MCP",
  "source_markdown": "",
  "duration_seconds": 60,
  "language": "zh-CN",
  "voice": "neutral",
  "use_ai": false
}
```

The client cannot provide provider, model, prompt, key, retry, budget or output path controls.

For safe client retries, send an `Idempotency-Key` header. The key is hashed
for the local index and the raw value is never stored:

```http
Idempotency-Key: article-mcp-2026-08-01
```

Submitting the same key returns the original job record instead of enqueueing a
second job.

## Inspect a job

`GET /v1/jobs/{job_id}` returns `queued`, `running`, `succeeded` or `failed`. A failed job exposes only a stable error code and a short safe diagnostic.

The worker uses a service-owned retry budget. A failed attempt becomes
`queued` with a bounded exponential backoff until the budget is exhausted;
worker leases are recovered after a process crash.

## Operations

- `GET /v1/jobs?status=queued&limit=50` lists recent jobs;
- `GET /v1/jobs/{job_id}/events` returns safe state-transition events;
- `GET /v1/stats` returns queue depth and status counts;
- `GET /v1/providers` returns configured capability metadata without secrets.

## Download artifacts

- `GET /v1/jobs/{job_id}/artifacts/video.mp4`
- `GET /v1/jobs/{job_id}/artifacts/story-plan.json`
- `GET /v1/jobs/{job_id}/artifacts/subtitles.srt`
- `GET /v1/jobs/{job_id}/artifacts/narration.wav`

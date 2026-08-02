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

## Inspect a job

`GET /v1/jobs/{job_id}` returns `queued`, `running`, `succeeded` or `failed`. A failed job exposes only a stable error code and a short safe diagnostic.

## Download artifacts

- `GET /v1/jobs/{job_id}/artifacts/video.mp4`
- `GET /v1/jobs/{job_id}/artifacts/story-plan.json`
- `GET /v1/jobs/{job_id}/artifacts/subtitles.srt`
- `GET /v1/jobs/{job_id}/artifacts/narration.wav`

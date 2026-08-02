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

`GET /v1/jobs/{job_id}` returns `queued`, `running`, `succeeded` or `failed`.
It also includes a server-owned `progress` object:

```json
{
  "stage": "video",
  "percent": 58,
  "completed_shots": 4,
  "total_shots": 8,
  "current_shot": 5,
  "message": "已完成 Shot 4/8"
}
```

The progress stage is informational and cannot be set by the client. A failed job exposes only a stable error code and a short safe diagnostic.

The worker uses a service-owned retry budget. A failed attempt becomes
`queued` with a bounded exponential backoff until the budget is exhausted;
worker leases are recovered after a process crash.

## Operations

- `GET /v1/jobs?status=queued&limit=50` lists recent jobs;
- `GET /v1/jobs/{job_id}/events` returns safe state-transition and shot-progress events;
- `GET /v1/stats` returns queue depth and status counts;
- `GET /v1/usage` returns idempotent terminal usage totals and provider counts;
- `GET /v1/providers` returns configured capability metadata without secrets.
- `GET /v1/publishers` returns explicitly registered publishing adapters.
- `GET /v1/templates` lists server-owned workflow templates;
- `GET /v1/brand-presets` lists versioned server-owned visual identity presets;
- `GET/POST /v1/assets` manages reusable asset metadata;
- `PUT/GET /v1/assets/{asset_id}/content` uploads or downloads asset bytes through the server-owned key;
- `GET/POST /v1/characters` manages reusable character profiles and reference IDs.
- `GET /v1/jobs/{job_id}/social-drafts` returns the validated draft bundle;
- `GET/POST /v1/jobs/{job_id}/approvals` reads or appends a human approval decision for one platform.
- `GET /v1/jobs/{job_id}/publish-audit` returns safe publish audit events;
- `POST /v1/jobs/{job_id}/publish` previews by default and requires the latest human approval for an external attempt.

`POST /v1/jobs` accepts `template_id`, an optional `brand_preset_id` and an
optional `character_id`. All three are resolved against server-owned catalogs;
a client cannot submit an arbitrary Prompt Builder configuration or filesystem
path. Omitting `brand_preset_id` uses the selected template's default.

Brand Presets expose a version, deterministic prompt layers and optional
`logo_asset_id`, `intro_asset_id` and `outro_asset_id` references. The current
render boundary records these reusable references and applies the prompt
layers; platform-specific media overlays remain a renderer extension.

When `AIVS_VIDEO_PROVIDER`, `AIVS_VIDEO_BASE_URL`, `AIVS_VIDEO_API_KEY` and
`AIVS_VIDEO_MODEL` are configured, the worker can use the generic asynchronous
video adapter. Otherwise it uses the deterministic FFmpeg renderer. The
download host must be explicitly allowed by `AIVS_VIDEO_ALLOWED_DOWNLOAD_HOSTS`.

## Download artifacts

- `GET /v1/jobs/{job_id}/artifacts/video.mp4`
- `GET /v1/jobs/{job_id}/artifacts/story-plan.json`
- `GET /v1/jobs/{job_id}/artifacts/subtitles.srt`
- `GET /v1/jobs/{job_id}/artifacts/narration.wav`
- `GET /v1/jobs/{job_id}/artifacts/social-drafts.json`
- `GET /v1/jobs/{job_id}/artifacts/shot-manifest.json`

For a Provider-backed job, `shot-manifest.json` is a `shot-manifest-v1`
document. A succeeded Shot is reused on a retry only when its plan
fingerprint, Provider ID, prompt hash, duration and local clip are all still
consistent. Failed or interrupted Shots are retried individually while the
manifest remains an operator-visible record.

Approval decisions and publish attempts are append-only and auditable. The
publish endpoint defaults to dry-run, and a non-dry-run request is blocked
unless the latest platform decision is `approved`. With no server-side adapter
registered—or while `AIVS_EXTERNAL_PUBLISH_ENABLED` is false—the structured
result is `unavailable`; no credentials or external request are fabricated.

## Web dashboard

打开 `GET /dashboard` 可使用内置控制台。它只调用同一 FastAPI 服务的
`/v1` 接口，不引入 Node 构建链；部署到生产环境前仍需在反向代理或应用
层增加认证与 CSRF/访问控制。配置 `AIVS_API_KEY` 后，Dashboard 右上角可在
当前浏览器会话中输入 API Key，Key 只保存在 `sessionStorage`。

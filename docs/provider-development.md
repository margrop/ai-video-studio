# Provider development

## Adding a provider

1. Implement the narrow interface in `packages/llm`, `packages/tts` or `packages/providers`.
2. Put vendor-specific authentication, request mapping, polling, response validation and error mapping under `providers/<vendor>/`.
3. Register the adapter in `packages/runtime.py`; public job input must not select it.
4. Add synthetic tests for success, timeout, rate limit, invalid response and secret-like output.
5. Document quota, cost, model availability and any required reference asset.

An independently distributed adapter can expose an entry point without
changing the core workflow:

```toml
[project.entry-points."aivs.video_providers"]
my-provider = "my_package:Provider"
```

The provider class should expose `provider_id`, optional `provider_kind` and
`capabilities`, then implement `VideoProvider.generate`. A provider-backed
workflow calls this method once per validated Story Plan shot, with a 4–15
second duration and the server-owned character reference images. Set
`AIVS_VIDEO_PROVIDER` to that server-owned ID to activate it. The repository
contains a verified native MiniMax H3 adapter under `providers/minimax`, plus
transport-compatible scaffolds for `kling`, `google-veo`, `runway` and
`openai-video`. The remaining scaffolds use vendor-prefixed `*_VIDEO_*`
environment variables but do not claim that their vendor API shapes have been
verified. Enable one only after its endpoint, credential, quota and response
contract has been tested.

## Volcengine Ark Agent Plan

`VolcengineAgentPlanVideoProvider` is the verified native adapter under
`providers/volcengine`. It uses the dedicated Agent Plan base URL
`https://ark.cn-beijing.volces.com/api/plan/v3`, submits
`POST /contents/generations/tasks`, polls
`GET /contents/generations/tasks/{id}`, reads `content.video_url`, validates
the signed Ark/TOS download host and downloads the MP4 without sending the API
key to the CDN.

Agent Plan requires a dedicated Agent Plan API key and a Base URL containing
`/api/plan/v3`; a normal Ark or Coding Plan key is not interchangeable. The
adapter maps the provider-owned prompt and server-owned reference image URLs
to Seedance `content[]`, and exposes resolution, ratio, duration, audio and
watermark as server configuration. It defaults to `doubao-seedance-2.0`,
`720p`, `9:16`, silent clips and no watermark so AIVS can attach its own
narration during composition.

## MiniMax H3 text and video boundaries

`MiniMaxLLMProvider` is the OpenAI-compatible text planner boundary. It uses
the text model selected by `AIVS_LLM_MODEL`, normally through a local NewAPI
or another OpenAI-compatible gateway. H3 is not used as the planner model.

`MiniMaxH3VideoProvider` is the native video boundary. It maps a validated Shot
to MiniMax H3's `content[]` request, submits `/v2/video_generation`, polls
`/v2/query/video_generation/{task_id}`, validates the returned CDN URL and
downloads the MP4. It supports 4–15 second text-to-video and reference-image
Shots. Reference images must be available through public or signed URLs; the
provider does not upload local files to an external service implicitly.

## Video providers

The `VideoProvider` interface is deliberately separate from the Phase 1 FFmpeg renderer. A hosted video provider may be asynchronous and may return a download URL, but that polling and download logic belongs inside its adapter.

`packages/providers/http_video.py` includes a generic submit → poll → download
transport for providers with compatible semantics. It is opt-in through
server-owned `AIVS_VIDEO_*` settings and enforces a download-host allow-list;
it is not a vendor-specific implementation. Kling, Veo, Runway and OpenAI
adapters should subclass or replace this transport when their API contracts
differ, then add success, timeout, failed-job and unsafe-URL tests. The core
workflow concatenates shot clips before attaching the single narration track,
so an adapter must not silently turn a one-minute request into one 60-second
model invocation.

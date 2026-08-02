# Provider development

## Adding a provider

1. Implement the narrow interface in `packages/llm`, `packages/tts` or `packages/providers`.
2. Put vendor-specific authentication, request mapping, polling, response validation and error mapping under `providers/<vendor>/`.
3. Register the adapter in `packages/runtime.py`; public job input must not select it.
4. Add synthetic tests for success, timeout, rate limit, invalid response and secret-like output.
5. Document quota, cost, model availability and any required reference asset.

## MiniMax H3

`providers/minimax/MiniMaxH3Provider` treats H3 as a server-side OpenAI-compatible planner model. It returns structured JSON which is validated by `StoryPlan`. The base URL is configurable so a local OpenAI Gateway can sit between AIVS and MiniMax.

## Video providers

The `VideoProvider` interface is deliberately separate from the Phase 1 FFmpeg renderer. A hosted video provider may be asynchronous and may return a download URL, but that polling and download logic belongs inside its adapter.

`packages/providers/http_video.py` includes a generic submit → poll → download
transport for providers with compatible semantics. It is opt-in through
server-owned `AIVS_VIDEO_*` settings and enforces a download-host allow-list;
it is not a vendor-specific implementation. Kling, Veo, Runway and OpenAI
adapters should subclass or replace this transport when their API contracts
differ, then add success, timeout, failed-job and unsafe-URL tests.

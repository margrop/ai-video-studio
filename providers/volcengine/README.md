# Volcengine Ark Agent Plan video provider

`VolcengineAgentPlanVideoProvider` is the native AIVS adapter for Ark Agent
Plan's asynchronous Seedance content-generation API. It is separate from the
NewAPI/OpenAI-compatible text planner and follows the same provider boundary as
MiniMax H3.

The adapter calls:

```text
POST /contents/generations/tasks
GET  /contents/generations/tasks/{id}
```

with the Agent Plan base URL:

```text
https://ark.cn-beijing.volces.com/api/plan/v3
```

The provider validates the task status, extracts `content.video_url`, checks
the signed Ark/TOS host allow-list and downloads the MP4 without forwarding the
API key.

## Configuration

```env
AIVS_VIDEO_PROVIDER=volcengine-agentplan-video
AIVS_VOLCENGINE_VIDEO_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
AIVS_VOLCENGINE_VIDEO_API_KEY=replace-with-agent-plan-api-key
AIVS_VOLCENGINE_VIDEO_MODEL=doubao-seedance-2.0
AIVS_VOLCENGINE_VIDEO_RESOLUTION=720p
AIVS_VOLCENGINE_VIDEO_RATIO=9:16
AIVS_VOLCENGINE_VIDEO_GENERATE_AUDIO=false
AIVS_VOLCENGINE_VIDEO_WATERMARK=false
AIVS_VOLCENGINE_VIDEO_POLL_INTERVAL_SECONDS=10
AIVS_VOLCENGINE_VIDEO_MAX_WAIT_SECONDS=900
```

The API key must be the dedicated Agent Plan key. The official API contract
requires the `/api/plan/v3` Base URL; a regular Ark or Coding Plan key/base URL
is not interchangeable.

Seedance 2.0 supports 4–15 second clips, so AIVS submits one task for each
validated Story Plan Shot and concatenates the clips locally. Since AIVS adds
its own narration during composition, generated video audio is disabled by
default. Set `AIVS_VOLCENGINE_VIDEO_GENERATE_AUDIO=true` only when the provider
audio should be retained in the source clips.

Reference images must be public or signed URLs, Ark `asset://` IDs, or image
data URLs. Local files are never uploaded implicitly. For Seedance 2.0
multi-image references, set `AIVS_VOLCENGINE_VIDEO_REFERENCE_ROLE=reference_image`;
`first_frame` and `last_frame` are also supported.

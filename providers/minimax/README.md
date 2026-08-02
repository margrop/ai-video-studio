# MiniMax H3 video provider

`MiniMaxH3VideoProvider` is the native adapter for MiniMax H3's asynchronous
video API. It is separate from the OpenAI-compatible text model used by Story
Planner and can coexist with a self-hosted NewAPI gateway.

The adapter calls:

```text
POST /v2/video_generation
GET  /v2/query/video_generation/{task_id}
```

It sends `content[]`, polls until a terminal status, validates the provider
CDN host and downloads the returned MP4 without forwarding the API key to the
CDN.

## Configuration

```env
AIVS_VIDEO_PROVIDER=minimax-video
AIVS_MINIMAX_VIDEO_BASE_URL=https://api.minimax.io
AIVS_MINIMAX_VIDEO_API_KEY=replace-with-a-Minimax-Developer-API-Key
AIVS_MINIMAX_VIDEO_MODEL=MiniMax-H3
AIVS_MINIMAX_VIDEO_RESOLUTION=768P
AIVS_MINIMAX_VIDEO_RATIO=9:16
AIVS_MINIMAX_VIDEO_POLL_INTERVAL_SECONDS=10
AIVS_MINIMAX_VIDEO_MAX_WAIT_SECONDS=900
AIVS_MINIMAX_VIDEO_ALLOWED_DOWNLOAD_HOSTS=filecdn.minimax.chat
```

For users in China, use the China API base URL shown in the MiniMax Developer
Platform. The credential must be a server-side Developer API key with H3 video
permission; a consumer Token Plan entitlement is not automatically an API
key.

H3 accepts 4–15 second integer clips. AIVS therefore calls the provider once
per Story Plan Shot and concatenates the clips locally. Reference images need
public URLs. Configure an operator-owned template such as:

```env
AIVS_ASSET_PUBLIC_URL_TEMPLATE=https://cdn.example.com/aivs/assets/{asset_id}
```

The URL must be reachable by MiniMax without the AIVS API key. Leave it empty
for text-to-video-only jobs.

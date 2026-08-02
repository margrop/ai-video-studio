# Changelog

## 0.18.2 — 2026-08-02

- update macOS setup to use Homebrew's keg-only `ffmpeg-full` formula;
- document FFmpeg 8's libfreetype and libharfbuzz requirements for `drawtext`;
- replace the ineffective `brew reinstall ffmpeg` remediation message.

## 0.18.1 — 2026-08-02

- detect missing FFmpeg `drawtext` support before offline slideshow rendering;
- expose an actionable macOS/libfreetype remediation message;
- support `AIVS_FFMPEG_BINARY` for selecting a complete FFmpeg installation;
- add regression tests for FFmpeg capability diagnostics.

## 0.18.0 — 2026-08-02

- add the native MiniMax H3 asynchronous video Provider;
- map H3 `content[]` requests, task polling, terminal failures and signed CDN
  downloads;
- support optional public reference-image URLs for Character/Asset inputs;
- separate the NewAPI-backed text Planner from the MiniMax H3 video model;
- add synthetic H3 provider tests without real credentials.

## 0.17.0 — 2026-08-02

- add allowlisted remote Article → Video source URLs;
- extract readable HTML/text content with a 2 MB limit and no embedded credentials;
- keep Markdown precedence and require `AIVS_SOURCE_ALLOWED_HOSTS` before any
  remote fetch to avoid turning the service into an open SSRF proxy;
- expose `source_url` through API jobs, CLI, MCP and Dashboard.

## 0.16.0 — 2026-08-02

- add versioned `shot-manifest-v1` state for provider-generated clips;
- reuse successful clips after a worker retry when the plan, Provider and
  prompt fingerprints still match;
- persist pending/running/succeeded/failed Shot state before and after each
  provider call;
- expose the manifest as a protected downloadable job artifact.

## 0.15.0 — 2026-08-02

- add explicit template versions and server-owned Brand Preset catalog;
- merge selected brand prompts into the deterministic Prompt Builder layer;
- expose reusable brand identity and intro/outro asset references through API,
  CLI, MCP and Dashboard job creation;
- keep template and brand selection server-validated rather than accepting raw
  prompt overrides from jobs.

## 0.14.0 — 2026-08-02

- add provider-neutral `JobProgress` metadata for planning, narration, shot
  generation, composition and social-draft stages;
- persist progress consistently in filesystem, Redis and PostgreSQL job stores;
- emit structured progress events for each completed video shot;
- show live percentage and shot progress in the Dashboard.

## 0.13.0 — 2026-08-02

- add capability-aware server-side ProviderRegistry selection;
- add transport-compatible MiniMax video, Kling, Google Veo, Runway and OpenAI video scaffolds;
- support vendor-prefixed HTTP adapter configuration without exposing provider controls to jobs;
- document the boundary between a reusable transport scaffold and a verified vendor adapter.

## 0.12.0 — 2026-08-02

- add server-owned Asset Library content upload/download endpoints;
- enforce configurable asset byte limits, atomic writes and SHA-256 metadata updates;
- allow uploaded reference assets to be resolved by shot-based provider workflows.

## 0.11.0 — 2026-08-02

- enforce 4–15 second contiguous Story Plan shots;
- generate provider video one shot at a time and concatenate clips before narration muxing;
- pass server-owned Character reference images through the shot boundary;
- add shot-generation capability metadata and workflow tests.

## 0.10.0 — 2026-08-02

- add PostgreSQL-backed Asset/Character catalogs and approval metadata;
- add append-only publish audit storage and a provider-neutral Publisher registry;
- add dry-run-by-default publishing with human approval gates, safe outcomes and API/MCP controls;
- add Dashboard preview/publish controls that never bypass the approval boundary.

## 0.9.0 — 2026-08-02

- add an optional PostgreSQL JobStore with row-level `SKIP LOCKED` claims;
- persist job metadata, idempotency, leases, events, retries and terminal usage records in PostgreSQL;
- add PostgreSQL Compose service, environment configuration, schema bootstrap and offline protocol tests.

## 0.8.0 — 2026-08-02

- add a provider-neutral artifact store contract with filesystem and S3-compatible backends;
- stage generated files locally, publish them to S3/MinIO after a successful render, and stream protected API downloads from object storage;
- add Docker, Compose, environment and deployment guidance for object-storage artifacts while keeping catalogs and approvals on the service volume.

## 0.7.0 — 2026-08-02

- add a manual GitHub Actions Article-to-Video workflow;
- validate repository-relative Markdown sources and upload the complete content package as a workflow artifact;
- keep offline deterministic planning as the default and isolate optional planner secrets in GitHub Actions secrets.

## 0.6.0 — 2026-08-02

- add append-only human approval records for social drafts;
- expose draft review and approval API endpoints without adding external posting side effects;
- add Dashboard approval controls and session-only API-key entry for protected `/v1` deployments.

## 0.5.0 — 2026-08-02

- add optional constant-time API-key authentication for `/v1` routes;
- add process-local and Redis-shared fixed-window rate limiting with standard response headers;
- keep health checks and anonymous local development available when no API key is configured.

## 0.4.0 — 2026-08-02

- add a pluggable job-store contract and Redis backend for multi-process workers;
- preserve atomic idempotency, reliable processing handoff, lease recovery, delayed retries, events and usage records in Redis;
- add Redis-aware Docker Compose configuration and storage/deployment documentation;
- keep filesystem storage as the zero-dependency offline default.

## 0.3.0 — 2026-08-02

- add recoverable filesystem jobs with idempotency, retries, leases and events;
- add FastAPI dashboard, Provider capability and usage APIs;
- add Character, Asset and Template catalogs with Prompt Builder integration;
- add optional async video transport with safe download-host enforcement;
- add social draft generation, optional MCP tools, Docker Compose and CI;
- add RSS/Atom → video → social-draft CLI workflow;
- preserve deterministic offline rendering and explicit human approval before publishing.

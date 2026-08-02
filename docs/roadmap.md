# Roadmap

## Phase 1 — completed

- FastAPI job API
- filesystem worker
- one-sentence CLI
- MiniMax H3 OpenAI-compatible planner adapter
- TTS interface with offline fallback
- deterministic SRT and FFmpeg vertical MP4
- versioned Story Plan contract

## Phase 2 — foundation completed

- durable local queue with atomic claims and worker leases
- bounded retry policy with crash recovery
- idempotency-key index and job event stream
- job list, stats and provider capability API
- Web dashboard, usage/cost records and compose stack are included
- Redis backend with reliable handoff, leases, retries and usage records
- optional API-key authentication and process/Redis-shared rate limiting
- append-only social draft approval records and Dashboard review controls
- manual Article → Video GitHub Actions workflow with artifact packaging
- S3/MinIO-compatible generated artifact storage with authenticated API streaming
- PostgreSQL job metadata, leases, events, idempotency and usage storage
- PostgreSQL asset/character metadata, approval history and publish audit storage

## Phase 3 — foundation completed

- Character Library, Asset Library and template catalog foundation
- reference asset IDs and character Prompt Builder integration
- generic async video provider transport with safe polling/download boundary
- RSS/Atom → video → social-draft workflow
- generic provider registry, safe async video transport and shot-by-shot composition
- transport-compatible MiniMax/Kling/Veo/Runway/OpenAI video scaffolds are
  included; verified vendor-specific request adapters, template versioning and
  brand presets remain extension work
- provider capability discovery and usage/cost records are included
- server-owned stage and per-shot progress metadata is persisted consistently
  by file, Redis and PostgreSQL queues

## Phase 4 — foundation completed

- MCP Server
- Claude Code, Codex and Kimi Code tools
- Article-to-video GitHub Action
- blog/WeChat/Bilibili/Xiaohongshu publishing boundary with dry-run and audit
- human review and approval gates before any registered external publisher
- real platform adapters remain opt-in integrations with their own credentials,
  rate limits and platform-specific tests

The remaining work is integration-specific extension work: verified vendor
request/response adapters, template and brand-preset versioning, and separately
tested social-platform publishers.

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
- Postgres catalog/job metadata and object-storage artifacts remain follow-up

## Phase 3 — foundation completed

- Character Library, Asset Library and template catalog foundation
- reference asset IDs and character Prompt Builder integration
- generic async video provider transport with safe polling/download boundary
- RSS/Atom → video → social-draft workflow
- vendor-specific image/video adapters
- asset upload lifecycle, template versioning and brand presets remain follow-up
- provider capability discovery and usage/cost records are included

## Phase 4 — in progress

- MCP Server
- Claude Code, Codex and Kimi Code tools
- Article-to-video GitHub Action
- blog/WeChat/Bilibili/Xiaohongshu publishing workflows
- human review and approval gates before external publishing

# Changelog

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

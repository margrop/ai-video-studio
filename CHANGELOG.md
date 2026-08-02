# Changelog

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

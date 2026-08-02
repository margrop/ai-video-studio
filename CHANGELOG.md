# Changelog

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

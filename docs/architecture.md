# Architecture

## Core data flow

```mermaid
flowchart TD
  A["Topic / Markdown"] --> B["Workflow"]
  B --> C["Story Planner"]
  C --> D["Story Plan v1"]
  D --> E["Prompt Builder"]
  D --> F["TTS Provider"]
  E --> G["Video Provider or FFmpeg"]
  F --> G
  G --> H["MP4 + SRT + Plan"]
```

## Boundaries

| Layer | Responsibility | Must not do |
|---|---|---|
| API | validate and queue a job | choose provider from user input |
| Workflow | compose planner, TTS and renderer | know vendor SDK details |
| Planner | produce versioned Story Plan | execute side effects or publish content |
| Provider adapter | translate one vendor contract | leak raw errors or secrets |
| Subtitle/FFmpeg | deterministic media assembly | infer business content |
| Storage | job state and artifacts | persist credentials or raw provider responses |

## Provider-neutral contract

The current `StoryPlan` is the handoff point shared by future workflows. A video provider can consume each shot's `prompt`, while local FFmpeg can render the same plan as a reviewable slideshow. This keeps the first release useful without pretending that a hosted video model is already configured.

## Runtime topology

Phase 1 uses a filesystem queue:

```text
FastAPI → .aivs/queue → worker → .aivs/artifacts/{job_id}
```

Phase 2 can replace only `FileJobStore` with Redis/Postgres-backed storage. The API contract and workflow inputs should remain stable.

# Storage backends

AI Video Studio supports three job-store modes selected by the service-owned
`AIVS_STORAGE_BACKEND` setting:

| Backend | Default | Intended use | State location |
|---|---:|---|---|
| `filesystem` | yes | offline development and one trusted host | `.aivs/` |
| `redis` | no | multiple API/worker processes | Redis plus shared artifact root |
| `postgres` | no | multiple hosts with transactional metadata | PostgreSQL plus artifact backend |

Both backends implement the same job contract: idempotency keys, bounded
retries, worker leases, crash recovery, event streams, terminal usage records
and the API/worker state transitions. Public job input cannot select the
backend, provider, retry policy or lease policy.

## Redis mode

Install the optional client and configure the same namespace for every API and
worker process:

```bash
python -m pip install -e '.[dev,redis]'
export AIVS_STORAGE_BACKEND=redis
export AIVS_REDIS_URL=redis://127.0.0.1:6379/0
export AIVS_REDIS_NAMESPACE=aivs

uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
aivs-worker
```

The Redis queue uses an atomic reliable handoff (`RPOPLPUSH`). A claimed job
stays in the processing list until the worker finishes or fails it. If the
lease expires, the next worker requeues it or records a bounded terminal
failure. Delayed retries use a sorted set, and idempotency keys are stored as
SHA-256 fingerprints rather than raw request keys.

`AIVS_REDIS_URL` may contain the Redis deployment's authentication and TLS
options. Keep Redis on a private network; do not expose the Redis port or the
MCP stdio bridge to the public internet.

## PostgreSQL mode

PostgreSQL stores job metadata, idempotency hashes, worker leases, event
records, retry state and terminal usage records. Claims use a transaction with
`FOR UPDATE SKIP LOCKED`, allowing multiple workers to safely claim different
jobs without a separate queue service. The schema is created idempotently when
the backend starts.

Install the optional client and configure the same DSN for every API and worker:

```bash
python -m pip install -e '.[dev,postgres]'
export AIVS_STORAGE_BACKEND=postgres
export AIVS_POSTGRES_DSN=postgresql://aivs:replace-with-local-password@127.0.0.1:5432/aivs

uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
aivs-worker
```

PostgreSQL is metadata storage, not media storage. Keep
`AIVS_ARTIFACT_BACKEND=s3` for separate API/worker hosts, or use the default
filesystem artifact backend with a shared volume. When
`AIVS_CATALOG_BACKEND`, `AIVS_APPROVAL_BACKEND` and `AIVS_AUDIT_BACKEND` are
empty, they follow `AIVS_STORAGE_BACKEND`; therefore PostgreSQL mode also
shares Asset/Character metadata, approval history and publish audit events.
Set any of those variables to `filesystem` to keep that particular record type
on the service volume.

## Files and multi-host deployments

Redis and PostgreSQL store job metadata, queue state, events and usage records.
The PostgreSQL backend stores asset/character metadata, approval decisions and
publish audit events in separate `aivs_assets`, `aivs_characters`,
`aivs_social_approvals` and `aivs_publish_audit` tables. Binary catalog files
and worker temporary staging files remain below `AIVS_STORAGE_ROOT` unless a
future catalog file adapter is configured. Generated MP4/SRT/audio/plan files
can use the artifact backend described below.

Asset bytes are uploaded through `PUT /v1/assets/{asset_id}/content`; the
record's server-owned `storage_key` determines the destination. The endpoint
enforces `AIVS_MAX_ASSET_BYTES` (50 MiB by default), writes atomically and
records size plus SHA-256. PostgreSQL mode shares the metadata, but binary
catalog files still require a shared volume for every worker that needs to
read reference images.

## Artifact backends

Artifact storage is selected independently with the service-owned
`AIVS_ARTIFACT_BACKEND` setting:

| Backend | Default | Intended use | Published location |
|---|---:|---|---|
| `filesystem` | yes | one trusted host or shared volume | `AIVS_STORAGE_ROOT/artifacts/<job-id>/` |
| `s3` | no | AWS S3, MinIO or another S3-compatible store | `<bucket>/<prefix>/<job-id>/` |

The API and worker use the same `ArtifactStore` contract. The worker renders to
a local job staging directory, uploads every generated file only after the
render and social-draft bundle are complete, and then marks the job successful.
The API serves local files with `FileResponse` and streams S3 objects through
the authenticated artifact endpoint, so S3 credentials never reach a browser
or an MCP caller.

Install the optional client and configure the same bucket settings for the API
and every worker:

```bash
python -m pip install -e '.[dev,redis,s3]'
export AIVS_ARTIFACT_BACKEND=s3
export AIVS_S3_ENDPOINT_URL=http://127.0.0.1:9000  # omit for AWS S3
export AIVS_S3_BUCKET=aivs
export AIVS_S3_ACCESS_KEY_ID=minioadmin
export AIVS_S3_SECRET_ACCESS_KEY=replace-with-local-secret
export AIVS_S3_REGION=us-east-1
export AIVS_S3_PREFIX=aivs
```

Create the bucket before submitting jobs. For MinIO, the endpoint must be
reachable from both the API and worker containers. Keep credentials in a
server-side secret store or Compose secret environment; never put them in a
job request, artifact name, URL or repository file.

S3 publication is intentionally upload-only from the worker boundary. The
current release does not delete remote objects automatically; apply a bucket
lifecycle/retention policy appropriate for article bodies, narration and
generated media. External social publishing is a separate, approval-gated
boundary and is dry-run by default.

The filesystem backend remains the default so `aivs generate`, offline tests
and a single-host installation require no Redis service.

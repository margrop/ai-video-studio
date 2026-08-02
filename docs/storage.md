# Storage backends

AI Video Studio supports two job-store modes selected by the service-owned
`AIVS_STORAGE_BACKEND` setting:

| Backend | Default | Intended use | State location |
|---|---:|---|---|
| `filesystem` | yes | offline development and one trusted host | `.aivs/` |
| `redis` | no | multiple API/worker processes | Redis plus shared artifact root |

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

## Files and multi-host deployments

Redis stores job metadata, queue state, events and usage records. Asset and
Character catalogs, approval records and the worker's temporary staging files
remain below `AIVS_STORAGE_ROOT`. Generated MP4/SRT/audio/plan files can use the
artifact backend described below.

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
generated media. Catalog and approval metadata are still local, so separate
hosts require a shared volume for those records until the Postgres catalog
slice is implemented.

The filesystem backend remains the default so `aivs generate`, offline tests
and a single-host installation require no Redis service.

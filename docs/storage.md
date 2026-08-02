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

Redis stores job metadata, queue state, events and usage records. Generated
MP4/SRT/audio/plan files and the Asset/Character catalogs still live below
`AIVS_STORAGE_ROOT`. In Docker Compose, mount the same `aivs_data` volume into
all API and worker replicas. For separate hosts, the next storage slice must
replace these local paths with an object-storage adapter and a shared catalog
database; Redis alone does not make local files portable.

The filesystem backend remains the default so `aivs generate`, offline tests
and a single-host installation require no Redis service.

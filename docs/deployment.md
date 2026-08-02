# Local deployment

## Docker Compose

Copy `.env.example` to `.env`, fill only the server-side credentials you intend
to use, then run:

```bash
docker compose up --build
```

Open <http://127.0.0.1:8000/dashboard>. The API and worker share the named
`aivs_data` volume, so queue leases, events, usage records and artifacts use the
same state directory.

The default Compose configuration uses the filesystem queue and filesystem
artifact backend. To use Redis for more than one API/worker process, set:

```dotenv
AIVS_STORAGE_BACKEND=redis
AIVS_REDIS_URL=redis://redis:6379/0
AIVS_REDIS_NAMESPACE=aivs
AIVS_API_KEY=replace-with-a-long-random-secret
AIVS_RATE_LIMIT_PER_MINUTE=120
AIVS_RATE_LIMIT_WINDOW_SECONDS=60
```

The included Redis service persists its append-only data in `redis_data`.
Redis makes queue metadata and leases shareable; `aivs_data` must still be
shared by every process because artifacts and local catalogs remain on disk.
See [`storage.md`](storage.md) for the handoff and recovery semantics.

For separate API and worker hosts, publish generated artifacts to S3 or MinIO:

```dotenv
AIVS_STORAGE_BACKEND=redis
AIVS_ARTIFACT_BACKEND=s3
AIVS_S3_ENDPOINT_URL=http://minio.internal:9000
AIVS_S3_BUCKET=aivs
AIVS_S3_ACCESS_KEY_ID=server-side-access-key
AIVS_S3_SECRET_ACCESS_KEY=server-side-secret
AIVS_S3_REGION=us-east-1
AIVS_S3_PREFIX=production
```

The API and worker must receive the same bucket, region and prefix settings.
The artifact endpoint remains behind the API key boundary. Keep a shared
volume for catalogs and approvals until those records move to Postgres.

For PostgreSQL-backed metadata, use the included Compose database or an
operator-managed PostgreSQL instance:

```dotenv
AIVS_STORAGE_BACKEND=postgres
AIVS_POSTGRES_DSN=postgresql://aivs:server-side-password@postgres:5432/aivs
AIVS_ARTIFACT_BACKEND=s3
```

The service bootstraps only the AIVS job, event, idempotency and usage tables;
it does not run destructive migrations or modify unrelated database objects.

## Production boundary

The filesystem queue is a trusted single-host baseline. Redis and PostgreSQL
are available for multi-process metadata, and the S3-compatible artifact
backend is available for multi-process deployments,
but a public deployment still needs authentication, rate limiting,
cost/concurrency budgets and a retention policy. Do not expose the dashboard,
Redis or MCP stdio bridge directly to the public internet.

`/health` is intentionally unauthenticated for liveness probes. Configure the
API key before exposing `/v1` or serving the dashboard through a public proxy;
see [`security.md`](security.md) for the client header contract.

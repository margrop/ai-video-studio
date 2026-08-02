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

The default Compose configuration uses the filesystem queue. To use Redis for
more than one API/worker process, set:

```dotenv
AIVS_STORAGE_BACKEND=redis
AIVS_REDIS_URL=redis://redis:6379/0
AIVS_REDIS_NAMESPACE=aivs
```

The included Redis service persists its append-only data in `redis_data`.
Redis makes queue metadata and leases shareable; `aivs_data` must still be
shared by every process because artifacts and local catalogs remain on disk.
See [`storage.md`](storage.md) for the handoff and recovery semantics.

## Production boundary

The filesystem queue is a trusted single-host baseline. Redis is now an
available multi-process queue backend, but a public deployment still needs
authentication, rate limiting, cost/concurrency budgets and a retention policy.
For separate hosts, move asset/artifact storage to a retention-controlled
object store. Do not expose the dashboard, Redis or MCP stdio bridge directly
to the public internet.

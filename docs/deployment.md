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

## Production boundary

The included filesystem queue is a trusted single-host baseline. Before
running multiple API/worker replicas, replace `FileJobStore` with a durable
Redis/Postgres implementation, add authentication and rate limiting, and move
asset/artifact storage to a retention-controlled object store. Do not expose
the dashboard or MCP stdio bridge directly to the public internet.

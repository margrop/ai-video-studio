# Publishing workflow and safety boundary

AIVS generates social drafts as `social-drafts.json` after a successful render.
The bundle covers blog, WeChat, Zhihu, Bilibili, Xiaohongshu, Douyin and
podcast-shaped copy, and every draft has:

- `requires_human_approval: true`;
- `published: false`;
- deterministic content derived from the validated Story Plan.

The core project deliberately ships with no real external posting connector.
It does ship the boundary that an adapter must cross: publisher registration,
dry-run preview, latest human approval, safe error handling and an append-only
audit record. A generated draft must never be interpreted as a successful
publication.

## Human review API

After a successful job, reviewers can inspect the bundle and append a decision:

```http
GET /v1/jobs/{job_id}/social-drafts
GET /v1/jobs/{job_id}/approvals
POST /v1/jobs/{job_id}/approvals
Content-Type: application/json

{"platform":"wechat","decision":"approved","reviewer":"editor","note":"ready"}
```

Decisions are append-only. A later rejection supersedes an earlier approval for
the same platform when the publish boundary evaluates the latest record. The
following endpoints are available after the job succeeds:

```http
GET /v1/jobs/{job_id}/publish-audit
POST /v1/jobs/{job_id}/publish
Content-Type: application/json

{"platform":"wechat"}
```

The publish request defaults to `dry_run: true`, which records a preview and
does not call a publisher. A non-dry-run request is blocked unless the latest
decision is `approved`; after approval it returns `unavailable` until a
platform adapter is explicitly registered and `AIVS_EXTERNAL_PUBLISH_ENABLED`
is set to `true`. This makes the absence of a credential, vendor adapter or
service-level opt-in a visible state rather than a fake success.

An adapter implements the provider-neutral contract:

```python
class Publisher(Protocol):
    publisher_id: str
    platform: SocialPlatform

    async def publish(self, draft: SocialDraft, *, video_path: Path | None = None) -> str: ...
```

Adapters must own their credentials, timeouts, rate limits and platform tests;
they must not be selected by public job input. The audit record stores only the
platform, actor, safe status/message and optional external ID—never tokens or
raw provider payloads.

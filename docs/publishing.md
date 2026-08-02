# Publishing workflow

AIVS generates social drafts as `social-drafts.json` after a successful render.
The bundle covers blog, WeChat, Zhihu, Bilibili, Xiaohongshu, Douyin and
podcast-shaped copy, and every draft has:

- `requires_human_approval: true`;
- `published: false`;
- deterministic content derived from the validated Story Plan.

The current project deliberately has no external posting connector. Adding one
requires a separate provider adapter, credential boundary, platform-specific
tests, rate limits and an explicit approval transition. A generated draft must
never be interpreted as a successful publication.

## Human review API

After a successful job, reviewers can inspect the bundle and append a decision:

```http
GET /v1/jobs/{job_id}/social-drafts
GET /v1/jobs/{job_id}/approvals
POST /v1/jobs/{job_id}/approvals
Content-Type: application/json

{"platform":"wechat","decision":"approved","reviewer":"editor","note":"ready"}
```

Decisions are stored below the server-owned approval root as an append-only
history. A later rejection supersedes an earlier approval for the same
platform when an external workflow evaluates the latest record. No endpoint in
this project marks a draft as published or sends credentials to a platform.

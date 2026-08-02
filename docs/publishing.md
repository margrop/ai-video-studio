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

# GitHub Actions

The repository includes a manual `Article to Video` workflow at
[`.github/workflows/article-to-video.yml`](../.github/workflows/article-to-video.yml).
It turns a topic or Markdown file into an artifact package containing:

- `video.mp4`;
- `story-plan.json`;
- `subtitles.srt`;
- `narration.wav`;
- `social-drafts.json`.

Open **Actions → Article to Video → Run workflow**, then provide the topic and,
optionally, a repository-relative `.md` path. The default is deterministic
offline planning. To use the configured planner, select `use_ai` and add these
repository or environment secrets:

```text
AIVS_LLM_BASE_URL
AIVS_LLM_API_KEY
AIVS_LLM_MODEL
```

The workflow validates that the source path stays inside the checked-out
repository and only accepts Markdown extensions. It never accepts a provider,
model or key through workflow inputs, and it does not publish to any external
platform.

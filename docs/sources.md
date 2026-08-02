# Content sources

The CLI supports Markdown and RSS/Atom sources without giving source text any
control over providers or runtime policy.

```bash
# Markdown is supported by the existing --source option.
aivs generate "AI Gateway" --source examples/tech-blog.md --no-ai

# Pick one RSS/Atom item by zero-based index.
aivs rss https://example.com/feed.xml --item 0 --no-ai \
  --output artifacts/news.mp4
```

Feeds are limited to 1 MB and 20 items per request, require HTTP(S), use a
finite timeout and are parsed into the same `CreateJobRequest` as a local
article. The source URL is displayed for review; it is not automatically
published or treated as an instruction.

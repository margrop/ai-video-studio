# MCP / Agent integration

The optional MCP server exposes the same server-owned contracts as the HTTP
API. It does not accept a provider, model, API key, retry policy or arbitrary
filesystem path from the agent.

Install and run it locally:

```bash
python -m pip install -e '.[mcp]'
aivs-mcp
```

Configure the command in the MCP-capable client using the absolute path to the
repository virtual environment, for example:

```json
{
  "mcpServers": {
    "ai-video-studio": {
      "command": "/path/to/ai-video-studio/.venv/bin/aivs-mcp"
    }
  }
}
```

Available tools:

- `generate_video`: queue and process an Article → Video → Voice → Social job;
- `inspect_job`: inspect safe state events and local artifact paths;
- `list_jobs`: list recent jobs;
- `create_social_drafts`: regenerate reviewable social drafts without posting.

The stdio server is intended for a trusted local agent process. Use the HTTP
API behind authentication for shared or internet-facing deployments.

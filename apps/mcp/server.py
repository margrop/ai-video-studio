"""Optional stdio MCP server.

Install the ``mcp`` extra to expose these functions to an agent. The core
service remains importable and testable without the optional SDK.
"""

from __future__ import annotations

from apps.mcp.service import AIVSToolService


def create_server(service: AIVSToolService | None = None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without optional extra
        raise RuntimeError("Install ai-video-studio[mcp] to run the MCP server") from exc

    tool_service = service or AIVSToolService.from_env()
    server = FastMCP("ai-video-studio")

    @server.tool()
    async def generate_video(
        topic: str,
        source_markdown: str = "",
        duration_seconds: int = 60,
        language: str = "zh-CN",
        voice: str = "neutral",
        use_ai: bool = False,
        template_id: str = "tech-blog-v1",
        character_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        """Create and process one Article → Video → Voice → Social job."""

        return await tool_service.generate_video(
            topic=topic,
            source_markdown=source_markdown,
            duration_seconds=duration_seconds,
            language=language,
            voice=voice,
            use_ai=use_ai,
            template_id=template_id,
            character_id=character_id,
            idempotency_key=idempotency_key,
        )

    @server.tool()
    async def inspect_job(job_id: str) -> dict[str, object]:
        """Inspect a job, safe events and generated artifact paths."""

        return tool_service.inspect_job(job_id)

    @server.tool()
    async def list_jobs(status: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        """List recent AIVS jobs."""

        return tool_service.list_jobs(status=status, limit=limit)

    @server.tool()
    async def create_social_drafts(job_id: str) -> dict[str, object]:
        """Create reviewable social drafts; this never publishes externally."""

        return tool_service.create_social_drafts(job_id)

    return server


def main() -> None:
    create_server().run(transport="stdio")

"""One-command local CLI for planning and rendering."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import typer

from packages.contracts.models import CreateJobRequest
from packages.planner import StoryPlanner
from packages.runtime import build_default_workflow

app = typer.Typer(add_completion=False, help="AI Video Studio content pipeline.")


def _read_source(source: Path | None) -> str:
    if source is None:
        return ""
    if not source.is_file():
        raise typer.BadParameter(f"source file not found: {source}")
    return source.read_text(encoding="utf-8")


@app.command()
def plan(
    topic: str = typer.Argument(..., help="Topic or article title."),
    source: Path | None = typer.Option(None, "--source", help="Optional Markdown source."),
    duration: int = typer.Option(60, min=15, max=180, help="Target duration in seconds."),
    no_ai: bool = typer.Option(False, "--no-ai", help="Use the deterministic planner."),
    output: Path | None = typer.Option(None, "--output", help="Write the StoryPlan JSON here."),
) -> None:
    """Create a StoryPlan without rendering video."""

    async def run() -> None:
        result = await StoryPlanner(provider=None).plan(
            topic=topic,
            source_markdown=_read_source(source),
            duration_seconds=duration,
            use_ai=not no_ai,
        )
        text = result.plan.model_dump_json(indent=2)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text + "\n", encoding="utf-8")
            typer.echo(str(output))
        else:
            typer.echo(text)

    asyncio.run(run())


@app.command()
def generate(
    topic: str = typer.Argument(..., help="Topic or article title."),
    source: Path | None = typer.Option(None, "--source", help="Optional Markdown source."),
    output: Path = typer.Option(Path("artifacts/video.mp4"), "--output", help="Output MP4 path."),
    duration: int = typer.Option(60, min=15, max=180, help="Target duration in seconds."),
    no_ai: bool = typer.Option(False, "--no-ai", help="Use the deterministic planner."),
) -> None:
    """Generate a vertical MP4 from a topic or Markdown article."""

    async def run() -> None:
        request = CreateJobRequest(
            topic=topic,
            source_markdown=_read_source(source),
            duration_seconds=duration,
            use_ai=not no_ai,
        )
        work_dir = output.parent / f".{output.stem}-aivs"
        result = await build_default_workflow().run(request, work_dir)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(result.video_path, output)
        typer.echo(f"video: {output}")
        typer.echo(f"plan: {result.plan_path}")
        typer.echo(f"subtitles: {result.subtitle_path}")
        if result.warnings:
            typer.echo("warnings: " + " | ".join(result.warnings))

    asyncio.run(run())

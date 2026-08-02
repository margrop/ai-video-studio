"""Filesystem queue worker."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer

from packages.runtime import build_default_workflow
from packages.storage import FileJobStore

app = typer.Typer(add_completion=False, help="Process AI Video Studio render jobs.")


async def process_once(store: FileJobStore) -> bool:
    record = store.claim_next()
    if record is None:
        return False
    output_dir = store.artifacts_dir / str(record.job_id)
    try:
        result = await build_default_workflow().run(record.request, output_dir)
        record.status = "succeeded"
        record.plan_path = result.plan_path.name
        record.subtitle_path = result.subtitle_path.name
        record.audio_path = result.audio_path.name
        record.video_path = result.video_path.name
    except Exception as exc:  # noqa: BLE001 - worker must convert failures to job state.
        record.status = "failed"
        record.error_code = "render_failed"
        record.error_message = f"{type(exc).__name__}: {str(exc)[:400]}"
    store.finish(record)
    return True


@app.command()
def run(
    once: bool = typer.Option(False, "--once", help="Process at most one queued job."),
    interval: float = typer.Option(2.0, min=0.2, max=60, help="Polling interval in seconds."),
    storage_root: Path = typer.Option(
        Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs")), "--storage-root"
    ),
) -> None:
    """Process queued jobs until --once or Ctrl-C."""
    store = FileJobStore(storage_root)

    async def loop() -> None:
        while True:
            processed = await process_once(store)
            if once:
                return
            if not processed:
                await asyncio.sleep(interval)

    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None

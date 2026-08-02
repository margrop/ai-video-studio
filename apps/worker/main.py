"""Filesystem queue worker."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer

from packages.library import CatalogNotFound
from packages.runtime import AppRuntime, build_runtime
from packages.storage import FileJobStore

app = typer.Typer(add_completion=False, help="Process AI Video Studio render jobs.")


async def process_once(store: FileJobStore, runtime: AppRuntime | None = None) -> bool:
    record = store.claim_next()
    if record is None:
        return False
    output_dir = store.artifacts_dir / str(record.job_id)
    app_runtime = runtime or build_runtime(store.root)
    try:
        character_prompt = ""
        if record.request.character_id is not None:
            character = app_runtime.characters.get(record.request.character_id)
            if character is None:
                raise CatalogNotFound(f"character is not registered: {record.request.character_id}")
            character_prompt = character.prompt
        prompt_config = app_runtime.templates.prompt_config(record.request.template_id)
        result = await app_runtime.workflow.run(
            record.request,
            output_dir,
            character_prompt=character_prompt,
            prompt_config=prompt_config,
        )
        record.status = "succeeded"
        record.plan_path = result.plan_path.name
        record.subtitle_path = result.subtitle_path.name
        record.audio_path = result.audio_path.name
        record.video_path = result.video_path.name
    except CatalogNotFound as exc:
        store.fail(
            record,
            error_code="invalid_job_reference",
            error_message=str(exc),
            retryable=False,
        )
    except Exception as exc:  # noqa: BLE001 - worker must convert failures to job state.
        store.fail(
            record,
            error_code="render_failed",
            error_message=f"{type(exc).__name__}: {str(exc)[:400]}",
        )
    else:
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
    store = FileJobStore.from_env(storage_root)
    runtime = build_runtime(store.root)

    async def loop() -> None:
        while True:
            processed = await process_once(store, runtime)
            if once:
                return
            if not processed:
                await asyncio.sleep(interval)

    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None

"""Filesystem queue worker."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer

from packages.library import CatalogNotFound
from packages.providers import VideoProviderError
from packages.publishing import write_social_drafts
from packages.runtime import AppRuntime, build_runtime
from packages.storage import ArtifactStore, JobStore, build_artifact_store, build_job_store

app = typer.Typer(add_completion=False, help="Process AI Video Studio render jobs.")


async def process_once(
    store: JobStore,
    runtime: AppRuntime | None = None,
    artifact_store: ArtifactStore | None = None,
) -> bool:
    record = store.claim_next()
    if record is None:
        return False
    generated_artifacts = artifact_store or build_artifact_store(store.root)
    output_dir = generated_artifacts.job_dir(record.job_id)
    app_runtime = runtime or build_runtime(store.root)
    try:
        character_prompt = ""
        reference_images: list[Path] = []
        if record.request.character_id is not None:
            character = app_runtime.characters.get(record.request.character_id)
            if character is None:
                raise CatalogNotFound(f"character is not registered: {record.request.character_id}")
            character_prompt = character.prompt
            reference_images = [
                path
                for asset_id in character.reference_asset_ids
                if (path := app_runtime.assets.local_path(asset_id)) is not None
            ]
        prompt_config = app_runtime.templates.prompt_config(record.request.template_id)
        result = await app_runtime.workflow.run(
            record.request,
            output_dir,
            character_prompt=character_prompt,
            reference_images=tuple(reference_images),
            prompt_config=prompt_config,
        )
        record.status = "succeeded"
        record.plan_path = result.plan_path.name
        record.subtitle_path = result.subtitle_path.name
        record.audio_path = result.audio_path.name
        record.video_path = result.video_path.name
        social_path = write_social_drafts(result.plan, output_dir / "social-drafts.json")
        record.social_drafts_path = social_path.name
        generated_artifacts.publish(record.job_id, output_dir)
    except CatalogNotFound as exc:
        store.fail(
            record,
            error_code="invalid_job_reference",
            error_message=str(exc),
            retryable=False,
            provider_id="pipeline",
        )
    except VideoProviderError as exc:
        store.fail(
            record,
            error_code=exc.code,
            error_message=str(exc),
            retryable=exc.retryable,
            provider_id=app_runtime.video_provider.provider_id
            if app_runtime.video_provider is not None
            else "pipeline",
        )
    except Exception as exc:  # noqa: BLE001 - worker must convert failures to job state.
        store.fail(
            record,
            error_code="render_failed",
            error_message=f"{type(exc).__name__}: {str(exc)[:400]}",
            provider_id=getattr(app_runtime.workflow.tts_provider, "provider_id", "pipeline"),
        )
    else:
        store.finish(record, provider_id=result.video_provider_id or result.mode)
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
    store = build_job_store(storage_root)
    runtime = build_runtime(store.root)
    artifact_store = build_artifact_store(store.root)

    async def loop() -> None:
        while True:
            processed = await process_once(store, runtime, artifact_store)
            if once:
                return
            if not processed:
                await asyncio.sleep(interval)

    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None

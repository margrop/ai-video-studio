import asyncio

from apps.mcp.service import AIVSToolService
from apps.worker.main import process_once
from packages.contracts.models import CreateJobRequest
from packages.runtime import build_runtime
from packages.storage import FileJobStore


def test_agent_service_reuses_the_same_job_contract(tmp_path) -> None:
    store = FileJobStore(tmp_path / "state")
    service = AIVSToolService(store=store, runtime=build_runtime(store.root))
    record = store.create(CreateJobRequest(topic="Agent inspection", use_ai=False))

    listed = service.list_jobs()
    inspected = service.inspect_job(str(record.job_id))

    assert listed[0]["job_id"] == str(record.job_id)
    assert inspected["job"]["status"] == "queued"
    assert inspected["events"][0]["event_type"] == "queued"


def test_worker_emits_social_draft_artifact_for_agent_jobs(tmp_path) -> None:
    store = FileJobStore(tmp_path / "state")
    runtime = build_runtime(store.root)
    service = AIVSToolService(store=store, runtime=runtime)
    record = store.create(CreateJobRequest(topic="Agent render", use_ai=False, duration_seconds=15))

    assert asyncio.run(process_once(store, runtime)) is True
    inspected = service.inspect_job(str(record.job_id))

    assert inspected["job"]["status"] == "succeeded"
    assert "social-drafts.json" in inspected["artifacts"]


def test_agent_publish_tool_is_dry_run_by_default(tmp_path) -> None:
    store = FileJobStore(tmp_path / "state")
    runtime = build_runtime(store.root)
    service = AIVSToolService(store=store, runtime=runtime)
    record = store.create(
        CreateJobRequest(topic="Agent publish preview", use_ai=False, duration_seconds=15)
    )

    assert asyncio.run(process_once(store, runtime)) is True
    result = asyncio.run(service.publish_social_draft(job_id=str(record.job_id), platform="wechat"))

    assert result["status"] == "dry_run"
    assert result["dry_run"] is True
    assert service.list_publish_audit(str(record.job_id))[0]["action"] == "publish_dry_run"

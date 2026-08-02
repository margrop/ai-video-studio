from packages.contracts.models import CreateJobRequest
from packages.storage import FileJobStore


def test_file_job_store_transitions_queued_to_running(tmp_path) -> None:
    store = FileJobStore(tmp_path / "state")
    created = store.create(CreateJobRequest(topic="Synthetic", use_ai=False))

    assert store.get(created.job_id).status == "queued"
    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.job_id == created.job_id
    assert claimed.status == "running"

    claimed.status = "succeeded"
    store.finish(claimed)
    assert store.get(created.job_id).status == "succeeded"

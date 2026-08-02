from datetime import UTC, datetime, timedelta

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
    assert [event.event_type for event in store.events(created.job_id)] == [
        "queued",
        "running",
        "succeeded",
    ]
    usage = store.usage.summary()
    assert usage.total_jobs == 1
    assert usage.successful_jobs == 1
    assert usage.total_duration_seconds == created.request.duration_seconds


def test_file_job_store_persists_shot_progress_and_finalizes_it(tmp_path) -> None:
    store = FileJobStore(tmp_path / "state")
    created = store.create(CreateJobRequest(topic="Progress", use_ai=False))
    claimed = store.claim_next()
    assert claimed is not None

    store.update_progress(
        claimed,
        stage="video",
        completed_shots=3,
        total_shots=8,
        current_shot=4,
        message="已完成 Shot 3/8",
    )
    observed = store.get(created.job_id)
    assert observed is not None
    assert observed.progress.percent == 51
    assert observed.progress.current_shot == 4
    assert store.events(created.job_id)[-1].event_type == "progress"

    claimed.status = "succeeded"
    store.finish(claimed)
    assert store.get(created.job_id).progress.stage == "completed"
    assert store.get(created.job_id).progress.percent == 100


def test_idempotency_key_returns_the_original_job_without_a_duplicate(tmp_path) -> None:
    store = FileJobStore(tmp_path / "state")
    request = CreateJobRequest(topic="Idempotent", use_ai=False)

    first = store.create(request, idempotency_key="request-123")
    second = store.create(request, idempotency_key="request-123")

    assert second.job_id == first.job_id
    assert len(store.list_jobs()) == 1


def test_failure_is_requeued_until_retry_budget_is_exhausted(tmp_path) -> None:
    store = FileJobStore(
        tmp_path / "state",
        max_attempts=2,
        retry_backoff_seconds=0,
    )
    created = store.create(CreateJobRequest(topic="Retry", use_ai=False))

    first_claim = store.claim_next()
    assert first_claim is not None
    retried = store.fail(
        first_claim,
        error_code="synthetic_failure",
        error_message="provider failed with token=do-not-persist",
    )
    assert retried.status == "queued"
    assert retried.error_message == "provider failed with token=[REDACTED]"

    second_claim = store.claim_next()
    assert second_claim is not None
    exhausted = store.fail(
        second_claim,
        error_code="synthetic_failure",
        error_message="still unavailable",
    )
    assert exhausted.status == "failed"
    assert exhausted.attempt == 2
    assert [event.event_type for event in store.events(created.job_id)] == [
        "queued",
        "running",
        "retrying",
        "running",
        "failed",
    ]


def test_expired_lease_is_recovered_on_the_next_claim(tmp_path) -> None:
    store = FileJobStore(tmp_path / "state", max_attempts=2)
    created = store.create(CreateJobRequest(topic="Lease", use_ai=False))
    claimed = store.claim_next()
    assert claimed is not None
    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    store.save(claimed)

    assert store.recover_expired_leases() == 1
    recovered = store.get(created.job_id)
    assert recovered is not None
    assert recovered.status == "queued"
    assert recovered.error_code == "lease_expired"

import asyncio

from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.contracts.models import CreateJobRequest
from packages.planner import StoryPlanner
from packages.publishing import write_social_drafts
from packages.storage import FileJobStore


def test_api_queues_job_without_accepting_provider_controls(tmp_path) -> None:
    client = TestClient(create_app(store=FileJobStore(tmp_path / "state")))

    assert client.get("/").status_code == 200
    assert "内容流水线控制台" in client.get("/dashboard").text
    assert client.get("/dashboard/app.js").status_code == 200
    assert client.get("/dashboard/styles.css").status_code == 200
    assert client.get("/dashboard/secret.txt").status_code == 404

    response = client.post(
        "/v1/jobs",
        json={"topic": "Synthetic API job", "duration_seconds": 15, "use_ai": False},
        headers={"Idempotency-Key": "api-request-1"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert client.get(f"/v1/jobs/{body['job_id']}").json()["job_id"] == body["job_id"]
    duplicate = client.post(
        "/v1/jobs",
        json={"topic": "Synthetic API job", "duration_seconds": 15, "use_ai": False},
        headers={"Idempotency-Key": "api-request-1"},
    )
    assert duplicate.json()["job_id"] == body["job_id"]
    assert client.get("/v1/jobs").json()[0]["job_id"] == body["job_id"]
    assert client.get("/v1/stats").json()["queue_depth"] == 1
    assert client.get("/v1/usage").json()["total_jobs"] == 0
    assert client.get("/v1/providers").json()["providers"]
    assert client.get("/v1/templates").json()[0]["template_id"] == "tech-blog-v1"
    assert client.get(f"/v1/jobs/{body['job_id']}/events").json()[0]["event_type"] == "queued"

    asset = client.post(
        "/v1/assets",
        json={"name": "Brand logo", "kind": "logo", "storage_key": "brand/logo.svg"},
    )
    assert asset.status_code == 201
    character = client.post(
        "/v1/characters",
        json={
            "name": "Studio host",
            "prompt": "consistent technology host",
            "reference_asset_ids": [asset.json()["asset_id"]],
        },
    )
    assert character.status_code == 201
    assert client.get("/v1/characters").json()[0]["name"] == "Studio host"
    invalid_reference = client.post(
        "/v1/characters",
        json={
            "name": "Broken",
            "prompt": "host",
            "reference_asset_ids": ["00000000-0000-0000-0000-000000000001"],
        },
    )
    assert invalid_reference.status_code == 422

    invalid_template = client.post(
        "/v1/jobs",
        json={"topic": "Bad template", "template_id": "../../secret", "use_ai": False},
    )
    assert invalid_template.status_code == 422

    rejected = client.post(
        "/v1/jobs",
        json={"topic": "Synthetic API job", "provider": "minimax"},
    )
    assert rejected.status_code == 422


def test_api_exposes_reviewable_social_draft_approvals(tmp_path) -> None:
    store = FileJobStore(tmp_path / "state")
    client = TestClient(create_app(store=store))
    record = store.create(
        CreateJobRequest(topic="Approval test", duration_seconds=15, use_ai=False)
    )
    claimed = store.claim_next()
    assert claimed is not None
    claimed.status = "succeeded"
    write_social_drafts(
        asyncio.run(
            StoryPlanner().plan(topic="Approval test", duration_seconds=15, use_ai=False)
        ).plan,
        store.artifacts_dir / str(record.job_id) / "social-drafts.json",
    )
    store.finish(claimed)

    assert client.get(f"/v1/jobs/{record.job_id}/approvals").json() == []
    decision = client.post(
        f"/v1/jobs/{record.job_id}/approvals",
        json={
            "platform": "wechat",
            "decision": "approved",
            "reviewer": "test-editor",
            "note": "Looks good.",
        },
    )
    assert decision.status_code == 201
    assert decision.json()["decision"] == "approved"
    assert client.get(f"/v1/jobs/{record.job_id}/approvals").json()[0]["platform"] == "wechat"

    preview = client.post(
        f"/v1/jobs/{record.job_id}/publish",
        json={"platform": "wechat"},
    )
    assert preview.status_code == 200
    assert preview.json()["status"] == "dry_run"
    assert preview.json()["approved"] is True

    publish = client.post(
        f"/v1/jobs/{record.job_id}/publish",
        json={"platform": "wechat", "dry_run": False},
    )
    assert publish.status_code == 200
    assert publish.json()["status"] == "unavailable"
    assert client.get(f"/v1/jobs/{record.job_id}/publish-audit").json()[-1]["action"] == (
        "publish_unavailable"
    )

    invalid_platform = client.post(
        f"/v1/jobs/{record.job_id}/approvals",
        json={"platform": "not-a-platform", "decision": "approved"},
    )
    assert invalid_platform.status_code == 422

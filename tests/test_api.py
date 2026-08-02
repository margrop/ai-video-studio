from fastapi.testclient import TestClient

from apps.api.main import create_app
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
    assert client.get("/v1/providers").json()["providers"]
    assert client.get(f"/v1/jobs/{body['job_id']}/events").json()[0]["event_type"] == "queued"

    rejected = client.post(
        "/v1/jobs",
        json={"topic": "Synthetic API job", "provider": "minimax"},
    )
    assert rejected.status_code == 422

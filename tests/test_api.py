from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.storage import FileJobStore


def test_api_queues_job_without_accepting_provider_controls(tmp_path) -> None:
    client = TestClient(create_app(store=FileJobStore(tmp_path / "state")))

    response = client.post(
        "/v1/jobs",
        json={"topic": "Synthetic API job", "duration_seconds": 15, "use_ai": False},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert client.get(f"/v1/jobs/{body['job_id']}").json()["job_id"] == body["job_id"]

    rejected = client.post(
        "/v1/jobs",
        json={"topic": "Synthetic API job", "provider": "minimax"},
    )
    assert rejected.status_code == 422

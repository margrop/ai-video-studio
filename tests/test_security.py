from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.security.api import FixedWindowRateLimiter
from packages.storage import FileJobStore


def test_api_key_is_optional_locally_and_required_when_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIVS_API_KEY", "local-test-secret-123")
    monkeypatch.setenv("AIVS_RATE_LIMIT_PER_MINUTE", "100")
    client = TestClient(create_app(store=FileJobStore(tmp_path / "state")))

    assert client.get("/health").status_code == 200
    assert client.get("/v1/stats").status_code == 401
    assert client.get("/v1/stats", headers={"Authorization": "Bearer wrong"}).status_code == 401

    response = client.get(
        "/v1/stats",
        headers={"Authorization": "Bearer local-test-secret-123"},
    )
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "100"


def test_rate_limiter_returns_429_after_the_service_owned_budget(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AIVS_API_KEY", raising=False)
    monkeypatch.setenv("AIVS_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("AIVS_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app(store=FileJobStore(tmp_path / "state")))

    assert client.get("/v1/stats").status_code == 200
    limited = client.get("/v1/stats")

    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate_limit_exceeded"}
    assert int(limited.headers["Retry-After"]) >= 1


def test_fixed_window_limiter_resets_without_unbounded_memory_growth() -> None:
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=60)

    assert limiter.check("client", now=120).allowed is True
    assert limiter.check("client", now=120).allowed is True
    assert limiter.check("client", now=120).allowed is False
    assert limiter.check("client", now=180).allowed is True

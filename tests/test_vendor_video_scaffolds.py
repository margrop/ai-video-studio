from packages.runtime import build_runtime
from providers.kling import KlingVideoProvider
from providers.minimax import MiniMaxVideoProvider
from providers.openai import OpenAIVideoProvider
from providers.runway import RunwayVideoProvider
from providers.veo import GoogleVeoVideoProvider


def test_vendor_scaffolds_use_server_owned_prefixed_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AIVS_KLING_VIDEO_BASE_URL", "https://kling.test")
    monkeypatch.setenv("AIVS_KLING_VIDEO_API_KEY", "server-secret")
    monkeypatch.setenv("AIVS_KLING_VIDEO_MODEL", "kling-test")

    provider = KlingVideoProvider.from_env()

    assert provider.provider_id == "kling"
    assert provider.base_url == "https://kling.test"
    assert provider.model == "kling-test"
    assert provider.capabilities == (
        "async-generation",
        "remote-download",
        "shot-generation",
    )


def test_all_vendor_scaffold_ids_are_stable() -> None:
    assert MiniMaxVideoProvider.provider_id == "minimax-video"
    assert GoogleVeoVideoProvider.provider_id == "google-veo"
    assert RunwayVideoProvider.provider_id == "runway"
    assert OpenAIVideoProvider.provider_id == "openai-video"


def test_runtime_activates_a_configured_vendor_scaffold(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AIVS_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("AIVS_KLING_VIDEO_BASE_URL", "https://kling.test")
    monkeypatch.setenv("AIVS_KLING_VIDEO_API_KEY", "server-secret")
    monkeypatch.setenv("AIVS_KLING_VIDEO_MODEL", "kling-test")

    runtime = build_runtime(tmp_path)

    assert runtime.video_provider is not None
    assert runtime.video_provider.provider_id == "kling"
    descriptor = next(
        item for item in runtime.providers.descriptors() if item.provider_id == "kling"
    )
    assert "shot-generation" in descriptor.capabilities

import pytest

from packages.providers import ProviderRegistry


class SyntheticProvider:
    provider_id = "synthetic"


def test_registry_is_explicit_and_rejects_duplicates() -> None:
    registry = ProviderRegistry()
    provider = SyntheticProvider()
    registry.register(provider)
    assert registry.ids() == ("synthetic",)
    assert registry.get("synthetic") is provider
    assert registry.descriptors()[0].kind == "video"
    with pytest.raises(ValueError):
        registry.register(provider)


def test_registry_selects_only_capability_compatible_providers() -> None:
    registry = ProviderRegistry()
    slideshow = SyntheticProvider()
    slideshow.provider_id = "slideshow"
    remote = SyntheticProvider()
    remote.provider_id = "remote"
    registry.register(slideshow, capabilities=("slideshow",))
    registry.register(remote, capabilities=("shot-generation", "remote-download"))

    assert registry.select(kind="video", required_capabilities=("shot-generation",)) is remote
    assert registry.select(kind="video", required_capabilities=("reference-images",)) is None
    assert registry.select(kind="video", preferred_id="slideshow") is slideshow

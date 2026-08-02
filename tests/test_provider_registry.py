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
    with pytest.raises(ValueError):
        registry.register(provider)

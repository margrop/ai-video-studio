from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.models import CreateAssetRequest, CreateCharacterRequest
from packages.library import AssetCatalog, CharacterCatalog, TemplateCatalog
from packages.storyboard import PromptBuilder


def test_asset_and_character_catalogs_keep_reusable_server_owned_records(tmp_path) -> None:
    assets = AssetCatalog(tmp_path / "assets")
    characters = CharacterCatalog(tmp_path / "characters", assets)
    source = tmp_path / "logo.svg"
    source.write_text("<svg />", encoding="utf-8")

    asset = assets.import_file(
        source,
        CreateAssetRequest(name="Studio logo", kind="logo", storage_key="brand/logo.svg"),
    )
    character = characters.create(
        CreateCharacterRequest(
            name="AIVS guide",
            prompt="consistent friendly technology host, dark jacket",
            reference_asset_ids=[asset.asset_id],
        )
    )

    assert assets.get(asset.asset_id).sha256 is not None
    assert (
        assets.local_path(asset.asset_id)
        == (tmp_path / "assets" / "files" / "brand" / "logo.svg").resolve()
    )
    assert characters.get(character.character_id).prompt.startswith("consistent")


def test_catalogs_reject_path_traversal_and_unknown_references(tmp_path) -> None:
    with pytest.raises(ValidationError):
        CreateAssetRequest(name="Unsafe", kind="image", storage_key="../secret.txt")

    assets = AssetCatalog(tmp_path / "assets")
    characters = CharacterCatalog(tmp_path / "characters", assets)
    with pytest.raises(KeyError):
        characters.create(
            CreateCharacterRequest(
                name="Broken",
                prompt="test character",
                reference_asset_ids=["00000000-0000-0000-0000-000000000001"],
            )
        )


def test_template_catalog_and_prompt_builder_are_deterministic() -> None:
    catalog = TemplateCatalog(Path("templates"))
    template = catalog.get("tech-blog-v1")
    prompt = PromptBuilder.from_config(catalog.prompt_config("tech-blog-v1"))

    assert template.template_id == "tech-blog-v1"
    assert template.requires_human_approval_before_publish is True
    assert "clean vertical" in prompt.build(visual="a title card")

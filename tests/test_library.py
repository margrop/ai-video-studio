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
    updated = assets.write_bytes(asset.asset_id, b"<svg />", mime_type="image/svg+xml")
    assert updated.size_bytes == 7
    assert updated.mime_type == "image/svg+xml"
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
    assert template.version == 1
    assert template.brand_preset_id == "aivs-default-v1"
    assert template.requires_human_approval_before_publish is True
    assert "clean vertical" in prompt.build(visual="a title card")

    brand = catalog.brand_presets.get("aivs-default-v1")
    assert brand.version == 1
    assert "documentary" in brand.camera_prompt


def test_brand_preset_is_the_final_prompt_consistency_layer(tmp_path) -> None:
    root = tmp_path / "templates"
    (root / "brands").mkdir(parents=True)
    (root / "brands" / "custom-v2.json").write_text(
        '{"brand_preset_id":"custom-v2","name":"Custom","version":2,'
        '"prompt":{"base":"custom base","camera":"locked camera"}}',
        encoding="utf-8",
    )
    (root / "template.json").write_text(
        '{"template_id":"template","prompt":{"base":"template base","lighting":"template light"}}',
        encoding="utf-8",
    )
    catalog = TemplateCatalog(root)

    config = catalog.prompt_config("template", "custom-v2")
    assert config["base"] == "custom base"
    assert config["camera"] == "locked camera"
    assert config["lighting"] == "template light"

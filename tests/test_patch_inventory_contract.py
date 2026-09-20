import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
MANIFEST_PATH = ROOT / "docs" / "architecture" / "patch_inventory.json"
APP_INIT = APP_DIR / "__init__.py"

CANONICAL_REPLACEMENTS = {
    "app/vram_release_patch.py": "app/vram_controller.py",
    "app/sidebar_navigation_patch.py": "app/sidebar_controller.py",
    "app/image_studio_patch.py": "app/image_studio_controller.py",
    "app/shopping_search_patch.py": "app/web_research_pipeline.py",
    "app/bilingual_search_patch.py": "app/web_research_pipeline.py",
    "app/verified_fallback_patch.py": "app/web_research_pipeline.py",
    "app/price_evidence_patch.py": "app/evidence_policy.py",
    "app/answer_verifier_patch.py": "app/evidence_policy.py",
}


def _manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_patch_module_count_is_zero():
    manifest = _manifest()
    actual = tuple(
        sorted(
            path.relative_to(ROOT).as_posix()
            for path in APP_DIR.glob("*_patch.py")
        )
    )

    assert manifest["policy"] == "NO_PATCH_MODULES"
    assert manifest["active_patch_modules"] == []
    assert manifest["install_order"] == []
    assert actual == ()


def test_app_init_is_side_effect_free_and_has_no_patch_installers():
    source = APP_INIT.read_text(encoding="utf-8")

    assert "install_" not in source
    assert "_patch" not in source
    assert "MainWindow." not in source
    assert "workers." not in source
    assert "web_search_tool." not in source
    assert "evidence_verifier." not in source


def test_manifest_records_all_historical_replacements():
    manifest = _manifest()

    assert manifest["canonical_replacements"] == CANONICAL_REPLACEMENTS
    for replacement in set(CANONICAL_REPLACEMENTS.values()):
        assert (ROOT / replacement).is_file()


def test_zero_patch_inventory_documentation_is_explicit():
    text = (
        ROOT / "docs" / "architecture" / "PATCH_INVENTORY.md"
    ).read_text(encoding="utf-8")

    assert "NO PATCH MODULES" in text
    assert "Active patch modules: **0**" in text
    assert "Import-time patch installers" in text
    assert "VramController" in text
    assert "SidebarController" in text
    assert "ImageStudioController" in text
    assert "WebResearchPipeline" in text
    assert "EvidencePolicy" in text

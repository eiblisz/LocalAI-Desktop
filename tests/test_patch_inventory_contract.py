import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
MANIFEST_PATH = ROOT / "docs" / "architecture" / "patch_inventory.json"
APP_INIT = APP_DIR / "__init__.py"

FROZEN_PATCH_MODULES = (
    "app/answer_verifier_patch.py",
    "app/bilingual_search_patch.py",
    "app/image_studio_patch.py",
    "app/price_evidence_patch.py",
    "app/shopping_search_patch.py",
    "app/sidebar_navigation_patch.py",
    "app/verified_fallback_patch.py",
    "app/vram_release_patch.py",
)

EXPECTED_INSTALL_ORDER = (
    "install_shopping_search_patch",
    "install_price_evidence_patch",
    "install_answer_price_equivalence_patch",
    "install_verified_fallback_patch",
    "install_bilingual_search_patch",
    "install_vram_release_patch",
    "install_sidebar_navigation_patch",
    "install_image_studio_patch",
)


def _manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_no_new_patch_modules_beyond_frozen_baseline():
    manifest = _manifest()

    actual = tuple(
        sorted(
            path.relative_to(ROOT).as_posix()
            for path in APP_DIR.glob("*_patch.py")
        )
    )
    documented = tuple(
        sorted(entry["module"] for entry in manifest["install_order"])
    )

    assert manifest["policy"] == "NO_NEW_PATCH_MODULES"
    assert actual == FROZEN_PATCH_MODULES
    assert documented == FROZEN_PATCH_MODULES


def test_patch_inventory_has_complete_ordered_metadata():
    entries = _manifest()["install_order"]

    assert [entry["order"] for entry in entries] == list(
        range(1, len(entries) + 1)
    )
    assert [entry["installer"] for entry in entries] == list(
        EXPECTED_INSTALL_ORDER
    )

    for entry in entries:
        assert entry["target_module"].startswith("app.")
        assert entry["migration_target"]
        assert entry["purpose"]
        assert entry["mutations"]
        for mutation in entry["mutations"]:
            assert mutation["operation"] in {"add", "wrap", "replace"}
            assert mutation["symbol"]


def test_app_init_installs_inventory_in_documented_order():
    source = APP_INIT.read_text(encoding="utf-8")

    positions = []
    for installer in EXPECTED_INSTALL_ORDER:
        token = f"_{installer}("
        assert token in source
        positions.append(source.index(token))

    assert positions == sorted(positions)


def test_each_inventory_entry_matches_existing_patch_source():
    for entry in _manifest()["install_order"]:
        path = ROOT / entry["module"]
        source = path.read_text(encoding="utf-8")

        assert f"def {entry['installer']}(" in source

        for mutation in entry["mutations"]:
            leaf = mutation["symbol"].split(".")[-1]
            assert f".{leaf} =" in source


def test_inventory_documents_migration_not_new_patch_authority():
    text = (
        ROOT / "docs" / "architecture" / "PATCH_INVENTORY.md"
    ).read_text(encoding="utf-8")

    assert "NO NEW PATCH MODULES" in text
    assert "migration ledger" in text
    assert "No temporary replacement" in text

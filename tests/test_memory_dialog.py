import inspect

from app.memory_dialog import MemoryDialog


def test_memory_dialog_exposes_user_controlled_memory_actions():
    source = inspect.getsource(MemoryDialog._build_ui)

    assert 'QLabel("MEMORY")' in source
    assert 'QPushButton("SAVE REVISION")' in source
    assert 'QPushButton("PIN")' in source
    assert 'QPushButton("ARCHIVE")' in source
    assert 'QPushButton("DELETE")' in source
    assert 'QPushButton("REFRESH")' in source
    assert '"All history"' in source


def test_memory_dialog_revision_uses_canonical_store_revision_api():
    source = inspect.getsource(MemoryDialog._revise)

    assert "self.store.revise_memory(" in source
    assert 'source_type="memory_ui"' in source
    assert 'source_excerpt="Manual revision from Memory UI"' in source


def test_memory_dialog_renders_provenance_and_revision_chain():
    source = inspect.getsource(MemoryDialog._render_provenance)

    assert "self.store.list_memory_sources(memory_id)" in source
    assert "self.store.memory_lineage(memory_id)" in source
    assert "Revision chain" in source


def test_memory_dialog_pin_archive_delete_use_store_authority():
    pin_source = inspect.getsource(MemoryDialog._toggle_pin)
    archive_source = inspect.getsource(MemoryDialog._archive)
    delete_source = inspect.getsource(MemoryDialog._delete)

    assert "self.store.set_importance(" in pin_source
    assert "self.store.archive_memory(" in archive_source
    assert "self.store.delete_memory(" in delete_source

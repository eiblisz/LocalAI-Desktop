import inspect


def test_main_window_imports():
    from app.main_window import MainWindow

    assert MainWindow is not None


def test_chat_artifact_links_are_intercepted_not_navigated():
    from app.main_window import MainWindow

    build_source = inspect.getsource(MainWindow._build_chat_panel)
    render_source = inspect.getsource(MainWindow._render_chat)

    assert "setOpenLinks(False)" in build_source
    assert "setOpenExternalLinks(False)" in build_source
    assert "anchorClicked.connect(self._open_artifact_link)" in build_source
    assert "OPEN FILE" in render_source
    assert "artifact_url(path)" in render_source


def test_chat_render_uses_deferred_scroll_to_bottom():
    from app.main_window import MainWindow

    render_source = inspect.getsource(MainWindow._render_chat)
    schedule_source = inspect.getsource(MainWindow._schedule_scroll_to_bottom)

    assert "_schedule_scroll_to_bottom()" in render_source
    assert "QTimer.singleShot(0" in schedule_source
    assert "QTimer.singleShot(60" in schedule_source


def test_tool_panel_uses_shared_theme_lists():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._select_tool)
    assert "document_preset_labels()" in source
    assert "workbook_preset_labels()" in source

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


def test_schedule_button_and_scheduler_methods_are_wired():
    from app.main_window import MainWindow

    tools_source = inspect.getsource(MainWindow._build_tools_panel)
    check_source = inspect.getsource(MainWindow._check_scheduled_tasks)
    run_source = inspect.getsource(MainWindow._run_scheduled_task)

    assert 'QPushButton("SCHEDULE")' in tools_source
    assert "_open_scheduler" in tools_source
    assert "due_tasks()" in check_source
    assert "ScheduledTaskWorker" in run_source


def test_run_now_queues_when_localai_is_busy():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._run_scheduled_task)
    assert "pending_scheduled_task_id = task_id" in source
    assert "will start automatically" in source
    assert "set_run_status" in source


def test_pending_schedule_runs_after_worker_cleanup():
    from app.main_window import MainWindow

    chat_cleanup = inspect.getsource(MainWindow._cleanup_worker)
    doc_cleanup = inspect.getsource(MainWindow._cleanup_document_worker)
    pending = inspect.getsource(MainWindow._run_pending_scheduled_task)

    assert "_run_pending_scheduled_task" in chat_cleanup
    assert "_run_pending_scheduled_task" in doc_cleanup
    assert "_run_scheduled_task(task_id)" in pending

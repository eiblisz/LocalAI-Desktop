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

    sidebar_source = inspect.getsource(MainWindow._build_sidebar)
    tools_source = inspect.getsource(MainWindow._build_tools_panel)
    check_source = inspect.getsource(MainWindow._check_scheduled_tasks)
    run_source = inspect.getsource(MainWindow._run_scheduled_task)

    assert 'self.schedule_button = QPushButton("SCHEDULE")' in sidebar_source
    assert "_open_scheduler" in sidebar_source
    assert 'QPushButton("SCHEDULE")' not in tools_source
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


def test_schedule_button_stays_neutral_and_task_rows_carry_health():
    from app.main_window import MainWindow

    sidebar_source = inspect.getsource(MainWindow._build_sidebar)
    button_source = inspect.getsource(MainWindow._apply_schedule_button_style)
    task_source = inspect.getsource(MainWindow._refresh_schedule_task_labels)

    assert 'self.schedule_button = QPushButton("SCHEDULE")' in sidebar_source
    assert "background:#202730" in button_source
    assert "#315A43" not in button_source
    assert "#6A3035" not in button_source
    assert "#86C69A" in task_source
    assert "#E07A82" in task_source
    assert "RUNNING" in task_source
    assert "DISABLED" in task_source

def test_schedule_button_refreshes_after_task_results():
    from app.main_window import MainWindow

    success_source = inspect.getsource(MainWindow._scheduled_task_finished)
    failure_source = inspect.getsource(MainWindow._scheduled_task_failed)
    cleanup_source = inspect.getsource(MainWindow._cleanup_scheduled_worker)

    assert "_refresh_schedule_indicator()" in success_source
    assert "_refresh_schedule_indicator()" in failure_source
    assert "_refresh_schedule_indicator()" in cleanup_source


def test_sidebar_lists_only_saved_tasks_not_predeclared_categories():
    from app.main_window import MainWindow

    sidebar = inspect.getsource(MainWindow._build_sidebar)
    refresh = inspect.getsource(MainWindow._refresh_schedule_task_labels)

    assert "schedule_task_status_layout" in sidebar
    assert '("weather", "Weather")' not in sidebar
    assert '("ebay", "eBay Search")' not in sidebar
    assert '("computer", "Computer")' not in sidebar
    assert '("custom", "Custom")' not in sidebar
    assert "for task in tasks" in refresh
    assert 'task.get("name", "Scheduled task")' in refresh



def test_normal_chat_has_web_auto_and_manual_web_toggle():
    from app.main_window import MainWindow

    build = inspect.getsource(MainWindow._build_chat_panel)
    send = inspect.getsource(MainWindow._send)

    assert 'QPushButton("WEB AUTO")' in build
    assert "setCheckable(True)" in build
    assert "self.web_button.isChecked()" in send
    assert "_looks_like_web_request(text)" in send
    assert "ChatWebWorker" in send


def test_web_auto_detects_explicit_search_intent():
    from app.main_window import MainWindow

    assert MainWindow._looks_like_web_request(
        None,
        "Keress ra milyen 32 GB-os videokartyak vannak most",
    )
    assert MainWindow._looks_like_web_request(
        None,
        "Nezz utana online a legfrissebb Qwen modellnek",
    )
    assert MainWindow._looks_like_web_request(
        None,
        "search the web for current Ollama news",
    )
    assert not MainWindow._looks_like_web_request(
        None,
        "Irj egy rovid verset az oszrol",
    )


def test_web_chat_failure_gets_distinct_status():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._on_failed)
    assert "Web research error" in source
    assert "Web research failed" in source


def test_chat_tokens_buffer_without_live_rendering():
    from app.main_window import MainWindow

    token_source = inspect.getsource(MainWindow._on_token)

    assert "self.partial_assistant += token" in token_source
    assert "_render_chat" not in token_source
    assert "stream_render_timer" not in token_source

def test_chat_uses_pulsing_thinking_indicator_until_complete():
    from app.main_window import MainWindow

    build_source = inspect.getsource(MainWindow._build_chat_panel)
    send_source = inspect.getsource(MainWindow._send)
    start_source = inspect.getsource(MainWindow._start_thinking_indicator)
    pulse_source = inspect.getsource(MainWindow._pulse_thinking_indicator)
    finished_source = inspect.getsource(MainWindow._on_finished)
    failed_source = inspect.getsource(MainWindow._on_failed)
    stop_source = inspect.getsource(MainWindow._stop_generation)

    assert 'self.thinking_label = QLabel("")' in build_source
    assert "setFixedHeight(26)" in build_source
    assert "_start_thinking_indicator(use_web)" in send_source
    assert '"Gondolkodik"' in start_source
    assert '"Keres es gondolkodik"' in start_source
    assert "thinking_timer.start()" in start_source
    assert "thinking_phase" in pulse_source
    assert "_stop_thinking_indicator()" in finished_source
    assert "_stop_thinking_indicator()" in failed_source
    assert "_stop_thinking_indicator()" in stop_source

def test_web_auto_detects_shopping_price_requests_without_search_verbs():
    from app.main_window import MainWindow

    assert MainWindow._looks_like_web_request(
        None,
        "2x32GB DDR4 1000 EUR alatt",
    )
    assert MainWindow._looks_like_web_request(
        None,
        "64GB DDR4 mennyiert kaphato most",
    )
    assert MainWindow._looks_like_web_request(
        None,
        "RTX 5090 current price Germany",
    )


def test_chat_link_handler_opens_http_links_externally():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._open_artifact_link)
    assert 'url.scheme().lower() in {"http", "https"}' in source
    assert "webbrowser.open" in source
    assert "path_from_artifact_url" in source


def test_chat_view_wraps_long_urls_without_horizontal_growth():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_chat_panel)

    assert "setMinimumWidth(0)" in source
    assert "ScrollBarAlwaysOff" in source
    assert "LineWrapMode.WidgetWidth" in source
    assert "WrapAtWordBoundaryOrAnywhere" in source
    assert "setDefaultTextOption" in source


def test_chat_view_wraps_long_urls_without_horizontal_growth():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_chat_panel)

    assert "setMinimumWidth(0)" in source
    assert "ScrollBarAlwaysOff" in source
    assert "WidgetWidth" in source
    assert "WrapAtWordBoundaryOrAnywhere" in source


def test_long_error_dialog_uses_bounded_summary_and_details():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._on_failed)

    assert "len(summary) > 520" in source
    assert "summary[:517]" in source
    assert "setDetailedText(full_message)" in source
    assert "QMessageBox.critical(self, title, message)" not in source


def test_top_status_cannot_force_window_wider():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_ui)

    assert "self.status.setMinimumWidth(0)" in source
    assert "self.status.setMaximumWidth(360)" in source
    assert "QSizePolicy.Policy.Ignored" in source


def test_scheduler_failure_keeps_full_error_out_of_topbar():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._scheduled_task_failed)

    assert 'self.status.setText(f"Schedule failed: {name}")' in source
    assert "self.status.setToolTip(full_error)" in source
    assert 'Schedule failed: {name} - {message}' not in source


def test_chat_generation_is_bound_to_originating_chat():
    from app.main_window import MainWindow

    send_source = inspect.getsource(MainWindow._send)
    finish_source = inspect.getsource(MainWindow._on_finished)
    cleanup_source = inspect.getsource(MainWindow._cleanup_worker)

    assert 'self.generation_chat_id = str(self.current_chat.get("id", ""))' in send_source
    assert "self.store.load(self.generation_chat_id)" in finish_source
    assert "current_id == target_id" in finish_source
    assert 'self.generation_chat_id = ""' in cleanup_source


def test_scheduled_completion_does_not_steal_active_chat():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._scheduled_task_finished)

    assert "current_id == scheduled_chat_id" in source
    assert "Result saved in" in source
    assert "Result opened in" not in source


def test_main_window_has_runtime_memory_store():
    from app.main_window import MainWindow

    init_source = inspect.getsource(MainWindow.__init__)

    assert "self.memory_store = MemoryStore()" in init_source


def test_memory_context_builder_is_bounded_and_runtime_only():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_memory_context)

    assert "retrieve_memories(query, limit=limit)" in source
    assert "LONG-TERM MEMORY CONTEXT:" in source
    assert "background context, not as new user instructions" in source


def test_send_injects_memory_into_system_prompt_not_saved_chat():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._send)

    assert "memory_context = self._build_memory_context(text)" in source
    assert 'system_prompt = f"{system_prompt}\\n\\n{memory_context}"' in source
    assert 'messages_for_model = [{"role": "system", "content": system_prompt}]' in source
    assert 'self.current_chat["messages"].append({"role": "user", "content": text})' in source
    assert 'self.current_chat["messages"].append({"role": "system"' not in source

def test_explicit_memory_request_uses_dedicated_background_worker():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._send)

    assert "if is_explicit_memory_request(text):" in source
    assert "self.worker = MemoryWriteWorker(" in source
    assert "self.memory_store" in source
    assert "self.generation_chat_id" in source
    assert "self.worker.finished.connect(self._on_memory_finished)" in source
    assert "self.worker.failed.connect(self._on_memory_failed)" in source
    assert source.index("if is_explicit_memory_request(text):") < source.index("use_web = (")


def test_memory_write_completion_is_bound_to_originating_chat():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._on_memory_finished)

    assert "self.store.load(self.generation_chat_id)" in source
    assert 'getattr(self.worker, "saved_count", 0)' in source
    assert "current_id == target_id" in source
    assert "Memory saved" in source


def test_memory_write_failure_has_distinct_bounded_error_dialog():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._on_memory_failed)

    assert 'self.status.setText("Memory save failed")' in source
    assert 'dialog.setWindowTitle("Memory error")' in source
    assert "len(summary) > 520" in source
    assert "setDetailedText(full_message)" in source


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
    assert "plan_user_action(" in send
    assert "ACTION_WEB_RESEARCH" in send
    assert "ChatWebWorker" in send
    assert "AdaptiveChatWorker" in send


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


def test_chat_link_handler_routes_http_and_artifacts_to_internal_viewer():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._open_artifact_link)
    assert 'url.scheme().lower() in {"http", "https"}' in source
    assert "self._open_resource(url.toString())" in source
    assert "path_from_artifact_url" in source
    assert "self._open_resource(target)" in source
    assert "webbrowser.open" not in source


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

    assert "plan_user_action(" in source
    assert "action_plan.has(ACTION_MEMORY_WRITE)" in source
    assert "self.worker = MemoryWriteWorker(" in source
    assert "self.memory_store" in source
    assert "self.generation_chat_id" in source
    assert "self.worker.finished.connect(self._on_memory_finished)" in source
    assert "self.worker.failed.connect(self._on_memory_failed)" in source
    assert source.index("action_plan.has(ACTION_MEMORY_WRITE)") < source.index(
        "use_web = action_plan.has(ACTION_WEB_RESEARCH)"
    )


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

def test_memory_context_explains_relationship_semantics():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_memory_context)

    assert "relationship_to_user" in source
    assert "literal relationship" in source
    assert "answer direct relationship questions" in source

def test_memory_context_renders_personal_facts_as_plain_semantics():
    from types import SimpleNamespace
    from app.main_window import MainWindow

    class Store:
        def retrieve_memories(self, query, limit=8):
            return [
                {
                    "category": "USER_PROFILE",
                    "subject": "USER",
                    "key": "name",
                    "value": "Iblisz",
                },
                {
                    "category": "USER_PROFILE",
                    "subject": "Lilla",
                    "key": "relationship_to_user",
                    "value": "daughter",
                },
            ]

    host = SimpleNamespace(memory_store=Store())
    context = MainWindow._build_memory_context(host, "Ki Iblisz es ki Lilla?")

    assert "the user's name is Iblisz" in context
    assert "Lilla is the user's daughter" in context

def test_memory_context_marks_persistent_facts_as_durable_authority():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_memory_context)

    assert "durable user-approved facts loaded from persistent memory" in source
    assert "Do not describe a matching memory as being only part of the current conversation" in source
    assert "answer the fact directly" in source

def test_memory_context_enforces_user_second_person_perspective():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_memory_context)

    assert "you are the assistant, and USER refers to the human user" in source
    assert "Never adopt USER profile facts as your own identity or relationships" in source
    assert "express USER self/profile facts in second person" in source
    assert "Your name is Iblisz" in source
    assert "Lilla is your daughter" in source
    assert "My name is Iblisz" in source
    assert "Lilla is my daughter" in source

def test_direct_personal_memory_answers_bypass_model_generation():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._send)

    assert "direct_memory_answer = self._direct_user_memory_answer(text)" in source
    assert '{"role": "assistant", "content": direct_memory_answer}' in source
    assert 'self.status.setText("Memory answer")' in source

    direct_index = source.index(
        "direct_memory_answer = self._direct_user_memory_answer(text)"
    )
    worker_index = source.index("self.thread = QThread()", direct_index)
    assert direct_index < worker_index


def test_direct_user_memory_answer_reads_only_active_user_profile_memories():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._direct_user_memory_answer)

    assert 'scope="USER"' in source
    assert 'category="USER_PROFILE"' in source
    assert 'statuses=("active",)' in source
    assert "include_session_only=False" in source
    assert "direct_user_memory_answer(query, memories)" in source


def test_memory_context_marks_person_relations_as_not_user_relations():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_memory_context)

    assert 'normalized_key.endswith("_of")' in source
    assert "Durable person fact" in source
    assert "relationship between two people, not a relationship to the user" in source


def test_normal_chat_system_prompt_enforces_current_user_language():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._send)

    assert "response_language_instruction(text)" in source
    assert (
        'f"{DEFAULT_SYSTEM_PROMPT}\\n\\n{response_language_instruction(text)}"'
        in source
    )
    assert source.index("response_language_instruction(text)") < source.index(
        "messages_for_model ="
    )


def test_web_auto_detects_inflected_hungarian_search_command():
    from app.main_window import MainWindow

    assert MainWindow._looks_like_web_request(
        None,
        "Keressel nekem 4tb-os ssd merevlemezt",
    )


def test_extensions_dialog_is_wired_but_not_injected_into_chat_runtime():
    from app.main_window import MainWindow

    init_source = inspect.getsource(MainWindow.__init__)
    open_source = inspect.getsource(MainWindow._open_extensions)
    send_source = inspect.getsource(MainWindow._send)

    assert "self.extension_store = ExtensionStore()" in init_source
    assert "self.extensions_dialog = None" in init_source
    assert "ExtensionsDialog(" in open_source
    assert "self.extension_store" in open_source
    assert "_crypto_market_extension" in send_source
    assert "extensions_dialog" not in send_source


def test_chat_panel_exposes_extension_attachment_button():
    from app.main_window import MainWindow

    build = inspect.getsource(MainWindow._build_chat_panel)
    open_source = inspect.getsource(MainWindow._open_chat_extensions)
    refresh_source = inspect.getsource(MainWindow._refresh_chat_extensions_button)

    assert 'self.chat_extensions_button = QPushButton("EXT 0")' in build
    assert "ChatExtensionsDialog(" in open_source
    assert "dialog.saved.connect(self._chat_extensions_saved)" in open_source
    assert 'button.setText(f"EXT {count}")' in refresh_source
    assert "runtime execution is not enabled yet" in refresh_source.lower()


def test_chat_extension_attachments_are_not_injected_into_model_runtime_yet():
    from app.main_window import MainWindow

    send_source = inspect.getsource(MainWindow._send)

    assert "attached_extensions" not in send_source
    assert "ChatExtensionsDialog" not in send_source


def test_chat_render_refreshes_extension_attachment_badge():
    from app.main_window import MainWindow

    render_source = inspect.getsource(MainWindow._render_chat)

    assert "self._refresh_chat_extensions_button()" in render_source


def test_prometheusz_bridge_starts_only_from_enabled_configured_extension():
    from app.main_window import MainWindow

    sync = inspect.getsource(MainWindow._sync_discord_bot_bridge)
    open_source = inspect.getsource(MainWindow._open_extensions)
    close_source = inspect.getsource(MainWindow.closeEvent)

    assert 'find_by_preset_id("discord-bot")' in inspect.getsource(MainWindow._discord_bot_extension)
    assert 'not bool(extension.get("enabled", False))' in sync
    assert "self.secret_store.get_secret" in sync
    assert "DiscordBotSettings.from_extension" in sync
    assert "DiscordBotBridge(" in sync
    assert "memory_store=self.memory_store" in sync
    assert "self.extensions_dialog.changed.connect(self._sync_discord_bot_bridge)" in open_source
    assert "self._stop_discord_bot_bridge()" in close_source


def test_prometheusz_remote_bridge_does_not_add_shell_execution_to_main_chat():
    from app.main_window import MainWindow

    sync = inspect.getsource(MainWindow._sync_discord_bot_bridge)
    send = inspect.getsource(MainWindow._send)

    assert "subprocess" not in sync
    assert "os.system" not in sync
    assert "subprocess" not in send
    assert "os.system" not in send


def test_desktop_artifact_tools_use_shared_artifact_service():
    from app.main_window import MainWindow

    creator = inspect.getsource(MainWindow._artifact_creator)
    create_selected = inspect.getsource(MainWindow._create_selected_tool)
    ready = inspect.getsource(MainWindow._on_document_ready)

    assert "create_artifact(" in creator
    assert 'create_artifact(\n                        "xlsx"' in create_selected
    assert 'create_artifact(\n                    "xlsx"' in ready
    assert "create_pdf(" not in creator
    assert "create_docx(" not in creator
    assert "create_html(" not in creator


def test_shared_action_plan_routes_memory_web_artifact_and_stable_chat():
    from app.web_intent import (
        ACTION_ARTIFACT,
        ACTION_CHAT,
        ACTION_MEMORY_WRITE,
        ACTION_WEB_RESEARCH,
        plan_user_action,
    )

    memory = plan_user_action("Jegyezd meg, hogy Lilla a lányom.")
    assert memory.has(ACTION_MEMORY_WRITE)

    current = plan_user_action("Melyik a jelenlegi legfrissebb Qwen verzió?")
    assert current.has(ACTION_WEB_RESEARCH)

    stable = plan_user_action("Magyarázd el röviden, mi az a TCP.")
    assert stable.has(ACTION_CHAT)
    assert not stable.has(ACTION_WEB_RESEARCH)

    artifact = plan_user_action(
        "Keress friss SSD árakat és készíts belőle Excel fájlt."
    )
    assert artifact.has(ACTION_WEB_RESEARCH)
    assert artifact.has(ACTION_ARTIFACT)
    assert artifact.artifact_plans[0].request.format == "xlsx"


def test_auto_web_fallback_policy_is_bounded_to_stale_or_missing_knowledge():
    from app.web_intent import answer_requires_web_fallback

    assert answer_requires_web_fallback(
        "Melyik modell a legújabb?",
        "Nincs friss információm erről a modellről.",
    )
    assert not answer_requires_web_fallback(
        "Mi az a TCP?",
        "A TCP egy kapcsolatorientált hálózati protokoll.",
    )
    assert not answer_requires_web_fallback(
        "Írj egy rövid verset.",
        "Nem vagyok biztos benne, milyen stílust szeretnél.",
    )


def test_freshness_sensitive_requests_route_to_web_without_search_verb():
    from app.web_intent import is_freshness_sensitive_request

    assert is_freshness_sensitive_request("Melyik a jelenlegi Ollama verzió?")
    assert is_freshness_sensitive_request("Mennyi most egy 4 TB SSD ára?")
    assert is_freshness_sensitive_request("What is the latest Qwen release?")
    assert not is_freshness_sensitive_request("Mi az a neurális háló?")
    assert not is_freshness_sensitive_request("Magyarázd el röviden, mi az a TCP.")
    assert not is_freshness_sensitive_request("Készíts rövid témaleírást.")


def test_numbered_multi_action_message_plans_each_task_independently():
    from app.web_intent import (
        ACTION_ARTIFACT,
        ACTION_CHAT,
        ACTION_WEB_RESEARCH,
        plan_user_actions,
    )

    prompt = """1. Melyik a jelenlegi legfrissebb Qwen verzió?

2. Magyarázd el röviden, mi az a TCP.

3. Mi a legújabb Ollama verzió, és készíts róla egy rövid HTML riportot."""

    planned = plan_user_actions(prompt)

    assert len(planned) == 3

    assert planned[0].plan.has(ACTION_WEB_RESEARCH)
    assert not planned[0].plan.has(ACTION_ARTIFACT)

    assert planned[1].plan.has(ACTION_CHAT)
    assert not planned[1].plan.has(ACTION_WEB_RESEARCH)

    assert planned[2].plan.has(ACTION_WEB_RESEARCH)
    assert planned[2].plan.has(ACTION_ARTIFACT)
    assert planned[2].plan.artifact_plans[0].request.format == "html"


def test_compound_web_to_artifact_workflow_stays_one_action_unit():
    from app.web_intent import plan_user_actions

    planned = plan_user_actions(
        "Mi a legújabb Ollama verzió, és készíts róla egy rövid HTML riportot."
    )

    assert len(planned) == 1
    assert planned[0].prompt.startswith("Mi a legújabb Ollama")


def test_live_market_price_questions_route_to_web():
    from app.web_intent import (
        ACTION_WEB_RESEARCH,
        is_freshness_sensitive_request,
        plan_user_action,
    )

    prompts = [
        "Mennyi most a bitcoin árfolyama?",
        "Mi a bitcoin árfolyama?",
        "Mennyi most az ETH arfolyama?",
        "Mi a Tesla részvény piaci ára most?",
        "What is the current BTC market price?",
        "What is the EUR USD exchange rate?",
        "Wie hoch ist der Bitcoin Kurs aktuell?",
    ]

    for prompt in prompts:
        assert is_freshness_sensitive_request(prompt)
        assert plan_user_action(prompt).has(ACTION_WEB_RESEARCH)


def test_market_price_routing_does_not_capture_stable_explanations():
    from app.web_intent import (
        ACTION_WEB_RESEARCH,
        plan_user_action,
    )

    stable_prompts = [
        "Mi az a bitcoin?",
        "Magyarázd el, mi az az árfolyam.",
        "Mi a különbség a spot és futures piac között?",
        "What is an exchange rate?",
    ]

    for prompt in stable_prompts:
        assert not plan_user_action(prompt).has(ACTION_WEB_RESEARCH)


def test_realtime_access_refusal_triggers_grounded_web_fallback():
    from app.web_intent import answer_requires_web_fallback

    assert answer_requires_web_fallback(
        "Mennyi most a bitcoin árfolyama?",
        (
            "Ha konkrét árat szeretnél, kérlek nézd meg közvetlenül, "
            "mivel én nem tudok valós időben hozzáférni a kriptovaluta piaci adatokhoz."
        ),
    )


def test_live_crypto_quotes_prefer_enabled_market_data_extension():
    from app.main_window import MainWindow

    send_source = inspect.getsource(MainWindow._send)
    helper_source = inspect.getsource(MainWindow._crypto_market_extension)

    assert 'find_by_preset_id("crypto-market-data")' in helper_source
    assert '"crypto_quote"' in helper_source
    assert "is_crypto_quote_request(text_for_model)" in send_source
    assert "MarketDataWorker(" in send_source
    assert "ChatWebWorker(" in send_source
    assert send_source.index("MarketDataWorker(") < send_source.index("ChatWebWorker(")


def test_discord_bridge_receives_shared_extension_store_for_market_runtime():
    from app.main_window import MainWindow

    sync_source = inspect.getsource(MainWindow._sync_discord_bot_bridge)

    assert "extension_store=self.extension_store" in sync_source


def test_workspace_hosts_chat_and_closeable_internal_resource_tabs():
    from app.main_window import MainWindow

    build_source = inspect.getsource(MainWindow._build_workspace_panel)
    close_source = inspect.getsource(MainWindow._close_workspace_tab)

    assert "QTabWidget()" in build_source
    assert "setTabsClosable(True)" in build_source
    assert "setMovable(True)" in build_source
    assert "self._build_chat_panel()" in build_source
    assert 'addTab(self.chat_workspace, "Chat")' in build_source
    assert "widget is self.chat_workspace" in close_source
    assert "removeTab(index)" in close_source


def test_open_resource_creates_internal_tab_and_keeps_browser_navigation_internal():
    from app.main_window import MainWindow

    open_source = inspect.getsource(MainWindow._open_resource)

    assert "resource_identity(target)" in open_source
    assert 'existing.property("resource_target") == resource_key' in open_source
    assert 'widget.setProperty("resource_target", resource_key)' in open_source
    assert "create_resource_view(" in open_source
    assert "open_resource=self._open_resource" in open_source
    assert "self.workspace_tabs.addTab" in open_source
    assert "self.workspace_tabs.setCurrentIndex" in open_source
    assert "BrowserView" in open_source


def test_open_file_button_uses_internal_resource_viewer():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._open_last_artifact)

    assert "self._open_resource(self.last_artifact_path)" in source
    assert "open_file(" not in source



def test_tradingview_workspace_uses_enabled_extension_config_or_safe_default():
    from app.main_window import MainWindow

    url_source = inspect.getsource(MainWindow._tradingview_workspace_url)
    open_source = inspect.getsource(MainWindow._open_market_browser)

    assert '"https://www.tradingview.com/markets/"' in url_source
    assert 'find_by_preset_id(' in url_source
    assert '"tradingview-workspace"' in url_source
    assert 'extension.get("enabled", False)' in url_source
    assert 'config.get("workspace_url")' in url_source
    assert 'value.startswith(("https://", "http://"))' in url_source
    assert "self._open_resource(self._tradingview_workspace_url())" in open_source


def test_live_stock_forex_and_index_quotes_prefer_multi_asset_extension():
    from app.main_window import MainWindow

    send_source = inspect.getsource(MainWindow._send)
    helper_source = inspect.getsource(MainWindow._multi_asset_market_extension)

    assert 'find_by_preset_id(' in helper_source
    assert '"multi-asset-market-data"' in helper_source
    assert '"market_quote"' in helper_source
    assert "is_multi_asset_quote_request(text_for_model)" in send_source
    assert "MultiAssetMarketDataWorker(" in send_source
    assert "ChatWebWorker(" in send_source
    assert send_source.index("MultiAssetMarketDataWorker(") < send_source.index(
        "ChatWebWorker("
    )


def test_crypto_and_multi_asset_structured_routing_remain_separate():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._send)

    assert "is_crypto_quote_request(text_for_model)" in source
    assert "is_multi_asset_quote_request(text_for_model)" in source
    assert "MarketDataWorker(" in source
    assert "MultiAssetMarketDataWorker(" in source


def test_chat_input_accepts_clipboard_images_as_ollama_image_payloads():
    from app.main_window import MainWindow, PasteAwareTextEdit

    build_source = inspect.getsource(MainWindow._build_chat_panel)
    send_source = inspect.getsource(MainWindow._send)
    paste_source = inspect.getsource(PasteAwareTextEdit.insertFromMimeData)
    attach_source = inspect.getsource(MainWindow._attach_clipboard_image)

    assert "PasteAwareTextEdit()" in build_source
    assert "imagePasted.connect(self._attach_clipboard_image)" in build_source
    assert "source.hasImage()" in paste_source
    assert "self.imagePasted.emit(image)" in paste_source
    assert "_qimage_to_png_base64(image)" in attach_source
    assert 'attachment.get("kind") == "image"' in send_source
    assert 'model_user_message["images"] = image_payloads' in send_source


def test_attach_file_supports_common_image_formats():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._attach_file)

    for suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        assert suffix in source
    assert "base64.b64encode" in source
    assert "self._add_image_attachment" in source


def test_local_model_hub_lists_all_ollama_models_and_supports_refresh():
    from app.main_window import MainWindow

    build_source = inspect.getsource(MainWindow._build_ui)
    load_source = inspect.getsource(MainWindow._refresh_local_model_hub)
    changed_source = inspect.getsource(MainWindow._model_changed)

    assert 'QLabel("LOCAL MODELS")' in build_source
    assert "self.model_combo.setMinimumWidth(300)" in build_source
    assert "self.model_combo.setMaxVisibleItems(24)" in build_source
    assert 'QPushButton("REFRESH")' in build_source
    assert "self.refresh_models_button.clicked.connect(self._load_models)" in build_source

    assert "self.client.list_models()" in load_source
    assert "self.model_combo.addItems(models)" in load_source
    assert 'self.model_label.setText(' in load_source
    assert "LOCAL MODELS (" in load_source
    assert "self.model_count_label.setText(str(len(models)))" in load_source
    assert "sorted(" in load_source

    assert 'self.current_chat["model"] = model' in changed_source
    assert 'self.status.setText(f"Model: {model}")' in changed_source


def test_model_refresh_preserves_saved_or_current_chat_model():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._refresh_local_model_hub)

    assert 'saved = str(self.current_chat.get("model") or "").strip()' in source
    assert "preferred = saved or previous" in source
    assert "self.model_combo.findText(preferred)" in source
    assert "self.model_combo.setCurrentIndex(index)" in source


def test_topbar_model_controls_share_one_compact_baseline():
    import app.main_window as main_window_module
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._build_ui)

    assert "model_box = QVBoxLayout()" not in source
    assert "model_header = QHBoxLayout()" not in source
    assert "self.model_combo.setFixedHeight(34)" in source
    assert "self.refresh_models_button.setFixedHeight(34)" in source
    assert "Qt.AlignmentFlag.AlignVCenter" in source
    assert "top_layout.setContentsMargins(18, 6, 18, 6)" in source
    assert "max-height: 34px" in main_window_module.STYLE


def test_schedule_style_no_longer_reintroduces_large_button_height():
    from app.main_window import MainWindow

    source = inspect.getsource(MainWindow._apply_schedule_button_style)

    assert '"padding:5px 10px;"' in source
    assert '"min-height:32px;"' in source
    assert '"max-height:34px;"' in source
    assert "self.schedule_button.setFixedHeight(34)" in source
    assert '"min-height:44px;"' not in source

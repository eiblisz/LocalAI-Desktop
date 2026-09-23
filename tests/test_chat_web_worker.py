from app import workers


class DummyWebClient:
    def __init__(self):
        self.once_calls = []
        self.stream_calls = []

    def chat_once(self, model, messages, timeout=600.0):
        self.once_calls.append((model, messages))
        return "Qwen local AI latest news"

    def chat_stream(
        self,
        model,
        messages,
        on_token,
        should_stop,
        timeout=600.0,
    ):
        self.stream_calls.append((model, messages))
        if not should_stop():
            on_token("Grounded web answer.")


def test_chat_web_worker_searches_streams_and_keeps_sources_structured(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=8, fetch_pages=True: {
            "provider": "Bing Web RSS",
            "query": query,
            "results": [{
                "title": "Qwen update",
                "url": "https://example.com/qwen",
                "snippet": "Fresh Qwen local AI news",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/qwen"],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA\nQwen update",
    )

    client = DummyWebClient()
    tokens = []
    failed = []
    finished = []

    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "Keress ra a legfrissebb Qwen hirekre"},
        ],
        "Keress ra a legfrissebb Qwen hirekre",
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()

    assert not failed
    assert finished == [True]
    assert client.once_calls
    assert client.stream_calls

    streamed_messages = client.stream_calls[0][1]
    assert "use ONLY the AUTHORIZED WEB TOOL DATA" in streamed_messages[1]["content"]
    assert "AUTHORIZED WEB TOOL DATA" in streamed_messages[-1]["content"]

    combined = "".join(tokens)
    assert "Grounded web answer." in combined
    assert "Search query:" not in combined
    assert "Search provider:" not in combined
    assert worker.source_metadata == [{
        "title": "Qwen update",
        "url": "https://example.com/qwen",
    }]
    assert worker.diagnostic_metadata["search_queries"] == [
        "Qwen local AI latest news"
    ]


def test_chat_web_worker_fails_closed_without_sources(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=8, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [],
        },
    )
    monkeypatch.setattr(workers, "source_urls", lambda payload: [])
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "",
    )

    client = DummyWebClient()
    failed = []

    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress nekem valamit az interneten",
    )
    worker.failed.connect(failed.append)
    worker.run()

    assert failed
    assert "no usable public sources" in failed[0].lower()
    assert not client.stream_calls


def test_chat_web_worker_stop_prevents_source_footer(monkeypatch):
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=8, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "Result",
                "url": "https://example.com/result",
                "snippet": "Result",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/result"],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA",
    )

    client = DummyWebClient()
    tokens = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Search the web",
    )
    worker.token.connect(tokens.append)
    worker.stop()
    worker.run()

    assert "Web results / sources:" not in "".join(tokens)


def test_punctuation_only_web_input_never_calls_search_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda *args, **kwargs: calls.append(args) or (_ for _ in ()).throw(
            AssertionError("invalid input must not reach a provider")
        ),
    )

    tokens = []
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "?",
    )
    worker.token.connect(tokens.append)
    worker.run()

    assert calls == []
    assert "context" in "".join(tokens).lower()


def test_contextual_followup_uses_previous_turn_not_literal_punctuation(monkeypatch):
    seen = []
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["Arany János Toldi date written"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: seen.append(query) or {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "Toldi",
                "url": "https://example.com/toldi",
                "snippet": "Arany János 1846",
            }],
        },
    )
    monkeypatch.setattr(workers, "source_urls", lambda payload: ["https://example.com/toldi"])
    monkeypatch.setattr(workers, "web_search_context_text", lambda payload: "Arany János 1846")

    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [
            {"role": "user", "content": "Mikor írta Arany János a Toldit?"},
            {"role": "assistant", "content": "1846-ban írta."},
            {"role": "user", "content": "?"},
        ],
        "?",
    )
    worker.run()

    assert seen == ["Arany János Toldi date written"]
    assert worker.followup_resolution.status == "resolved"


def test_query_generator_prose_is_repaired_before_provider_call(monkeypatch):
    seen = []
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["You should search for the user's request about Gemma."],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: seen.append(query) or {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "Gemma",
                "url": "https://example.com/gemma",
                "snippet": "Gemma4 release",
            }],
        },
    )
    monkeypatch.setattr(workers, "source_urls", lambda payload: ["https://example.com/gemma"])
    monkeypatch.setattr(workers, "web_search_context_text", lambda payload: "Gemma4 release")

    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Melyik a legfrissebb Gemma4 modell?",
    )
    worker.run()

    assert worker.query_validation["status"] == "bounded_repair"
    assert seen == ["Melyik a legfrissebb Gemma4 modell?"]


def test_chat_web_worker_runs_separate_searches_for_multi_part_request(monkeypatch):
    class MultiQueryClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            return (
                "32GB GPU graphics cards current models\n"
                "latest Qwen model release\n"
                "64GB DDR4 2x32 current prices Germany"
            )

    seen = []

    def fake_search(query, max_results=6, fetch_pages=True):
        seen.append(query)
        slug = str(len(seen))
        return {
            "provider": "test",
            "query": query,
            "results": [{
                "title": f"Relevant result {slug}",
                "url": f"https://example.com/{slug}",
                "snippet": query,
            }],
        }

    monkeypatch.setattr(workers, "search_web", fake_search)
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: [payload["results"][0]["url"]],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: payload["results"][0]["snippet"],
    )

    client = MultiQueryClient()
    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        (
            "Keress 32 GB-os videokartyakat.\n"
            "Nezd meg a legfrissebb Qwen modellt.\n"
            "Keress 64 GB DDR4 RAM-ot."
        ),
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    assert seen == [
        "32GB GPU graphics cards current models",
        "latest Qwen model release",
        "64GB DDR4 2x32 current prices Germany",
    ]
    combined = "".join(tokens)
    assert "Search queries:" not in combined
    assert len(worker.source_metadata) == 3
    assert worker.diagnostic_metadata["search_queries"] == seen


def test_chat_web_worker_keeps_result_links_in_structured_sources(monkeypatch):
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["64GB DDR4 2x32 Germany price"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "Kingston 64GB DDR4 kit",
                "url": "https://shop.example/kingston-64gb",
                "snippet": "2x32GB DDR4 kit EUR 149",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://shop.example/kingston-64gb"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=10: [{
            "title": "Kingston 64GB DDR4 kit",
            "url": "https://shop.example/kingston-64gb",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA",
    )

    client = DummyWebClient()
    tokens = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "2x32GB DDR4 1000 EUR alatt",
    )
    worker.token.connect(tokens.append)
    worker.run()

    combined = "".join(tokens)
    assert "Web results / sources:" not in combined
    assert worker.source_metadata == [{
        "title": "Kingston 64GB DDR4 kit",
        "url": "https://shop.example/kingston-64gb",
    }]


def test_search_again_uses_previous_user_request_context(monkeypatch):
    class FollowupClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            system = messages[0]["content"]
            user = messages[1]["content"]

            assert "follow-up asking to search again" in system
            assert "PREVIOUS USER REQUEST" in user
            assert "2x32GB DDR4 1000 EUR alatt" in user
            assert "CURRENT USER REQUEST" in user
            assert "most keress ra ujra" in user
            return "2x32GB DDR4 Germany under 1000 EUR"

    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "64GB DDR4 kit",
                "url": "https://example.com/ram",
                "snippet": "2x32GB DDR4 kit EUR 150",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/ram"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=10: [{
            "title": "64GB DDR4 kit",
            "url": "https://example.com/ram",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA",
    )

    client = FollowupClient()
    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "2x32GB DDR4 1000 EUR alatt"},
            {"role": "assistant", "content": "Previous answer"},
            {"role": "user", "content": "most keress ra ujra"},
        ],
        "most keress ra ujra",
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    assert "Search query:" not in "".join(tokens)
    assert worker.diagnostic_metadata["search_queries"] == [
        "2x32GB DDR4 Germany under 1000 EUR"
    ]


def test_literal_search_again_query_is_rejected_and_falls_back_to_previous_request():
    class BadFollowupClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            return "Keressel Ra Ujra plot summary"

    worker = workers.ChatWebWorker(
        BadFollowupClient(),
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "64GB DDR4 RAM 200 EUR alatt"},
            {"role": "assistant", "content": "Previous answer"},
            {"role": "user", "content": "keress ra ujra"},
        ],
        "keress ra ujra",
    )

    assert worker._generate_search_queries() == [
        "64GB DDR4 RAM 200 EUR alatt"
    ]


def test_hungarian_conversation_forces_hungarian_final_answer():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "Keress nekem 64GB DDR4 memoriat"},
        ],
        "most keress ra ujra",
    )

    instruction = worker._conversation_language_instruction()
    assert "Hungarian" in instruction


def test_single_topic_search_preserves_hardware_and_price_constraints():
    class ConstraintDroppingClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            return "DDR4 RAM Germany shops"

    worker = workers.ChatWebWorker(
        ConstraintDroppingClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress 2x32GB DDR4 3200 MHz RAM-ot Németországban 200 EUR alatt",
    )

    assert worker._generate_search_queries() == [
        "DDR4 RAM Germany shops 2x32GB 3200 MHz 200 EUR"
    ]


def test_multi_topic_search_does_not_cross_contaminate_constraints():
    class MultiClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            return (
                "latest Qwen model release\n"
                "64GB DDR4 2x32 current prices Germany"
            )

    worker = workers.ChatWebWorker(
        MultiClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        (
            "Nézd meg a legfrissebb Qwen modellt. "
            "Keress 2x32GB DDR4 RAM-ot 200 EUR alatt."
        ),
    )

    assert worker._generate_search_queries() == [
        "latest Qwen model release",
        "64GB DDR4 2x32 current prices Germany",
    ]


def test_chat_web_worker_keeps_provider_fallback_in_diagnostics(monkeypatch):
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["2x32GB DDR4 3200MHz Germany 200 EUR"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Bing Web RSS",
            "provider_chain_errors": [
                "Brave Search API: 401 Client Error"
            ],
            "query": query,
            "results": [{
                "title": "64GB DDR4 kit",
                "url": "https://example.com/ram",
                "snippet": "2x32GB DDR4 3200MHz",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/ram"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=10: [{
            "title": "64GB DDR4 kit",
            "url": "https://example.com/ram",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA",
    )

    client = DummyWebClient()
    tokens = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress 2x32GB DDR4 RAM-ot",
    )
    worker.token.connect(tokens.append)
    worker.run()

    combined = "".join(tokens)
    assert "Search provider:" not in combined
    assert worker.diagnostic_metadata["providers"] == ["Bing Web RSS"]
    assert worker.diagnostic_metadata["provider_fallbacks"] == [
        "Brave Search API: 401 Client Error"
    ]


def test_new_explicit_search_does_not_inherit_previous_topic():
    class TopicSwitchClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            user = messages[1]["content"]
            assert "PREVIOUS USER REQUEST" not in user
            assert "2x32GB DDR4" not in user
            assert "teas kannakat" in user
            return "tea kettles Germany"

    worker = workers.ChatWebWorker(
        TopicSwitchClient(),
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "Keress 2x32GB DDR4 RAM-ot 700 EUR alatt"},
            {"role": "assistant", "content": "Previous RAM answer"},
            {"role": "user", "content": "mondom teas kannakat keressel"},
        ],
        "mondom teas kannakat keressel",
    )

    assert worker._generate_search_queries() == ["tea kettles Germany"]


def test_new_web_topic_excludes_previous_chat_history_from_grounded_answer(monkeypatch):
    class TopicSwitchClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            return "tea kettles Germany"

    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "results": [{
                "title": "Tea kettle",
                "url": "https://example.com/tea-kettle",
                "snippet": "Tea kettle available in Germany",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/tea-kettle"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=6: [{
            "title": "Tea kettle",
            "url": "https://example.com/tea-kettle",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "Tea kettle Germany",
    )

    client = TopicSwitchClient()
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "Keress 2x32GB DDR4 RAM-ot 700 EUR alatt"},
            {"role": "assistant", "content": "Previous RAM answer"},
            {"role": "user", "content": "mondom teas kannakat keressel"},
        ],
        "mondom teas kannakat keressel",
    )
    worker.run()

    streamed_messages = client.stream_calls[0][1]
    combined = "\n".join(message["content"] for message in streamed_messages)
    assert "2x32GB DDR4" not in combined
    assert "Previous RAM answer" not in combined
    assert "mondom teas kannakat keressel" in combined
    assert "Tea kettle Germany" in combined


def test_referential_followup_still_keeps_previous_context():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "Keress teaskannakat"},
            {"role": "assistant", "content": "Previous answer"},
            {"role": "user", "content": "ebbol keress olcsobbat"},
        ],
        "ebbol keress olcsobbat",
    )

    assert worker._needs_previous_search_context()


def test_short_hungarian_web_prompt_stays_hungarian():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "ki Zsofia?",
    )

    instruction = worker._conversation_language_instruction()
    assert "Hungarian" in instruction
    assert "Answer in Hungarian" in instruction
    assert "Do not switch to English" in instruction


def test_unconstrained_ssd_shopping_uses_deterministic_product_evidence(monkeypatch):
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["4 TB SSD Germany"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "provider_chain_errors": [],
            "results": [
                {
                    "title": "4 TB SSD (2026) Preisvergleich",
                    "url": "https://www.idealo.de/preisvergleich/ProductCategory/14613F9786619.html",
                    "snippet": "4 TB SSD Preisvergleich",
                    "page_text": "",
                },
                {
                    "title": "SAMSUNG 870 QVO 4TB, 4 TB, SSD, intern",
                    "url": "https://www.mediamarkt.de/de/product/_samsung-870-qvo-4tb-12345.html",
                    "snippet": "SAMSUNG 870 QVO 4TB SSD 289,00 EUR",
                    "page_text": "",
                },
            ],
        },
    )

    client = DummyWebClient()
    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress nekem 4 TB-os SSD-t",
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    assert client.stream_calls == []

    combined = "".join(tokens)
    assert "Ellenőrzött termékszintű találatok:" in combined
    assert "SAMSUNG 870 QVO 4TB" in combined
    assert "289,00 EUR" in combined
    assert "mediamarkt.de/de/product/" in combined
    assert "Idealo" not in combined
    assert "Preis-Leistungs" not in combined
    assert "MB/s" not in combined
    assert "Shopping evidence:" not in combined
    assert worker.source_metadata


def test_unconstrained_shopping_fails_closed_without_product_page(monkeypatch):
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["4 TB SSD Germany"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "provider_chain_errors": [],
            "results": [
                {
                    "title": "4 TB SSD (2026) Preisvergleich",
                    "url": "https://www.idealo.de/preisvergleich/ProductCategory/14613F9786619.html",
                    "snippet": "4 TB SSD Preisvergleich",
                    "page_text": "",
                },
            ],
        },
    )

    client = DummyWebClient()
    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress nekem 4 TB-os SSD-t",
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    assert client.stream_calls == []

    combined = "".join(tokens)
    assert "Nem találtam olyan termékszintű forrást" in combined
    assert "Nem fogok kitalált árat vagy specifikációt" in combined
    assert "Shopping evidence:" not in combined


def test_price_bounded_teakettle_keeps_existing_verified_model_path(monkeypatch):
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress nekem teaskannat 100 EUR alatt",
    )

    source = worker.user_prompt
    from app.evidence_verifier import evidence_required
    from app.web_search_tool import build_search_plan
    from app.generic_shopping_evidence import is_generic_shopping_request

    assert is_generic_shopping_request(source)
    assert evidence_required(build_search_plan(source))


def test_web_worker_repairs_clearly_german_answer_for_hungarian_request():
    class LanguageRepairClient(DummyWebClient):
        def __init__(self):
            super().__init__()
            self.repair_calls = []

        def chat_once(self, model, messages, timeout=600.0):
            if messages and "Rewrite the supplied answer in Hungarian" in messages[0]["content"]:
                self.repair_calls.append((model, messages))
                return "Ellenőrzött találat magyarul, változatlan tényekkel."
            return super().chat_once(model, messages, timeout=timeout)

    client = LanguageRepairClient()
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress nekem SSD-t",
    )

    repaired = worker._repair_response_language(
        "Die Suche zeigt viele Angebote und Preise. Hier sind die besten Produkte."
    )

    assert repaired.startswith("Ellenőrzött találat")
    assert len(client.repair_calls) == 1


def test_web_worker_fails_closed_when_language_repair_stays_wrong():
    class BadRepairClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            if messages and "Rewrite the supplied answer in Hungarian" in messages[0]["content"]:
                return "Die Antwort bleibt leider auf Deutsch und enthaelt viele Preise."
            return super().chat_once(model, messages, timeout=timeout)

    worker = workers.ChatWebWorker(
        BadRepairClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keress nekem SSD-t",
    )

    repaired = worker._repair_response_language(
        "Die Suche zeigt viele Angebote und Preise. Hier sind die besten Produkte."
    )

    assert "nem egyezett a kérdés nyelvével" in repaired
    assert "hibás nyelvű választ" in repaired


def test_generic_shopping_bypasses_model_query_generation(monkeypatch):
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: (_ for _ in ()).throw(
            AssertionError("generic shopping must not use model query generation")
        ),
    )

    seen_queries = []

    def fake_search(query, max_results=6, fetch_pages=True):
        seen_queries.append((query, max_results))
        if "mediamarkt.de/de/product" in query:
            return {
                "provider": "Brave Search API",
                "query": query,
                "provider_chain_errors": [],
                "results": [{
                    "title": "Samsung 870 QVO 4TB SSD",
                    "url": "https://www.mediamarkt.de/de/product/_samsung-870-qvo-4tb-12345.html",
                    "snippet": "Samsung 870 QVO 4 TB SSD 289 EUR",
                    "page_text": "",
                }],
            }
        return {
            "provider": "Brave Search API",
            "query": query,
            "provider_chain_errors": [],
            "results": [],
        }

    monkeypatch.setattr(workers, "search_web", fake_search)

    client = DummyWebClient()
    tokens = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Keressel nekem 4tb-os ssd merevlemezt",
    )
    worker.token.connect(tokens.append)
    worker.run()

    combined = "".join(tokens)
    assert "Samsung 870 QVO 4TB SSD" in combined
    assert "Shopping evidence:" not in combined
    assert worker.source_metadata
    assert seen_queries
    assert all(max_results == 10 for _, max_results in seen_queries)


def test_run_chat_web_request_collects_grounded_worker_output(monkeypatch):
    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["latest Qwen local AI news"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "provider_chain_errors": [],
            "results": [{
                "title": "Qwen update",
                "url": "https://example.com/qwen",
                "snippet": "Fresh Qwen local AI news",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/qwen"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=6: [{
            "title": "Qwen update",
            "url": "https://example.com/qwen",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "WEB SEARCH TOOL DATA",
    )

    client = DummyWebClient()
    answer = workers.run_chat_web_request(
        client,
        "qwen-test",
        [
            {"role": "system", "content": "Base system"},
            {"role": "user", "content": "Keress rá a legfrissebb Qwen hírekre"},
        ],
        "Keress rá a legfrissebb Qwen hírekre",
    )

    assert "Grounded web answer." in answer
    assert "Search query:" not in answer
    assert "Web results / sources:" not in answer


def test_adaptive_chat_worker_retries_grounded_web_when_local_answer_is_stale(monkeypatch):
    class StaleClient:
        def __init__(self):
            self.calls = []

        def chat_once(self, model, messages, timeout=600.0):
            self.calls.append((model, messages))
            return "Nincs friss információm erről a kiadásról."

    monkeypatch.setattr(
        workers,
        "run_chat_web_request",
        lambda client, model, messages, prompt: "Friss, ellenőrzött webes válasz.",
    )

    client = StaleClient()
    tokens = []
    finished = []
    failed = []
    worker = workers.AdaptiveChatWorker(
        client,
        "qwen-test",
        [{"role": "user", "content": "Melyik Qwen verzió a legújabb?"}],
        "Melyik Qwen verzió a legújabb?",
    )
    worker.token.connect(tokens.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    assert finished == [True]
    assert tokens == ["Friss, ellenőrzött webes válasz."]
    assert worker.used_web_fallback is True


def test_adaptive_chat_worker_keeps_confident_local_answer_without_web(monkeypatch):
    class LocalClient:
        def chat_once(self, model, messages, timeout=600.0):
            return "A TCP egy megbízható, kapcsolatorientált protokoll."

    monkeypatch.setattr(
        workers,
        "run_chat_web_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stable answer must not trigger web fallback")
        ),
    )

    tokens = []
    worker = workers.AdaptiveChatWorker(
        LocalClient(),
        "qwen-test",
        [{"role": "user", "content": "Mi az a TCP?"}],
        "Mi az a TCP?",
    )
    worker.token.connect(tokens.append)
    worker.run()

    assert tokens == ["A TCP egy megbízható, kapcsolatorientált protokoll."]
    assert worker.used_web_fallback is False


def test_web_worker_replaces_stale_secondary_release_with_first_party_current_fact(monkeypatch):
    class WrongReleaseClient(DummyWebClient):
        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            self.stream_calls.append((model, messages))
            if not should_stop():
                on_token(
                    "A legújabb elérhető Ollama verzió: v0.33.2. "
                    "Forrás: egy másodlagos kiadási oldal."
                )

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["Ollama latest version release"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "provider_query": query,
            "retrieved_at": "2026-09-19T12:59:00",
            "provider_chain_errors": [],
            "results": [
                {
                    "title": "Releasebot - Ollama releases",
                    "url": "https://releasebot.io/updates/ollama",
                    "snippet": "Tracked version v0.33.2",
                    "page_text": "v0.33.2",
                },
                {
                    "title": "Releases · ollama/ollama · GitHub",
                    "url": "https://github.com/ollama/ollama/releases",
                    "snippet": "Official releases",
                    "page_text": (
                        "Release list v0.34.2 v0.34.1 v0.34.0 v0.33.3 v0.33.2 "
                        "v0.34.2 Latest What's Changed"
                    ),
                },
            ],
        },
    )

    client = WrongReleaseClient()
    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mi a legújabb Ollama verzió?",
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    combined = "".join(tokens)
    assert "**v0.34.2**" in combined
    assert "github.com/ollama/ollama/releases" in combined
    assert "legújabb elérhető Ollama verzió: v0.33.2" not in combined

    streamed_messages = client.stream_calls[0][1]
    grounded = "\n".join(item["content"] for item in streamed_messages)
    assert "AUTHORITATIVE CURRENT FACT" in grounded
    assert "Value: v0.34.2" in grounded
    assert "prefer that first-party authority" in grounded


def test_web_worker_does_not_replace_family_answer_with_qualified_tool_release(monkeypatch):
    class FamilyClient(DummyWebClient):
        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            self.stream_calls.append((model, messages))
            if not should_stop():
                on_token(
                    "A legfrissebb Qwen modellcsalád a Qwen3.8, "
                    "a hivatalos Qwen források alapján."
                )

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["Qwen latest version release"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "provider_query": query,
            "retrieved_at": "2026-09-19T13:20:00",
            "provider_chain_errors": [],
            "results": [
                {
                    "title": "Releases · QwenLM/qwen-code",
                    "url": "https://github.com/QwenLM/qwen-code/releases",
                    "snippet": "Qwen Code v0.24.1",
                    "page_text": "Release list v0.24.1 Latest",
                },
                {
                    "title": "Qwen",
                    "url": "https://qwen.ai/",
                    "snippet": "Official Qwen model family",
                    "page_text": "Qwen3.8 is the latest Qwen model family release.",
                },
            ],
        },
    )

    client = FamilyClient()
    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Melyik a jelenlegi legfrissebb Qwen verzió?",
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    combined = "".join(tokens)
    assert "Qwen3.8" in combined
    assert "v0.24.1" not in combined

    grounded = "\n".join(
        item["content"] for item in client.stream_calls[0][1]
    )
    assert "qualified subproduct/tool not named in the query" in grounded
    assert "do not use that result as the current-version authority" in grounded


def test_current_version_answer_with_authoritative_fact_is_canonical_and_brief(monkeypatch):
    class VerboseClient(DummyWebClient):
        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            self.stream_calls.append((model, messages))
            if not should_stop():
                on_token(
                    "A legújabb Ollama verzió v0.34.2. "
                    "Ezután egy nagyon hosszú idővonal és sok további részlet következne. "
                    "Történeti összefoglaló, API-változások, ökoszisztéma és egyéb adatok."
                )

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["Ollama latest version release"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "provider_query": query,
            "retrieved_at": "2026-09-19T13:30:00",
            "provider_chain_errors": [],
            "results": [
                {
                    "title": "Releases · ollama/ollama · GitHub",
                    "url": "https://github.com/ollama/ollama/releases",
                    "snippet": "Official releases",
                    "page_text": "Release list v0.34.2 v0.34.1 v0.34.2 Latest",
                }
            ],
        },
    )

    client = VerboseClient()
    tokens = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mi a legújabb Ollama verzió?",
    )
    worker.token.connect(tokens.append)
    worker.run()

    assert tokens
    main_answer = tokens[0]
    assert "**v0.34.2**" in main_answer
    assert "github.com/ollama/ollama/releases" in main_answer
    assert "idővonal" not in main_answer
    assert len(main_answer) < 400

    combined = "".join(tokens)
    assert "Search query:" not in combined
    assert "Web results / sources:" not in combined
    assert worker.source_metadata


def test_family_current_version_answer_is_compacted_with_structured_sources(monkeypatch):
    class FamilyClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            if messages and "Rewrite the supplied grounded answer" in messages[0]["content"]:
                return (
                    "A legfrissebb Qwen modellcsalád a Qwen3.8. "
                    "A rendelkezésre álló webes források ezt támasztják alá."
                )
            return "Qwen latest version release"

        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            self.stream_calls.append((model, messages))
            if not should_stop():
                on_token(
                    "A legfrissebb Qwen modellcsalád a Qwen3.8. "
                    "Key Highlights: Qwen3.8-Flash, Qwen3.8-27B és Qwen3.8-Flash-Next. "
                    "Részletes idővonal: 2026 augusztus, 2026 szeptember. "
                    "API improvements, Hugging Face organization, broader ecosystem, "
                    "további hosszú kutatási összefoglaló és háttérinformációk. "
                    "Ez a rész szándékosan hosszú, hogy a tömörítő útvonal lefusson. "
                    * 8
                )

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["Qwen latest version release"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "provider_query": query,
            "retrieved_at": "2026-09-19T13:30:00",
            "provider_chain_errors": [],
            "results": [
                {
                    "title": "Qwen",
                    "url": "https://qwen.ai/",
                    "snippet": "Official Qwen model family",
                    "page_text": "Qwen3.8 is the latest Qwen model family release.",
                },
                {
                    "title": "Releases · QwenLM/qwen-code",
                    "url": "https://github.com/QwenLM/qwen-code/releases",
                    "snippet": "Qwen Code v0.24.1",
                    "page_text": "Release list v0.24.1 Latest",
                },
            ],
        },
    )

    client = FamilyClient()
    tokens = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Melyik a jelenlegi legfrissebb Qwen verzió?",
    )
    worker.token.connect(tokens.append)
    worker.run()

    assert tokens
    main_answer = tokens[0]
    assert "Qwen3.8" in main_answer
    assert "Key Highlights" not in main_answer
    assert "API improvements" not in main_answer
    assert len(main_answer) < 700

    combined = "".join(tokens)
    assert "Search query:" not in combined
    assert "Web results / sources:" not in combined
    assert worker.source_metadata


def test_current_version_compactor_rejects_new_version_tokens():
    class UnsafeCompactClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            return "A legfrissebb verzió a Qwen9.9."

    worker = workers.ChatWebWorker(
        UnsafeCompactClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Melyik a jelenlegi legfrissebb Qwen verzió?",
    )
    original = (
        "A legfrissebb Qwen modellcsalád a Qwen3.8. "
        + "Részletes háttér és kutatási összefoglaló. " * 40
    )

    compact = worker._compact_current_version_answer(original, [])

    assert "Qwen3.8" in compact
    assert "Qwen9.9" not in compact


def test_version_like_token_guard_detects_semver_and_named_model_versions():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Melyik a jelenlegi legfrissebb Qwen verzió?",
    )

    tokens = worker._version_like_tokens(
        "Qwen3.8, Qwen9.9, v0.34.2 és 1.25.0"
    )

    assert "Qwen3.8" in tokens
    assert "Qwen9.9" in tokens
    assert "v0.34.2" in tokens
    assert "1.25.0" in tokens


def test_generic_grounded_web_answer_is_compacted_to_direct_primary_answer():
    class CompactClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            if messages and "Rewrite the supplied grounded web answer" in messages[0]["content"]:
                return (
                    "A Bitcoin aktuális ára 81 669,66 USD. "
                    "A forrás késleltetett adatot jelez, ezért az érték változhat."
                )
            return "unused"

    worker = workers.ChatWebWorker(
        CompactClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mennyi most a bitcoin árfolyama?",
    )
    verbose = (
        "Ha szeretnéd követni a BTC árfolyamot, használhatsz több oldalt is. "
        "CoinMarketCap, CoinGecko, Binance és TradingView is elérhető. "
        "A megadott szöveg szerint a BTC/USD árfolyam 81 669,66 USD. "
        "A forrás késleltetett adatot jelez. "
        + "További statisztikák és háttérinformációk. " * 30
    )

    compact = worker._compact_grounded_answer(verbose)

    assert compact.startswith("A Bitcoin aktuális ára 81 669,66 USD")
    assert len(compact) < 750
    assert "CoinMarketCap, CoinGecko" not in compact


def test_generic_compactor_rejects_new_numeric_fact():
    class UnsafeCompactClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            return "A Bitcoin aktuális ára 99 999 USD."

    worker = workers.ChatWebWorker(
        UnsafeCompactClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mennyi most a bitcoin árfolyama?",
    )
    original = (
        "A BTC/USD árfolyam 81 669,66 USD. "
        + "További részletek és háttérinformációk. " * 40
    )

    compact = worker._compact_grounded_answer(original)

    assert "81 669,66 USD" in compact
    assert "99 999 USD" not in compact


def test_detailed_web_request_opts_out_of_generic_compaction():
    class NoRewriteClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            raise AssertionError("detailed request must not be compacted")

    worker = workers.ChatWebWorker(
        NoRewriteClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Készíts részletes elemzést a Bitcoin mai árfolyamáról.",
    )
    original = "Részletes válasz. " * 100

    assert worker._compact_grounded_answer(original) == original


def test_short_grounded_web_answer_is_left_unchanged():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mennyi most a bitcoin árfolyama?",
    )
    original = "A BTC/USD árfolyam 81 669,66 USD."

    assert worker._compact_grounded_answer(original) == original



def test_market_quote_web_mode_is_concise_and_hides_source_appendix(monkeypatch):
    class MarketClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0):
            self.once_calls.append((model, messages))
            system = messages[0]["content"]
            if "Rewrite the supplied grounded market answer" in system:
                return "A Tesla részvény ára jelenleg **364.27 USD**."
            return "Tesla stock price"

        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            self.stream_calls.append((model, messages))
            if not should_stop():
                on_token(
                    "A Tesla részvény ára jelenleg 364.27 USD. "
                    "A vállalat kilátásairól több elemzői vélemény is elérhető. "
                    "További technikai elemzés is készíthető."
                )

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: ["Tesla stock price"],
    )
    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "test",
            "query": query,
            "results": [{
                "title": "Tesla quote",
                "url": "https://example.com/tsla",
                "snippet": "TSLA 364.27 USD",
            }],
        },
    )
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/tsla"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=6: [{
            "title": "Tesla quote",
            "url": "https://example.com/tsla",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "TSLA 364.27 USD",
    )

    tokens = []
    worker = workers.ChatWebWorker(
        MarketClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mennyi most a Tesla részvény ára?",
        compact_market_quote=True,
    )
    worker.token.connect(tokens.append)
    worker.run()

    combined = "".join(tokens)
    assert combined == "A Tesla részvény ára jelenleg **364.27 USD**."
    assert "Search query:" not in combined
    assert "Web results / sources:" not in combined


def test_web_worker_chooses_newest_family_fact_across_multiple_queries(monkeypatch):
    class StaleFirstClient(DummyWebClient):
        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
        ):
            self.stream_calls.append((model, messages))
            if not should_stop():
                on_token(
                    "A hivatalos forrás alapján a legfrissebb Qwen verzió Qwen2.5."
                )

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: [
            "Qwen current version release",
            "Qwen latest model family release",
        ],
    )

    def fake_search(query, max_results=6, fetch_pages=True):
        if "current version" in query:
            return {
                "provider": "Brave Search API",
                "query": query,
                "provider_query": query,
                "retrieved_at": "2026-09-20T09:30:00",
                "provider_chain_errors": [],
                "results": [{
                    "title": "Qwen legacy official site",
                    "url": "https://qwenlm.github.io/",
                    "snippet": "Official Qwen model family",
                    "page_text": "The current model generation is Qwen2.5.",
                }],
            }
        return {
            "provider": "Brave Search API",
            "query": query,
            "provider_query": query,
            "retrieved_at": "2026-09-20T09:30:01",
            "provider_chain_errors": [],
            "results": [{
                "title": "Qwen",
                "url": "https://qwen.ai/blog?id=qwen3.8",
                "snippet": "Official Qwen model family update",
                "page_text": "Qwen3.8 is the latest Qwen model family release.",
            }],
        }

    monkeypatch.setattr(workers, "search_web", fake_search)

    client = StaleFirstClient()
    tokens = []
    failed = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Melyik a jelenlegi legfrissebb Qwen verzió?",
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    assert tokens
    main_answer = tokens[0]
    assert "Qwen3.8" in main_answer
    assert "Qwen2.5" not in main_answer
    assert "qwen.ai/blog?id=qwen3.8" in main_answer



def test_adaptive_chat_worker_local_only_never_uses_web_fallback(monkeypatch):
    class StaleClient:
        def chat_once(self, model, messages, timeout=600.0):
            return "Nincs friss informaciom errol a kiadasrol."

    monkeypatch.setattr(
        workers,
        "run_chat_web_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("LOCAL ONLY must never call web fallback")
        ),
    )

    tokens = []
    failed = []
    worker = workers.AdaptiveChatWorker(
        StaleClient(),
        "qwen-test",
        [{"role": "user", "content": "Melyik Qwen verzio a legujabb?"}],
        "Melyik Qwen verzio a legujabb?",
        allow_web_fallback=False,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert not failed
    assert tokens == ["Nincs friss informaciom errol a kiadasrol."]
    assert worker.used_web_fallback is False



def test_adaptive_chat_repairs_accidental_hangul_with_parent_constraints():
    from app.task_constraints import build_task_constraints

    class RepairingClient:
        def __init__(self):
            self.responses = [
                "Ez egy magyar válasz 잘못 beszúrással.",
                "Ez egy javított magyar válasz.",
            ]

        def chat_once(self, model, messages, timeout=600.0):
            return self.responses.pop(0)

    prompt = "Válaszolj magyarul röviden."
    tokens = []
    errors = []
    worker = workers.AdaptiveChatWorker(
        RepairingClient(),
        "qwen-test",
        [{"role": "user", "content": prompt}],
        prompt,
        allow_web_fallback=False,
        constraints=build_task_constraints(prompt),
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(errors.append)

    worker.run()

    assert errors == []
    assert tokens == ["Ez egy javított magyar válasz."]



def test_adaptive_chat_repairs_stale_subject_substitution():
    from app.task_constraints import build_task_constraints

    class DriftRepairClient:
        def __init__(self):
            self.responses = [
                "A Bitcoin aktualis ara 60 000 USD.",
                "A Tesla aktualis ara 364 USD.",
            ]

        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            return self.responses.pop(0)

    prompt = "Melyik a Tesla aktualis ara?"
    messages = [
        {"role": "user", "content": "Melyik a Bitcoin aktualis ara?"},
        {"role": "assistant", "content": "A Bitcoin ara..."},
        {"role": "user", "content": prompt},
    ]
    tokens = []
    errors = []
    worker = workers.AdaptiveChatWorker(
        DriftRepairClient(),
        "qwen-test",
        messages,
        prompt,
        allow_web_fallback=False,
        constraints=build_task_constraints(prompt),
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(errors.append)

    worker.run()

    assert errors == []
    assert tokens == ["A Tesla aktualis ara 364 USD."]



def test_factual_risk_query_validation_seeds_current_user_request():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mikor írta Wrong Author a Silver Story című művet?",
    )

    queries = worker._validated_search_queries([
        "Silver Story publication date",
        "Wrong Author Silver Story",
    ])

    assert queries
    assert queries[0] == "Mikor írta Wrong Author a Silver Story című művet?"
    assert len(queries) <= 4


def test_factual_risk_query_seed_does_not_duplicate_equivalent_generated_query():
    prompt = "Who wrote Silver Story?"
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )

    queries = worker._validated_search_queries([
        prompt,
        "Silver Story author",
    ])

    assert queries[0] == prompt
    assert queries.count(prompt) == 1



def test_single_factual_risk_request_skips_model_query_generation(monkeypatch):
    from app.request_trace import RequestTrace

    prompt = "Mikor írta Wrong Author a Silver Story című művet?"
    search_calls = []

    class FactualClient:
        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            return (
                "A Silver Story című művet Correct Author írta, "
                "és 1912-ben jelent meg."
            )

        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
            **kwargs,
        ):
            if not should_stop():
                on_token(
                    "A Silver Story című művet Correct Author írta, "
                    "és 1912-ben jelent meg."
                )

    def fake_search(query, max_results=6, fetch_pages=True):
        search_calls.append(query)
        return {
            "provider": "Brave Search API",
            "query": query,
            "retrieved_at": "2026-09-22T10:00:00",
            "provider_chain_errors": [],
            "results": [{
                "title": "Correct Author: Silver Story",
                "url": "https://example.com/silver-story",
                "snippet": (
                    "Silver Story was written by Correct Author and "
                    "published in 1912."
                ),
                "page_text": (
                    "Silver Story was written by Correct Author and "
                    "published in 1912."
                ),
            }],
        }

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: (_ for _ in ()).throw(
            AssertionError("factual fast path must skip model query generation")
        ),
    )
    monkeypatch.setattr(workers, "search_web", fake_search)
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/silver-story"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=6: [{
            "title": "Correct Author: Silver Story",
            "url": "https://example.com/silver-story",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: (
            "Silver Story was written by Correct Author and published in 1912."
        ),
    )

    trace = RequestTrace("test")
    tokens = []
    errors = []
    worker = workers.ChatWebWorker(
        FactualClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
        trace=trace,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(errors.append)
    worker.run()

    assert errors == []
    assert tokens
    assert "Correct Author" in tokens[0]
    assert "1912" in tokens[0]
    assert search_calls == ["Silver Story creation publication date year"]

    snapshot = trace.snapshot()
    assert snapshot["phases_ms"]["query_generation"] == 0.0
    assert snapshot["metadata"]["query_strategy"] == "premise_neutral_title_relation"



def test_resolved_punctuation_followup_preserves_previous_user_language():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [
            {"role": "user", "content": "Mikor írta Arany Janos a Janos vitez cimu verset?"},
            {"role": "assistant", "content": "Petőfi Sándor írta 1844-ben."},
            {"role": "user", "content": "?"},
        ],
        "?",
    )

    assert worker.followup_resolution.status == "resolved"
    assert worker._response_language_source().startswith("Mikor írta")
    instruction = worker._conversation_language_instruction()
    assert "Answer in Hungarian" in instruction


def test_direct_factual_request_uses_one_grounded_model_call_not_forced_second_pass(
    monkeypatch,
):
    from app.request_trace import RequestTrace

    prompt = "Mikor írta Wrong Author a Silver Story című művet?"

    class SinglePassClient:
        def __init__(self):
            self.once_calls = []
            self.stream_calls = []

        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            self.once_calls.append((model, messages))
            return (
                "A Silver Story című művet nem Wrong Author, hanem Correct Author "
                "írta, és 1912-ben jelent meg."
            )

        def chat_stream(self, *args, **kwargs):
            self.stream_calls.append((args, kwargs))
            raise AssertionError(
                "direct factual single-pass path must not stream a draft first"
            )

    def fake_search(query, max_results=6, fetch_pages=True):
        assert query == "Silver Story creation publication date year"
        return {
            "provider": "Brave Search API",
            "query": query,
            "retrieved_at": "2026-09-22T10:00:00",
            "provider_chain_errors": [],
            "results": [{
                "title": "Correct Author: Silver Story",
                "url": "https://example.com/silver-story",
                "snippet": (
                    "Silver Story was written by Correct Author and "
                    "published in 1912."
                ),
                "page_text": (
                    "Silver Story was written by Correct Author and "
                    "published in 1912."
                ),
            }],
        }

    bundle_kwargs = {}
    real_bundle = workers.compact_evidence_bundle

    def capture_bundle(*args, **kwargs):
        bundle_kwargs.update(kwargs)
        return real_bundle(*args, **kwargs)

    monkeypatch.setattr(workers, "compact_evidence_bundle", capture_bundle)
    monkeypatch.setattr(workers, "search_web", fake_search)
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/silver-story"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=6: [{
            "title": "Correct Author: Silver Story",
            "url": "https://example.com/silver-story",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: (
            "Silver Story was written by Correct Author and published in 1912."
        ),
    )

    client = SinglePassClient()
    tokens = []
    errors = []
    trace = RequestTrace("test")
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
        trace=trace,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(errors.append)
    worker.run()

    assert errors == []
    assert len(client.once_calls) == 1
    assert client.stream_calls == []
    assert bundle_kwargs["max_sources"] == 4
    assert bundle_kwargs["max_total_chars"] == 3000
    assert bundle_kwargs["max_text_chars"] == 320
    assert tokens == [
        "A Silver Story című művet nem Wrong Author, hanem Correct Author "
        "írta, és 1912-ben jelent meg."
    ]
    snapshot = trace.snapshot()
    assert snapshot["metadata"]["generation_strategy"] == "factual_single_pass"
    assert snapshot["metadata"]["factual_authority_profile"] == "direct_compact"
    assert snapshot["metadata"]["factual_authority_chars"] <= 3000


def test_direct_fact_fetches_one_page_only_when_snippets_lack_requested_date(
    monkeypatch,
):
    prompt = "Mikor írta Wrong Author a Silver Story című művet?"
    fetched = []

    class Client:
        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            return "A Silver Story című művet Correct Author írta, és 1912-ben jelent meg."

    monkeypatch.setattr(
        workers,
        "search_web",
        lambda query, max_results=6, fetch_pages=True: {
            "provider": "Brave Search API",
            "query": query,
            "retrieved_at": "2026-09-22T10:00:00",
            "results": [{
                "title": "Silver Story",
                "url": "https://example.com/silver-story",
                "snippet": "Silver Story was written by Correct Author.",
            }],
        },
    )

    def fetch_one(payload, page_fetch_budget=1, timeout=8.0):
        fetched.append((page_fetch_budget, timeout))
        payload = dict(payload)
        payload["results"] = [dict(payload["results"][0])]
        payload["results"][0]["page_text"] = "Published in 1912."
        return payload

    monkeypatch.setattr(workers, "fetch_result_pages", fetch_one)
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/silver-story"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=6: [{
            "title": "Silver Story",
            "url": "https://example.com/silver-story",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: "Silver Story was written by Correct Author and published in 1912.",
    )

    worker = workers.ChatWebWorker(
        Client(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )
    tokens = []
    errors = []
    worker.token.connect(tokens.append)
    worker.failed.connect(errors.append)
    worker.run()

    assert errors == []
    assert tokens
    assert fetched and fetched[0][0] == 1
    assert worker.execution_control.budget.search_calls == 1
    assert worker.execution_control.budget.page_fetches == 1



def test_hungarian_language_repair_uses_native_instruction():
    class RepairClient:
        def __init__(self):
            self.messages = None

        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            self.messages = messages
            return "A Pokolgép 1980-ban alakult Budapesten."

    client = RepairClient()
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "mikor alakult a pokolgep?",
    )

    repaired = worker._repair_response_language(
        "The band Pokolgép was formed in 1980 in Budapest."
    )

    assert repaired == "A Pokolgép 1980-ban alakult Budapesten."
    assert client.messages is not None
    assert "kizárólag magyar" in client.messages[0]["content"].casefold()



def test_entity_overview_uses_semantic_profile_without_model_query_generation(
    monkeypatch,
):
    prompt = "Mit tudsz az Ezüst Hold zenekarról?"
    search_calls = []

    class OverviewClient:
        def __init__(self):
            self.once_calls = []
            self.stream_calls = []

        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            self.once_calls.append((model, messages))
            raise AssertionError(
                "entity overview should not need query-generation or compaction call"
            )

        def chat_stream(
            self,
            model,
            messages,
            on_token,
            should_stop,
            timeout=600.0,
            **kwargs,
        ):
            self.stream_calls.append((model, messages))
            system = messages[-2]["content"]
            assert "kind=entity_overview" in system
            assert "substantive overview" in system
            if not should_stop():
                on_token(
                    "Az Ezüst Hold egy magyar zenekar. "
                    "A források alapján a története több korszakra tagolódik, "
                    "és több fontos kiadvány, tag és mérföldkő kapcsolódik hozzá."
                )

    def fake_search(query, max_results=6, fetch_pages=True):
        search_calls.append((query, max_results, fetch_pages))
        return {
            "provider": "Brave Search API",
            "query": query,
            "provider_query": query,
            "retrieved_at": "2026-09-22T10:00:00",
            "provider_chain_errors": [],
            "results": [{
                "title": "Ezüst Hold zenekar története",
                "url": "https://example.com/ezust-hold",
                "snippet": "Az Ezüst Hold zenekar története, tagjai és kiadványai.",
                "page_text": "Az Ezüst Hold több korszakon át működő magyar zenekar.",
            }],
        }

    monkeypatch.setattr(
        workers.ChatWebWorker,
        "_generate_search_queries",
        lambda self: (_ for _ in ()).throw(
            AssertionError("overview profile must skip model query generation")
        ),
    )
    monkeypatch.setattr(workers, "search_web", fake_search)
    monkeypatch.setattr(
        workers,
        "source_urls",
        lambda payload: ["https://example.com/ezust-hold"],
    )
    monkeypatch.setattr(
        workers,
        "source_entries",
        lambda payload, limit=6: [{
            "title": "Ezüst Hold zenekar története",
            "url": "https://example.com/ezust-hold",
        }],
    )
    monkeypatch.setattr(
        workers,
        "web_search_context_text",
        lambda payload: (
            "Ezüst Hold zenekar története, tagjai, kiadványai és mérföldkövei."
        ),
    )

    client = OverviewClient()
    tokens = []
    errors = []
    worker = workers.ChatWebWorker(
        client,
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        prompt,
    )
    worker.token.connect(tokens.append)
    worker.failed.connect(errors.append)
    worker.run()

    assert errors == []
    assert tokens
    assert client.once_calls == []
    assert len(client.stream_calls) == 1
    assert search_calls == [(prompt, 8, 2)]
    assert worker.diagnostic_metadata["request_kind"] == "entity_overview"
    assert worker.diagnostic_metadata["response_depth"] == "overview"
    assert worker.diagnostic_metadata["query_budget"] == 1
    assert worker.diagnostic_metadata["page_fetch_budget"] == 2


def test_entity_overview_is_not_collapsed_to_three_sentences():
    class NoCompactClient(DummyWebClient):
        def chat_once(self, model, messages, timeout=600.0, **kwargs):
            raise AssertionError("overview response must not enter concise compaction")

    worker = workers.ChatWebWorker(
        NoCompactClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mit tudsz az Ezüst Hold zenekarról?",
    )
    original = "Áttekintő, evidence-grounded bekezdés. " * 40

    assert worker.request_profile.kind == "entity_overview"
    assert worker._wants_detailed_web_answer() is True
    assert worker._compact_grounded_answer(original) == original


def test_direct_fact_keeps_narrow_semantic_budget():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mikor írta Nimbus Szerző az Ezüst Történetet?",
    )

    assert worker.request_profile.kind == "direct_fact"
    assert worker.request_profile.query_budget == 1
    assert worker.request_profile.source_budget == 4
    assert worker.request_profile.page_fetch_budget == 2
    assert worker._wants_detailed_web_answer() is False


def test_entity_formation_question_uses_direct_fact_execution_budget():
    worker = workers.ChatWebWorker(
        DummyWebClient(),
        "qwen-test",
        [{"role": "system", "content": "Base system"}],
        "Mikor alakult a Sample Band?",
    )

    assert worker.request_profile.kind == "direct_fact"
    assert worker.request_profile.requested_fact == "temporal"
    assert worker.execution_control.budget.timeout_seconds == 45.0
    assert worker.execution_control.budget.max_search_calls == 1

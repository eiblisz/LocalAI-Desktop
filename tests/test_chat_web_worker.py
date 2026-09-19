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


def test_chat_web_worker_searches_streams_and_appends_sources(monkeypatch):
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
    assert "Search query: Qwen local AI latest news" in combined
    assert "https://example.com/qwen" in combined


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
    assert "Search queries:" in combined
    assert "https://example.com/1" in combined
    assert "https://example.com/2" in combined
    assert "https://example.com/3" in combined


def test_chat_web_worker_appends_markdown_result_links(monkeypatch):
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
    assert (
        "[Kingston 64GB DDR4 kit]"
        "(https://shop.example/kingston-64gb)"
        in combined
    )
    assert "Web results / sources:" in combined


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
    assert "Search query: 2x32GB DDR4 Germany under 1000 EUR" in "".join(tokens)


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


def test_chat_web_worker_footer_reports_provider_and_brave_fallback(monkeypatch):
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
    assert "Search provider: Bing Web RSS" in combined
    assert "Brave fallback: 401 Client Error" in combined


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
    assert "Shopping evidence: PASS" in combined


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
    assert "Shopping evidence: FAIL-CLOSED" in combined


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
    assert "Shopping evidence: PASS" in combined
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
    assert "Search query: latest Qwen local AI news" in answer
    assert "https://example.com/qwen" in answer


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


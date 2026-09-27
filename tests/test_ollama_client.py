import os
import pytest
import requests

from app.ollama_client import OllamaClient, ollama_failure_metadata
from app.request_trace import RequestTrace
from app.task_constraints import build_task_constraints
from app.workers import AdaptiveChatWorker
from app.ollama_resource_coordinator import (
    OWNER_EINSTEIN,
    OWNER_LOCALAI_DESKTOP,
    STATE_IDLE,
    STATE_INFERENCE_ACTIVE,
    STATE_STALE,
    OllamaResourceBusyError,
    ResourceLeaseStore,
)


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": "ok"}}


def test_chat_once_forwards_explicit_native_response_format(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["value"],
        "properties": {"value": {"type": "string"}},
    }

    result = OllamaClient("http://127.0.0.1:11434").chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
        response_format=schema,
    )

    assert result == "ok"
    assert captured["json"] == {
        "model": "qwen-test",
        "messages": [{"role": "user", "content": "test"}],
        "stream": False,
        "options": {"num_predict": 1024},
        "format": schema,
    }
    assert captured["timeout"] == 600.0


def test_chat_once_omits_format_when_not_explicitly_selected(monkeypatch):
    captured = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    OllamaClient().chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
    )

    assert "format" not in captured["json"]
    assert "think" not in captured["json"]
    assert captured["json"]["options"]["num_predict"] == 1024


def test_non_thinking_chat_omits_think_for_model_compatibility(monkeypatch):
    captured = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    monkeypatch.setattr("app.ollama_client.OLLAMA_THINKING_ENABLED", False)

    OllamaClient().chat_once(
        model="eurollm:9b-q4",
        messages=[{"role": "user", "content": "test"}],
    )

    assert "think" not in captured["json"]


def test_chat_request_allows_explicit_operator_thinking_opt_in(monkeypatch):
    captured = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    monkeypatch.setattr("app.ollama_client.OLLAMA_THINKING_ENABLED", True)

    OllamaClient().chat_once(
        model="reasoning-test",
        messages=[{"role": "user", "content": "think deliberately"}],
    )

    assert captured["json"]["think"] is True


class _ShowResponse:
    def __init__(self, context_length):
        self.context_length = context_length

    def raise_for_status(self):
        return None

    def json(self):
        return {"model_info": {"llama.context_length": self.context_length}}


def test_small_final_payload_keeps_default_context_without_num_ctx_override(monkeypatch):
    captured = {}
    decisions = []

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    assert OllamaClient().chat_once(
        model="local-test:9b-q4",
        messages=[{"role": "user", "content": "Rövid kérdés."}],
        context_budget_callback=decisions.append,
    ) == "ok"

    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["options"] == {"num_predict": 1024}
    assert decisions == [{
        "estimated_final_prompt_units": 20,
        "requested_output_units": 1024,
        "requested_num_ctx": 4096,
        "context_budget_decision": "fits_default_context",
        "context_budget_safety_units": 192,
    }]


def test_final_grounded_payload_raises_context_to_next_safe_step(monkeypatch):
    captured = {}
    show_calls = []

    def fake_post(url, **kwargs):
        if url.endswith("/api/show"):
            show_calls.append(kwargs["json"])
            return _ShowResponse(32768)
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    messages = [
        {"role": "system", "content": "Grounded answer instructions. " * 35},
        {
            "role": "user",
            "content": (
                "CURRENT USER REQUEST: factual question\n\n"
                "AUTHORIZED WEB TOOL DATA:\n" + ("source evidence " * 800)
            ),
        },
    ]
    decisions = []

    assert OllamaClient().chat_once(
        model="local-test:9b-q4",
        messages=messages,
        num_predict=1024,
        context_budget_callback=decisions.append,
    ) == "ok"

    assert show_calls == [{"model": "local-test:9b-q4"}]
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["options"] == {
        "num_predict": 1024,
        "num_ctx": 8192,
    }
    assert decisions[0]["estimated_final_prompt_units"] > 3000
    assert decisions[0]["requested_num_ctx"] == 8192
    assert decisions[0]["model_max_context"] == 32768
    assert decisions[0]["context_budget_decision"] == "raised_to_next_context_step"


def test_context_budget_never_exceeds_model_declared_maximum(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        if url.endswith("/api/show"):
            return _ShowResponse(8192)
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    decisions = []

    assert OllamaClient().chat_once(
        model="context-limited-test",
        messages=[{"role": "user", "content": "evidence " * 9000}],
        num_predict=1024,
        context_budget_callback=decisions.append,
    ) == "ok"

    assert captured["json"]["options"]["num_ctx"] == 8192
    assert decisions[0]["requested_num_ctx"] <= decisions[0]["model_max_context"]
    assert decisions[0]["context_budget_decision"] == "model_max_context_insufficient"


def test_model_context_metadata_is_cached_for_repeated_large_requests(monkeypatch):
    show_calls = []

    def fake_post(url, **_kwargs):
        if url.endswith("/api/show"):
            show_calls.append(url)
            return _ShowResponse(32768)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    client = OllamaClient()
    messages = [{"role": "user", "content": "grounded evidence " * 1200}]

    assert client.chat_once("cached-context-test", messages, num_predict=1024) == "ok"
    assert client.chat_once("cached-context-test", messages, num_predict=1024) == "ok"

    assert show_calls == ["http://127.0.0.1:11434/api/show"]


def test_grounded_direct_fact_payload_reaches_chat_with_context_override(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        if url.endswith("/api/show"):
            return _ShowResponse(32768)
        captured["url"] = url
        captured.update(kwargs)
        if kwargs["json"]["options"].get("num_ctx") != 8192:
            raise requests.HTTPError("would reject the undersized context")
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    answer = OllamaClient().chat_once(
        model="local-factual-test:9b-q4",
        num_predict=1024,
        messages=[
            {
                "role": "system",
                "content": "Use only authorized evidence. " * 40,
            },
            {
                "role": "user",
                "content": (
                    "CURRENT USER REQUEST: false premise\n\n"
                    "AUTHORIZED EVIDENCE:\n" + ("grounded source " * 900)
                ),
            },
        ],
    )

    assert answer == "ok"
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["options"]["num_ctx"] == 8192


def test_context_decision_is_preserved_on_a_later_ollama_http_failure(monkeypatch):
    class BadRequestResponse:
        status_code = 400
        text = ""

        def json(self):
            return {}

        def raise_for_status(self):
            error = requests.HTTPError("Bad Request")
            error.response = self
            raise error

    def fake_post(url, **_kwargs):
        if url.endswith("/api/show"):
            return _ShowResponse(32768)
        return BadRequestResponse()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    with pytest.raises(requests.HTTPError) as exc:
        OllamaClient().chat_once(
            model="local-factual-test:9b-q4",
            num_predict=1024,
            messages=[{"role": "user", "content": "evidence " * 1800}],
        )

    metadata = ollama_failure_metadata(exc.value)
    assert metadata["ollama_failure_stage"] == "ollama_http"
    assert metadata["ollama_http_status"] == 400
    assert metadata["requested_num_ctx"] == 8192
    assert metadata["model_max_context"] == 32768
    assert metadata["context_budget_decision"] == "raised_to_next_context_step"


def _desktop_client(tmp_path):
    store = ResourceLeaseStore(tmp_path / "leases.json")
    return OllamaClient(
        owner_type=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        resource_store=store,
    ), store


def test_prepare_model_unloads_only_proven_desktop_owned_idle_model(
    monkeypatch,
    tmp_path,
):
    client, store = _desktop_client(tmp_path)
    released = []

    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="gemma4:26b",
        state=STATE_IDLE,
        owner_pid=os.getpid(),
        model_pid=777,
    )

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["gemma4:26b"],
    )
    monkeypatch.setattr(
        client,
        "_runner_processes",
        lambda: [{"pid": 777, "name": "runner", "command_line": "runner"}],
    )
    monkeypatch.setattr(client, "_external_consumers", lambda: [])
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda _client, model, timeout: released.append(model),
    )

    result = client.prepare_model("qwen3-coder:30b-a3b-q8_0")

    assert result == ["gemma4:26b"]
    assert released == ["gemma4:26b"]
    assert store.ownership("gemma4:26b")["state"] == STATE_STALE


def test_prepare_model_blocks_foreign_active_owner(monkeypatch, tmp_path):
    client, store = _desktop_client(tmp_path)
    released = []

    store.upsert(
        owner=OWNER_EINSTEIN,
        owner_id="einstein:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_INFERENCE_ACTIVE,
        owner_pid=None,
        model_pid=888,
    )

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(
        client,
        "_runner_processes",
        lambda: [{"pid": 888, "name": "runner", "command_line": "runner"}],
    )
    monkeypatch.setattr(client, "_external_consumers", lambda: [])
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda _client, model, timeout: released.append(model),
    )

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.prepare_model("gemma4:26b")

    assert "EINSTEIN" in str(exc.value)
    assert released == []


def test_prepare_model_blocks_unknown_ownership(monkeypatch, tmp_path):
    client, _store = _desktop_client(tmp_path)

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(
        client,
        "_runner_processes",
        lambda: [{"pid": 999, "name": "runner", "command_line": "runner"}],
    )
    monkeypatch.setattr(client, "_external_consumers", lambda: [])

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.prepare_model("gemma4:26b")

    assert "UNKNOWN" in str(exc.value)


def test_prepare_model_reconciles_stopping_without_process_kill(
    monkeypatch,
    tmp_path,
):
    client, store = _desktop_client(tmp_path)
    unloaded = []

    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_IDLE,
        owner_pid=os.getpid(),
        model_pid=777,
    )
    monkeypatch.setattr(client, "_external_consumers", lambda: [])
    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(client, "_runner_processes", lambda: [])
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda *_args, **_kwargs: unloaded.append(True),
    )

    assert client.prepare_model("gemma4:26b") == []
    assert unloaded == []
    ownership = store.ownership("qwen3-coder:30b-a3b-q8_0")
    assert ownership["state"] == STATE_STALE
    assert "no runner process" in ownership["detail"]


def test_prepare_model_blocks_when_external_consumer_is_visible(
    monkeypatch,
    tmp_path,
):
    client, store = _desktop_client(tmp_path)

    store.upsert(
        owner=OWNER_LOCALAI_DESKTOP,
        owner_id="desktop:test",
        model="qwen3-coder:30b-a3b-q8_0",
        state=STATE_IDLE,
        owner_pid=os.getpid(),
        model_pid=777,
    )
    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )
    monkeypatch.setattr(
        client,
        "_runner_processes",
        lambda: [{"pid": 777, "name": "runner", "command_line": "runner"}],
    )
    monkeypatch.setattr(
        client,
        "_external_consumers",
        lambda: [{"pid": 901, "owner": "MANUAL"}],
    )

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.prepare_model("gemma4:26b")

    assert "MANUAL" in str(exc.value)


def test_auto_prepare_model_is_opt_in_for_chat_once(monkeypatch):
    captured = {"prepared": [], "readiness": []}

    def fake_prepare(self, model, timeout=6.0, *, allow_model_release=True):
        captured["prepared"].append((model, allow_model_release))
        return []

    def fake_ready(self, model, **kwargs):
        captured["readiness"].append((model, kwargs))
        return {
            "model_resident_before": True,
            "model_warmup_required": False,
            "model_warmup_reason": "",
            "model_warmup_result": "not_needed",
            "model_resident_after": True,
            "model_warmup_requested_num_ctx": kwargs["requested_num_ctx"],
        }

    def fake_post(_url, **_kwargs):
        return _Response()

    monkeypatch.setattr(OllamaClient, "prepare_model", fake_prepare)
    monkeypatch.setattr(OllamaClient, "_ensure_model_ready", fake_ready)
    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    OllamaClient(auto_prepare_model=False).chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
    )
    assert captured["prepared"] == []
    assert captured["readiness"] == []

    OllamaClient(auto_prepare_model=True).chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
    )
    assert captured["prepared"] == [("qwen-test", False)]
    assert captured["readiness"][0][0] == "qwen-test"



def test_automatic_model_prepare_has_no_process_kill_or_server_restart_path():
    import inspect

    source = inspect.getsource(OllamaClient.prepare_model)

    assert "kill_ollama" not in source
    assert "kill_ollama_model_processes" not in source
    assert "restart_ollama" not in source
    assert "unload_ollama_model" in source
    assert "can_control_model" in source



def test_external_consumer_probe_excludes_local_launcher_ancestors(monkeypatch):
    client = OllamaClient()
    captured = {}

    class Parent:
        def __init__(self, pid):
            self.pid = pid

    class Process:
        def __init__(self, pid):
            assert pid == os.getpid()

        def parents(self):
            return [Parent(43210), Parent(54321)]

    monkeypatch.setattr("app.ollama_client.psutil.Process", Process)

    def fake_list_external(*, timeout, exclude_pids):
        captured["timeout"] = timeout
        captured["exclude_pids"] = list(exclude_pids)
        return []

    monkeypatch.setattr(
        "app.ollama_client.list_external_ollama_consumers",
        fake_list_external,
    )

    assert client._external_consumers() == []
    assert os.getpid() in captured["exclude_pids"]
    assert 43210 in captured["exclude_pids"]
    assert 54321 in captured["exclude_pids"]


def test_external_consumer_probe_does_not_exclude_unrelated_clients(monkeypatch):
    client = OllamaClient()

    monkeypatch.setattr(
        client,
        "_local_process_family_pids",
        lambda: [os.getpid(), 43210],
    )

    def fake_list_external(*, timeout, exclude_pids):
        assert 99999 not in exclude_pids
        return [{
            "pid": 99999,
            "owner": "EINSTEIN",
            "model": "qwen-test",
        }]

    monkeypatch.setattr(
        "app.ollama_client.list_external_ollama_consumers",
        fake_list_external,
    )

    assert client._external_consumers() == [{
        "pid": 99999,
        "owner": "EINSTEIN",
        "model": "qwen-test",
    }]


def test_prepare_model_blocks_manual_other_model_before_destructive_switch(monkeypatch, tmp_path):
    client, _store = _desktop_client(tmp_path)
    touched = {"ps": False}

    monkeypatch.setattr(
        client,
        "_external_consumers",
        lambda: [{
            "pid": 901,
            "owner": "MANUAL",
            "model": "qwen3-coder:30b-a3b-q8_0",
        }],
    )

    def resident_other_model(_client, timeout):
        touched["ps"] = True
        return ["qwen3-coder:30b-a3b-q8_0"]

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        resident_other_model,
    )

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.prepare_model("gemma4:26b")

    assert "MANUAL" in str(exc.value)
    assert "qwen3-coder:30b-a3b-q8_0" in str(exc.value)
    assert touched["ps"] is True


def test_prepare_model_allows_visible_manual_client_only_for_same_target(
    monkeypatch,
    tmp_path,
):
    client, _store = _desktop_client(tmp_path)

    monkeypatch.setattr(
        client,
        "_external_consumers",
        lambda: [{
            "pid": 901,
            "owner": "MANUAL",
            "model": "qwen3-coder:30b-a3b-q8_0",
        }],
    )
    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["qwen3-coder:30b-a3b-q8_0"],
    )

    assert client.prepare_model("qwen3-coder:30b-a3b-q8_0") == []


def test_prepare_model_allows_resident_target_without_external_consumer_probe(
    monkeypatch,
    tmp_path,
):
    client, _store = _desktop_client(tmp_path)
    target = "eurollm:9b-q4"
    probe_calls = []
    unloaded = []

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: [target, "gemma4:26b"],
    )
    monkeypatch.setattr(
        client,
        "_external_consumers",
        lambda: probe_calls.append(True) or [{
            "pid": 901,
            "owner": "OTHER",
            "model": "",
        }],
    )
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda *_args, **_kwargs: unloaded.append(True),
    )

    assert client.prepare_model(target) == []
    assert probe_calls == []
    assert unloaded == []


def test_resident_eurollm_direct_fact_reaches_api_chat_despite_unknown_probe(
    monkeypatch,
):
    target = "eurollm:9b-q4"
    captured = {}
    client = OllamaClient(auto_prepare_model=True)

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: [target],
    )
    monkeypatch.setattr(
        client,
        "_external_consumers",
        lambda: (_ for _ in ()).throw(
            AssertionError("resident target must not probe external consumers")
        ),
    )

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    answer = client.chat_once(
        model=target,
        call_phase="model_inference",
        messages=[
            {"role": "system", "content": "Answer from evidence only."},
            {
                "role": "user",
                "content": (
                    "CURRENT USER REQUEST: Mikor írta Petőfi Sándor a Toldit?\n"
                    "AUTHORIZED EVIDENCE: A Toldi Arany János műve."
                ),
            },
        ],
    )

    assert answer == "ok"
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["model"] == target
    assert "think" not in captured["json"]


def test_automatic_prepare_never_unloads_a_different_resident_model(
    monkeypatch,
):
    target = "eurollm:9b-q4"
    captured = {}
    client = OllamaClient(auto_prepare_model=True)

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: ["gemma4:26b"],
    )
    monkeypatch.setattr(client, "_external_consumers", lambda: [])
    monkeypatch.setattr(
        "app.ollama_client.unload_ollama_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("automatic inference must not unload another model")
        ),
    )

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    assert client.chat_once(
        model=target,
        messages=[{"role": "user", "content": "ordinary factual request"}],
    ) == "ok"
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["model"] == target



def test_cold_model_is_warmed_before_user_chat(monkeypatch):
    target = "eurollm:9b-q4"
    loaded_states = iter([
        ["gemma4:26b"],  # prepare_model
        ["gemma4:26b"],  # readiness preflight
        [target],         # post-warmup readiness poll
    ])
    posts = []
    decisions = []

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: next(loaded_states),
    )
    monkeypatch.setattr(
        OllamaClient,
        "_external_consumers",
        lambda self: (_ for _ in ()).throw(
            AssertionError("non-destructive warmup must not probe external consumers")
        ),
    )

    def fake_post(url, **kwargs):
        posts.append((url, kwargs.get("json")))
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    result = OllamaClient(auto_prepare_model=True).chat_once(
        model=target,
        messages=[{"role": "user", "content": "Rövid kérdés."}],
        context_budget_callback=decisions.append,
    )

    assert result == "ok"
    assert posts[0][0].endswith("/api/generate")
    assert posts[0][1] == {
        "model": target,
        "prompt": "",
        "stream": False,
        "keep_alive": "5m",
    }
    assert posts[1][0].endswith("/api/chat")
    assert decisions[-1]["model_resident_before"] is False
    assert decisions[-1]["model_warmup_required"] is True
    assert decisions[-1]["model_warmup_reason"] == "cold_model"
    assert decisions[-1]["model_warmup_result"] == "ready"
    assert decisions[-1]["model_resident_after"] is True


def test_post_warmup_chat_retries_once_after_successful_http_parse_shape_failure(
    monkeypatch,
):
    target = "eurollm:9b-q4"
    loaded_states = iter([
        [],       # prepare_model
        [],       # readiness preflight
        [target], # readiness poll
    ])
    posts = []
    decisions = []

    class InvalidShapeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": None}

    responses = iter([
        _Response(),            # warmup
        InvalidShapeResponse(), # first user chat: HTTP 2xx, invalid payload shape
        _Response(),            # bounded retry succeeds
    ])

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: next(loaded_states),
    )

    def fake_post(url, **kwargs):
        posts.append(url)
        return next(responses)

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    result = OllamaClient(auto_prepare_model=True).chat_once(
        model=target,
        messages=[{"role": "user", "content": "test"}],
        context_budget_callback=decisions.append,
    )

    assert result == "ok"
    assert posts[0].endswith("/api/generate")
    assert posts[1].endswith("/api/chat")
    assert posts[2].endswith("/api/chat")
    assert decisions[-1]["post_warmup_retry_attempted"] is True
    assert decisions[-1]["post_warmup_retry_result"] == "success"


def test_large_resident_model_preflights_requested_context(monkeypatch):
    target = "eurollm:9b-q4"
    posts = []
    decisions = []

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: [target],
    )

    def fake_post(url, **kwargs):
        if url.endswith("/api/show"):
            return _ShowResponse(32768)
        posts.append((url, kwargs.get("json")))
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    result = OllamaClient(auto_prepare_model=True).chat_once(
        model=target,
        messages=[{"role": "user", "content": "evidence " * 1800}],
        num_predict=1024,
        context_budget_callback=decisions.append,
    )

    assert result == "ok"
    assert posts[0][0].endswith("/api/generate")
    assert posts[0][1]["options"]["num_ctx"] == 8192
    assert posts[1][0].endswith("/api/chat")
    assert posts[1][1]["options"]["num_ctx"] == 8192
    assert decisions[-1]["model_resident_before"] is True
    assert decisions[-1]["model_warmup_reason"] == "context_preflight"
    assert decisions[-1]["model_warmup_result"] == "ready"


def test_cold_model_warmup_http_failure_is_classified_separately(monkeypatch):
    class BadWarmupResponse:
        status_code = 400
        text = ""

        def json(self):
            return {}

        def raise_for_status(self):
            error = requests.HTTPError("Bad Request")
            error.response = self
            raise error

    monkeypatch.setattr(
        "app.ollama_client.loaded_ollama_models",
        lambda _client, timeout: [],
    )

    def fake_post(url, **kwargs):
        if url.endswith("/api/generate"):
            return BadWarmupResponse()
        raise AssertionError("user /api/chat must not run after failed warmup")

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)

    with pytest.raises(requests.HTTPError) as exc:
        OllamaClient(auto_prepare_model=True).chat_once(
            model="eurollm:9b-q4",
            messages=[{"role": "user", "content": "test"}],
        )

    metadata = ollama_failure_metadata(exc.value)
    assert metadata["ollama_failure_stage"] == "model_preparation"
    assert metadata["ollama_failure_classification"] == "model_warmup_failed"
    assert metadata["ollama_http_status"] == 400


def test_controlled_chat_once_uses_streaming_and_honors_budget(monkeypatch):
    import json

    from app.runtime_control import ExecutionBudget, ExecutionControl

    captured = {}

    class StreamResponse:
        def __init__(self):
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def close(self):
            self.closed = True

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({
                "message": {"content": "hello "},
                "done": False,
            }).encode("utf-8")
            yield json.dumps({
                "message": {"content": "world"},
                "done": True,
            }).encode("utf-8")

    response = StreamResponse()

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return response

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    control = ExecutionControl(
        budget=ExecutionBudget(timeout_seconds=60, max_model_calls=2)
    )

    result = OllamaClient().chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
        control=control,
    )

    assert result == "hello world"
    assert captured["json"]["stream"] is True
    assert "think" not in captured["json"]
    assert captured["stream"] is True
    assert control.budget.model_calls == 1



def test_controlled_structured_chat_once_accepts_complete_json_without_done_marker(monkeypatch):
    import json

    from app.runtime_control import ExecutionBudget, ExecutionControl

    captured = {}

    class StructuredStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({
                "message": {"content": '{"judgments":[[0,"pass"]]}'} ,
                "done": False,
            }).encode("utf-8")

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return StructuredStreamResponse()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    control = ExecutionControl(
        budget=ExecutionBudget(timeout_seconds=60, max_model_calls=2)
    )

    result = OllamaClient().chat_once(
        model="gemma4:26b",
        messages=[{"role": "user", "content": "audit this sentence"}],
        control=control,
        num_predict=512,
        call_phase="hungarian_fluency_audit",
        response_format="json",
    )

    assert result == '{"judgments":[[0,"pass"]]}'
    assert captured["json"]["stream"] is True
    assert captured["json"]["format"] == "json"
    assert captured["json"]["options"]["num_predict"] == 512
    assert captured["stream"] is True
    assert control.budget.model_calls == 1


def test_controlled_chat_once_closes_active_response_on_cancel(monkeypatch):
    import json

    from app.runtime_control import ExecutionControl

    control = ExecutionControl()

    class StreamResponse:
        def __init__(self):
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def close(self):
            self.closed = True

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({
                "message": {"content": "partial"},
                "done": False,
            }).encode("utf-8")
            control.cancellation.cancel()
            if not self.closed:
                yield json.dumps({
                    "message": {"content": "should-not-continue"},
                    "done": True,
                }).encode("utf-8")

    response = StreamResponse()
    monkeypatch.setattr(
        "app.ollama_client.requests.post",
        lambda *args, **kwargs: response,
    )

    result = OllamaClient().chat_once(
        model="qwen-test",
        messages=[{"role": "user", "content": "test"}],
        control=control,
    )

    assert response.closed is True
    assert "should-not-continue" not in result


def test_chat_stream_uses_normal_output_budget_and_returns_completion_metadata(
    monkeypatch,
):
    import json

    captured = {}

    class StreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({
                "message": {"content": "Kék Sárkány 7319"},
                "done": True,
                "done_reason": "stop",
                "eval_count": 12,
                "load_duration": 10_000_000,
                "prompt_eval_duration": 20_000_000,
                "eval_duration": 30_000_000,
                "total_duration": 70_000_000,
            }).encode("utf-8")

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return StreamResponse()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    tokens = []
    metadata = OllamaClient().chat_stream(
        model="qwen-test",
        messages=[{"role": "user", "content": "Recall the codename"}],
        on_token=tokens.append,
        should_stop=lambda: False,
    )

    assert captured["json"]["options"]["num_predict"] == 1024
    assert "stop" not in captured["json"]
    assert tokens == ["Kék Sárkány 7319"]
    assert metadata["done_reason"] == "stop"
    assert metadata["eval_count"] == 12
    assert metadata["load_duration"] == 10_000_000
    assert metadata["prompt_eval_duration"] == 20_000_000
    assert metadata["eval_duration"] == 30_000_000
    assert metadata["total_duration"] == 70_000_000


def test_chat_stream_accepts_a_bounded_per_request_output_budget(monkeypatch):
    import json

    captured = {}

    class StreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({
                "message": {"content": "complete"},
                "done": True,
                "done_reason": "stop",
            }).encode("utf-8")

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return StreamResponse()

    monkeypatch.setattr("app.ollama_client.requests.post", fake_post)
    OllamaClient().chat_stream(
        model="qwen-test",
        messages=[{"role": "user", "content": "long response"}],
        on_token=lambda _token: None,
        should_stop=lambda: False,
        num_predict=2048,
    )

    assert captured["json"]["options"]["num_predict"] == 2048


def test_chat_stream_rejects_length_truncated_response(monkeypatch):
    import json

    from app.ollama_client import IncompleteGenerationError

    class StreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({
                "message": {"content": "Megértettem. Jegyzem a tesztprojekt k"},
                "done": True,
                "done_reason": "length",
                "eval_count": 10,
            }).encode("utf-8")

    monkeypatch.setattr(
        "app.ollama_client.requests.post",
        lambda *_args, **_kwargs: StreamResponse(),
    )

    with pytest.raises(IncompleteGenerationError) as exc:
        OllamaClient().chat_stream(
            model="qwen-test",
            messages=[{"role": "user", "content": "Remember the codename"}],
            on_token=lambda _token: None,
            should_stop=lambda: False,
        )

    metadata = ollama_failure_metadata(exc.value)
    assert metadata["ollama_failure_stage"] == "generation_length"
    assert metadata["ollama_failure_classification"] == "output_token_limit"
    assert metadata["ollama_initial_request"] is True


def test_initial_model_preparation_failure_keeps_root_cause_classified(monkeypatch):
    client = OllamaClient(auto_prepare_model=True)

    def fail_prepare(_model, timeout=6.0, *, allow_model_release=True):
        raise OllamaResourceBusyError("runtime inspection unavailable")

    monkeypatch.setattr(client, "prepare_model", fail_prepare)

    with pytest.raises(OllamaResourceBusyError) as exc:
        client.chat_once(
            model="gemma4:26b",
            messages=[{"role": "user", "content": "long first request"}],
            num_predict=2048,
        )

    metadata = ollama_failure_metadata(exc.value)
    assert metadata["ollama_failure_stage"] == "model_preparation"
    assert metadata["ollama_failure_classification"] == "model_prepare_failed"
    assert metadata["ollama_request_sequence"] == 1
    assert metadata["ollama_initial_request"] is True
    assert metadata["ollama_preparation_reason"] == "runtime inspection unavailable"


def test_ollama_http_error_detail_is_bounded_and_exposed():
    response = requests.Response()
    response.status_code = 400
    response._content = (
        b'{"error":"prompt exceeds the configured context window"}'
    )
    exc = requests.HTTPError(
        "400 Client Error: Bad Request",
        response=response,
    )

    from app.ollama_client import _tag_ollama_failure

    _tag_ollama_failure(
        exc,
        stage="ollama_http",
        classification="http_status",
        request_sequence=1,
        call_phase="model_inference",
    )
    metadata = ollama_failure_metadata(exc)

    assert metadata["ollama_http_status"] == 400
    assert metadata["ollama_http_detail"] == (
        "prompt exceeds the configured context window"
    )
    assert metadata["ollama_call_phase"] == "model_inference"


def test_ollama_transport_failure_is_classified_for_retry_diagnostics(monkeypatch):
    client = OllamaClient()

    def fail_post(*_args, **_kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr("app.ollama_client.requests.post", fail_post)

    with pytest.raises(requests.ConnectionError) as exc:
        client.chat_once(
            model="gemma4:26b",
            messages=[{"role": "user", "content": "retry request"}],
            num_predict=2048,
        )

    metadata = ollama_failure_metadata(exc.value)
    assert metadata["ollama_failure_stage"] == "ollama_transport"
    assert metadata["ollama_failure_classification"] == "transport_connection"
    assert metadata["ollama_initial_request"] is True


def test_long_request_retry_succeeds_without_hiding_the_first_failure(monkeypatch):
    client = OllamaClient()
    calls = []

    def post_once_then_succeed(*_args, **_kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise requests.ConnectionError("cold transport unavailable")
        return _Response()

    monkeypatch.setattr("app.ollama_client.requests.post", post_once_then_succeed)

    with pytest.raises(requests.ConnectionError) as exc:
        client.chat_once(
            model="gemma4:26b",
            messages=[{"role": "user", "content": "long first request"}],
            num_predict=2048,
        )
    assert ollama_failure_metadata(exc.value)["ollama_request_sequence"] == 1

    result = client.chat_once(
        model="gemma4:26b",
        messages=[{"role": "user", "content": "long retry"}],
        num_predict=2048,
    )

    assert result == "ok"
    assert len(calls) == 2


def test_worker_request_trace_keeps_classified_ollama_failure(monkeypatch):
    def fail_post(*_args, **_kwargs):
        raise requests.ConnectionError("runtime is starting")

    monkeypatch.setattr("app.ollama_client.requests.post", fail_post)
    prompt = "Írj részletes magyar összefoglalót az MI működéséről."
    trace = RequestTrace("desktop")
    worker = AdaptiveChatWorker(
        OllamaClient(),
        "gemma4:26b",
        [{"role": "user", "content": prompt}],
        prompt,
        constraints=build_task_constraints(prompt),
        trace=trace,
        output_budget=2048,
    )
    errors = []
    worker.failed.connect(errors.append)

    worker.run()

    metadata = trace.snapshot()["metadata"]
    assert errors
    assert metadata["ollama_failure_stage"] == "ollama_transport"
    assert metadata["ollama_failure_classification"] == "transport_connection"
    assert metadata["ollama_initial_request"] is True
    assert metadata["ollama_call_phase"] == "primary_generation"


def test_chat_stream_rejects_response_without_terminal_completion(monkeypatch):
    import json

    from app.ollama_client import IncompleteGenerationError

    class StreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield json.dumps({
                "message": {"content": "A tesztprojekt kódneve"},
                "done": False,
            }).encode("utf-8")

    monkeypatch.setattr(
        "app.ollama_client.requests.post",
        lambda *_args, **_kwargs: StreamResponse(),
    )

    with pytest.raises(IncompleteGenerationError):
        OllamaClient().chat_stream(
            model="qwen-test",
            messages=[{"role": "user", "content": "Recall the codename"}],
            on_token=lambda _token: None,
            should_stop=lambda: False,
        )

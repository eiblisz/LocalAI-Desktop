import json
from pathlib import Path
import subprocess
import sys


def test_cold_production_startup_binds_bilingual_worker_before_gui_construction():
    repository_root = Path(__file__).resolve().parents[1]
    script = r'''
import json
import main
from app import main_window, workers

class Client:
    def __init__(self):
        self.calls = []

    def chat_once(self, model, messages, timeout=600.0, response_format=None):
        self.calls.append({
            "model": model,
            "response_format": response_format,
        })
        return json.dumps({
            "hu_query": "teaskanna 100 EUR alatt",
            "de_query": "Teekanne unter 100 EUR kaufen Deutschland",
        }, separators=(",", ":"))

client = Client()
worker = main_window.ChatWebWorker(
    client,
    "qwen-test",
    [{"role": "system", "content": "Base system"}],
    "Keress nekem teas kannat 100 EUR alatt.",
)
print(json.dumps({
    "patch_installed": getattr(
        workers.ChatWebWorker,
        "_bilingual_search_patch_installed",
        False,
    ),
    "gui_class_identity": main_window.ChatWebWorker is workers.ChatWebWorker,
    "method_module": workers.ChatWebWorker._generate_search_queries.__module__,
    "queries": worker._generate_search_queries(),
    "calls": client.calls,
}, separators=(",", ":"), sort_keys=True))
'''

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(completed.stdout)

    assert evidence["patch_installed"] is True
    assert evidence["gui_class_identity"] is True
    assert evidence["method_module"] == "app.bilingual_search_patch"
    assert evidence["queries"] == [
        "teaskanna 100 EUR alatt",
        "Teekanne unter 100 EUR kaufen Deutschland",
    ]
    assert len(evidence["calls"]) == 1
    assert evidence["calls"][0]["response_format"]["additionalProperties"] is False

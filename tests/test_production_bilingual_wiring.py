import json
from pathlib import Path
import subprocess
import sys


def test_cold_production_startup_uses_explicit_web_research_pipeline_before_gui_construction():
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
    "gui_class_identity": main_window.ChatWebWorker is workers.ChatWebWorker,
    "method_module": workers.ChatWebWorker._generate_search_queries.__module__,
    "pipeline_module": worker.web_research_pipeline.__class__.__module__,
    "pipeline_class": worker.web_research_pipeline.__class__.__name__,
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

    assert evidence["gui_class_identity"] is True
    assert evidence["method_module"] == "app.workers"
    assert evidence["pipeline_module"] == "app.web_research_pipeline"
    assert evidence["pipeline_class"] == "WebResearchPipeline"
    assert evidence["queries"] == [
        "teaskanna 100 EUR alatt",
        "Teekanne unter 100 EUR kaufen Deutschland",
    ]
    assert len(evidence["calls"]) == 1
    assert evidence["calls"][0]["response_format"]["additionalProperties"] is False

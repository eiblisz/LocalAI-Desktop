import os
from pathlib import Path

from .runtime_paths import ensure_runtime_layout, migrate_legacy_runtime_data, runtime_root


APP_NAME = "LOCAL AI"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
PREFERRED_LOCAL_MODEL = "gemma4:26b"
# Gemma's hidden reasoning can be expensive for ordinary chat requests.  Keep it
# off by default, while allowing an explicit operator opt-in for models/tasks
# where deliberately slower reasoning is wanted.
OLLAMA_THINKING_ENABLED = os.environ.get("LOCALAI_OLLAMA_THINK", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ROOT_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = runtime_root()
RUNTIME_PATHS = ensure_runtime_layout(RUNTIME_DIR)
migrate_legacy_runtime_data(ROOT_DIR, RUNTIME_DIR)

CHAT_DIR = RUNTIME_PATHS["chats"]
SCHEDULE_DIR = RUNTIME_PATHS["schedules"]
MEMORY_DIR = RUNTIME_PATHS["memory"]
MEMORY_CANONICAL_DIR = RUNTIME_PATHS["memory_canonical"]
MEMORY_BACKUP_DIR = RUNTIME_PATHS["memory_backups"]
EXTENSIONS_DIR = RUNTIME_PATHS["extensions"]
EXTENSION_CONFIG_DIR = RUNTIME_PATHS["extension_configs"]
OUTPUT_DIR = ROOT_DIR / "output"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful local AI assistant. Answer the user directly and clearly. "
    "Do not assume project-specific governance or repository rules unless the user "
    "explicitly provides them in the current conversation."
)

SUPPORTED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".log",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
}

from pathlib import Path

APP_NAME = "LOCAL AI"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

ROOT_DIR = Path(__file__).resolve().parent.parent
CHAT_DIR = ROOT_DIR / "data" / "chats"
OUTPUT_DIR = ROOT_DIR / "output"

CHAT_DIR.mkdir(parents=True, exist_ok=True)
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

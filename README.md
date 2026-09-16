# LocalAI Desktop

A standalone Windows desktop chat client for local Ollama models.

This project is intentionally independent from QuantAI and EinsteinAI.

## MVP features

- Modern dark desktop UI
- Ollama connection status
- Model selector populated from `/api/tags`
- Local chat with streaming responses
- Chat history saved locally as JSON
- File attachment support for text, PDF and DOCX
- Active quick tools: PDF, DOCX, Excel, HTML and Summary
- PDF / DOCX / HTML presets: `Red Professional` and `Red Executive`
- Styled Excel workbook generation
- Source modes: current conversation or custom topic
- Direct artifact actions: OPEN FILE / OPEN FOLDER
- Stop generation
- New chat

All quick-tool buttons are active. Custom-topic generation uses the selected local Ollama model, while current-conversation exports can be created directly where appropriate.

## Requirements

- Windows 10/11
- Python 3.11+
- Ollama running locally
- At least one Ollama model installed

Default Ollama endpoint: `http://127.0.0.1:11434`

## Quick start

```powershell
git clone https://github.com/eiblisz/LocalAI-Desktop.git
cd LocalAI-Desktop
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
python main.py
```

Or:

```powershell
.\run.ps1
```

## PDF behavior

Click `PDF` in the right sidebar and then `CREATE PDF`.

The current conversation is rendered into an A4 PDF using the selected preset.

`Red Professional` includes:
- dark red header
- white title
- clean body layout
- timestamp
- page numbering
- separate USER / ASSISTANT sections

Generated files are saved under `output\`.

## Safety boundary

The MVP is a chat client and document tool. It does not automatically execute shell commands, Git operations, repository changes, or arbitrary Python code.

Those capabilities can be added later as explicit opt-in tools.


## Artifact themes

LocalAI Desktop uses a shared artifact theme engine across PDF, DOCX, HTML and Excel.

Document presets:
- Red Professional
- Red Executive
- Classic Professional
- Classic Executive

Workbook presets:
- Red Executive Workbook
- Classic Workbook

Classic themes are designed for formal documents and printing: white backgrounds, charcoal text, restrained blue-grey accents, light borders and high readability. Red themes remain available for more visual reports.

Theme definitions live in `app/artifact_themes.py`, so additional families such as Minimal, Corporate Blue, Technical, Academic or Legal can be added without duplicating the artifact generators.


## Scheduled tasks

LocalAI Desktop includes a bounded scheduler for recurring local-model tasks.

Current MVP:
- Hourly schedules with a configurable interval.
- Daily schedules at a selected local time.
- RUN NOW for immediate execution.
- Persistent task storage under `data/schedules/tasks.json`.
- Results are written to a dedicated `[SCHEDULE] ...` chat.
- Scheduled work is postponed while a normal chat or document generation is using Ollama.

Internet access is permission-based. The first available external tool is Weather:
- Location lookup through Open-Meteo geocoding.
- Current conditions plus the next 12 hours of forecast data.
- The Ollama model receives only the returned tool data; it does not get arbitrary web access.

The scheduler currently runs while LocalAI Desktop is open. A separate Windows background/autostart runner can be added later for schedules that must continue after the GUI is closed.

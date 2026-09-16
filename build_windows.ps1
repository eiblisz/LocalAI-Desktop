$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -r requirements-dev.txt

& ".\.venv\Scripts\pyinstaller.exe" `
    --noconfirm `
    --windowed `
    --name "LocalAI-Desktop" `
    --collect-all reportlab `
    main.py

Write-Host ""
Write-Host "Build complete: dist\LocalAI-Desktop\LocalAI-Desktop.exe"

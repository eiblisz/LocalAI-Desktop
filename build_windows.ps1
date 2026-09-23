param(
    [string]$GitExe = "$env:ProgramFiles\Git\cmd\git.exe",
    [string]$ExpectedMainSha = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$MetadataPath = Join-Path $RepoRoot "app\_build_metadata.py"

if (-not (Test-Path -LiteralPath $GitExe -PathType Leaf)) {
    throw "Real Git executable not found at '$GitExe'. Pass -GitExe with the full path to git.exe."
}

$BuildSha = (& $GitExe -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $BuildSha -notmatch '^[0-9a-f]{40}$') {
    throw "Could not determine checkout HEAD with '$GitExe'."
}
if (-not $ExpectedMainSha) {
    $ExpectedMainSha = $BuildSha
}
$ExpectedMainSha = $ExpectedMainSha.Trim().ToLowerInvariant()
if ($ExpectedMainSha -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedMainSha must be a full 40-character commit SHA."
}

$PreviousMetadata = if (Test-Path -LiteralPath $MetadataPath) {
    Get-Content -LiteralPath $MetadataPath -Raw
} else {
    $null
}

Set-Content -LiteralPath $MetadataPath -Encoding ascii -Value @"
BUILD_SHA = "$BuildSha"
EXPECTED_MAIN_SHA = "$ExpectedMainSha"
"@

Push-Location $RepoRoot
try {
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
    Write-Host "Build SHA: $BuildSha"
    Write-Host "Expected main SHA: $ExpectedMainSha"
    Write-Host "Build complete: dist\LocalAI-Desktop\LocalAI-Desktop.exe"
}
finally {
    Pop-Location
    if ($null -eq $PreviousMetadata) {
        Remove-Item -LiteralPath $MetadataPath -ErrorAction SilentlyContinue
    } else {
        Set-Content -LiteralPath $MetadataPath -Encoding ascii -Value $PreviousMetadata -NoNewline
    }
}

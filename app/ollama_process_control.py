import json
import os
import re
import shutil
import subprocess
import time


class OllamaProcessControlError(RuntimeError):
    pass


def _creation_flags():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_powershell(script, timeout=8.0):
    if os.name != "nt":
        raise OllamaProcessControlError(
            "Ollama process controls are currently supported on Windows only."
        )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=float(timeout),
        creationflags=_creation_flags(),
        check=False,
    )
    if completed.returncode != 0:
        detail = " ".join(
            (completed.stderr or completed.stdout or "").split()
        )
        raise OllamaProcessControlError(
            detail or f"PowerShell exited with code {completed.returncode}."
        )
    return (completed.stdout or "").strip()


def _parse_json_rows(output):
    if not str(output or "").strip():
        return []
    payload = json.loads(output)
    if isinstance(payload, dict):
        payload = [payload]
    return payload if isinstance(payload, list) else []


def list_ollama_model_processes(timeout=5.0):
    """Return runner/model processes without mutating the shared runtime."""
    script = r"""
$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -ieq 'ollama.exe' -and $_.CommandLine -match '(?i)(^|\s)runner(\s|$)') -or
    ($_.Name -ieq 'ollama_llama_server.exe')
} | Select-Object ProcessId,Name,CommandLine
@($targets) | ConvertTo-Json -Compress
"""
    return [
        {
            "pid": int(row.get("ProcessId")),
            "name": str(row.get("Name") or ""),
            "command_line": str(row.get("CommandLine") or ""),
        }
        for row in _parse_json_rows(_run_powershell(script, timeout=timeout))
        if str(row.get("ProcessId") or "").isdigit()
    ]


def _extract_ollama_run_model(command_line):
    text = str(command_line or "")
    match = re.search(r'(?i)\brun\s+(?:"([^"]+)"|(\S+))', text)
    if not match:
        return ""
    return str(match.group(1) or match.group(2) or "").strip()


def _classify_ollama_consumer(name, command_line):
    name = str(name or "").lower()
    lowered = str(command_line or "").lower()
    if "einsteinai" in lowered:
        return "EINSTEIN"
    if "localai-desktop" in lowered and "scheduler" in lowered:
        return "SCHEDULER"
    if "localai-desktop" in lowered:
        return "LOCALAI_DESKTOP"
    if name == "ollama.exe" and re.search(r"(?i)\brun\b", lowered):
        return "MANUAL"
    return "OTHER"


def list_external_ollama_consumers(timeout=5.0, exclude_pids=None):
    """
    Best-effort active Ollama client discovery.

    In addition to known command-line clients, inspect established local TCP
    connections whose remote port is the Ollama API port. This catches direct
    HTTP clients that do not participate in the lease protocol.
    """
    script = r"""
$direct = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -ieq 'ollama.exe' -and $_.CommandLine -match '(?i)\brun\b') -or
    (($_.Name -ieq 'python.exe' -or $_.Name -ieq 'pythonw.exe') -and
        $_.CommandLine -match '(?i)EinsteinAI')
} | Select-Object ProcessId,Name,CommandLine

$connectionPids = @(
    Get-NetTCPConnection -RemotePort 11434 -State Established -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
$connected = foreach ($pidValue in $connectionPids) {
    Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue |
        Select-Object ProcessId,Name,CommandLine
}

$targets = @($direct) + @($connected)
$unique = @($targets | Where-Object { $_.ProcessId } | Sort-Object ProcessId -Unique)
$unique | ConvertTo-Json -Compress
"""
    excluded = {
        int(pid)
        for pid in (exclude_pids or [])
        if str(pid).isdigit() and int(pid) > 0
    }
    rows = _parse_json_rows(_run_powershell(script, timeout=timeout))
    result = []
    for row in rows:
        pid = row.get("ProcessId")
        if not str(pid or "").isdigit():
            continue
        pid = int(pid)
        if pid in excluded:
            continue
        name = str(row.get("Name") or "")
        command_line = str(row.get("CommandLine") or "")
        result.append(
            {
                "pid": pid,
                "name": name,
                "command_line": command_line,
                "owner": _classify_ollama_consumer(name, command_line),
                "model": _extract_ollama_run_model(command_line),
            }
        )
    return result

def kill_ollama_model_processes(pids=None, timeout=8.0):
    """
    Force-stop only explicitly authorized runner PIDs.

    Global runner discovery is intentionally not used as kill authority.
    """
    authorized = sorted(
        {
            int(pid)
            for pid in (pids or [])
            if str(pid).isdigit() and int(pid) > 0
        }
    )
    if not authorized:
        raise OllamaProcessControlError(
            "Model process kill blocked: no ownership-authorized PID was supplied."
        )

    pid_literal = ",".join(str(pid) for pid in authorized)
    script = rf"""
$authorized = @({pid_literal})
$targets = Get-CimInstance Win32_Process | Where-Object {{
    $authorized -contains [int]$_.ProcessId -and (
        ($_.Name -ieq 'ollama.exe' -and $_.CommandLine -match '(?i)(^|\s)runner(\s|$)') -or
        ($_.Name -ieq 'ollama_llama_server.exe')
    )
}}
$ids = @($targets | Select-Object -ExpandProperty ProcessId)
foreach ($pidValue in $ids) {{
    Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
}}
$ids -join ','
"""
    output = _run_powershell(script, timeout=timeout)
    return [
        int(value)
        for value in output.split(",")
        if value.strip().isdigit()
    ]


def kill_ollama(timeout=8.0):
    """Emergency global stop for Ollama server and runner processes."""
    script = r"""
$names = @('ollama.exe', 'ollama_llama_server.exe', 'ollama app.exe')
$targets = Get-CimInstance Win32_Process | Where-Object {
    $names -contains $_.Name.ToLower()
}
$ids = @($targets | Select-Object -ExpandProperty ProcessId)
foreach ($pidValue in $ids) {
    Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
}
$ids -join ','
"""
    output = _run_powershell(script, timeout=timeout)
    return [
        int(value)
        for value in output.split(",")
        if value.strip().isdigit()
    ]


def start_ollama(timeout=8.0):
    """Start an Ollama server using the executable available on PATH."""
    executable = shutil.which("ollama")
    if not executable:
        raise OllamaProcessControlError(
            "ollama.exe was not found on PATH."
        )
    process = subprocess.Popen(
        [executable, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=_creation_flags(),
    )
    time.sleep(min(0.6, max(0.0, float(timeout))))
    if process.poll() is not None:
        raise OllamaProcessControlError(
            f"Ollama exited immediately with code {process.returncode}."
        )
    return process.pid


def restart_ollama(timeout=12.0):
    killed = kill_ollama(timeout=min(float(timeout), 8.0))
    time.sleep(0.5)
    pid = start_ollama(timeout=max(2.0, float(timeout) - 1.0))
    return {"killed": killed, "started_pid": pid}

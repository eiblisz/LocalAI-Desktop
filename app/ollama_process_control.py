import os
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


def kill_ollama_model_processes(timeout=8.0):
    """Force-stop Ollama runner/model processes without killing the server."""
    script = r"""
$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -ieq 'ollama.exe' -and $_.CommandLine -match '(?i)(^|\s)runner(\s|$)') -or
    ($_.Name -ieq 'ollama_llama_server.exe')
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


def kill_ollama(timeout=8.0):
    """Force-stop Ollama server and runner processes."""
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

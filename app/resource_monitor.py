import subprocess
import sys

import psutil


def _parse_nvidia_smi_line(line: str) -> dict:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 3:
        raise ValueError("Unexpected nvidia-smi output")
    return {
        "gpu_percent": float(parts[0]),
        "vram_used_mb": float(parts[1]),
        "vram_total_mb": float(parts[2]),
    }


def get_system_metrics() -> dict:
    memory = psutil.virtual_memory()
    metrics = {
        "cpu_percent": float(psutil.cpu_percent(interval=None)),
        "ram_used_gb": memory.used / (1024 ** 3),
        "ram_total_gb": memory.total / (1024 ** 3),
        "ram_percent": float(memory.percent),
        "gpu_percent": None,
        "vram_used_mb": None,
        "vram_total_mb": None,
    }

    creationflags = 0
    if sys.platform.startswith("win") and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=True,
            creationflags=creationflags,
        )
        first_line = result.stdout.strip().splitlines()[0]
        metrics.update(_parse_nvidia_smi_line(first_line))
    except Exception:
        pass

    return metrics


def format_resource_summary(metrics: dict) -> str:
    cpu = metrics.get("cpu_percent", 0.0)
    ram_used = metrics.get("ram_used_gb", 0.0)
    ram_total = metrics.get("ram_total_gb", 0.0)
    ram_percent = metrics.get("ram_percent", 0.0)

    parts = [
        f"CPU {cpu:.0f}%",
        f"RAM {ram_used:.1f}/{ram_total:.0f} GB {ram_percent:.0f}%",
    ]

    gpu = metrics.get("gpu_percent")
    vram_used = metrics.get("vram_used_mb")
    vram_total = metrics.get("vram_total_mb")
    if gpu is not None:
        parts.append(f"GPU {gpu:.0f}%")
    if vram_used is not None and vram_total:
        parts.append(
            f"VRAM {vram_used / 1024:.1f}/{vram_total / 1024:.1f} GB"
        )

    return "   |   ".join(parts)

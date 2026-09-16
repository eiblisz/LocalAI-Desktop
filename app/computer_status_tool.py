import shutil
from datetime import datetime

from .resource_monitor import get_system_metrics


def get_computer_status():
    metrics = get_system_metrics()
    total, used, free = shutil.disk_usage("C:\\")

    metrics.update({
        "disk_used_gb": used / (1024 ** 3),
        "disk_total_gb": total / (1024 ** 3),
        "disk_free_gb": free / (1024 ** 3),
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
    })
    return metrics


def computer_status_context_text(metrics):
    lines = [
        "COMPUTER STATUS TOOL DATA",
        f"Retrieved: {metrics.get('retrieved_at', '')}",
        f"CPU usage: {metrics.get('cpu_percent', 0):.0f}%",
        (
            f"RAM usage: {metrics.get('ram_used_gb', 0):.1f}/"
            f"{metrics.get('ram_total_gb', 0):.1f} GB "
            f"({metrics.get('ram_percent', 0):.0f}%)"
        ),
    ]

    if metrics.get("gpu_percent") is not None:
        lines.append(f"GPU usage: {metrics['gpu_percent']:.0f}%")

    if metrics.get("vram_used_mb") is not None and metrics.get("vram_total_mb"):
        lines.append(
            f"VRAM usage: {metrics['vram_used_mb'] / 1024:.1f}/"
            f"{metrics['vram_total_mb'] / 1024:.1f} GB"
        )

    lines.append(
        f"Disk C: {metrics.get('disk_used_gb', 0):.1f}/"
        f"{metrics.get('disk_total_gb', 0):.1f} GB used; "
        f"{metrics.get('disk_free_gb', 0):.1f} GB free"
    )
    return "\n".join(lines)

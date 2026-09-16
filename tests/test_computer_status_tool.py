from app import computer_status_tool


def test_computer_status_context_contains_local_metrics(monkeypatch):
    monkeypatch.setattr(
        computer_status_tool,
        "get_system_metrics",
        lambda: {
            "cpu_percent": 25.0,
            "ram_used_gb": 16.0,
            "ram_total_gb": 64.0,
            "ram_percent": 25.0,
            "gpu_percent": 10.0,
            "vram_used_mb": 4096.0,
            "vram_total_mb": 12288.0,
        },
    )

    class Disk:
        total = 1024 ** 3 * 1000
        used = 1024 ** 3 * 400
        free = 1024 ** 3 * 600

        def __iter__(self):
            return iter((self.total, self.used, self.free))

    monkeypatch.setattr(
        computer_status_tool.shutil,
        "disk_usage",
        lambda path: Disk(),
    )

    metrics = computer_status_tool.get_computer_status()
    text = computer_status_tool.computer_status_context_text(metrics)

    assert "CPU usage: 25%" in text
    assert "RAM usage: 16.0/64.0 GB (25%)" in text
    assert "GPU usage: 10%" in text
    assert "VRAM usage: 4.0/12.0 GB" in text
    assert "Disk C:" in text

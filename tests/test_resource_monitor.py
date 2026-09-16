from app.resource_monitor import _parse_nvidia_smi_line, format_resource_summary


def test_parse_nvidia_smi_line():
    parsed = _parse_nvidia_smi_line("82, 9432, 12288")
    assert parsed["gpu_percent"] == 82
    assert parsed["vram_used_mb"] == 9432
    assert parsed["vram_total_mb"] == 12288


def test_format_resource_summary_with_gpu():
    text = format_resource_summary(
        {
            "cpu_percent": 23,
            "ram_used_gb": 15.1,
            "ram_total_gb": 64,
            "ram_percent": 24,
            "gpu_percent": 81,
            "vram_used_mb": 9728,
            "vram_total_mb": 12288,
        }
    )
    assert "CPU 23%" in text
    assert "RAM 15.1/64 GB 24%" in text
    assert "GPU 81%" in text
    assert "VRAM 9.5/12.0 GB" in text

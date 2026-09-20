import inspect
from pathlib import Path

from app import image_studio_patch
from app.main_window import MainWindow


def test_image_tool_is_installed_before_existing_artifact_tools():
    source = inspect.getsource(MainWindow._build_tools_panel)
    assert 'QPushButton("IMAGE")' in source
    assert "layout.insertWidget(1, button)" in source
    assert 'self.tool_buttons["IMAGE"]' in source


def test_image_studio_checks_existing_service_before_launch():
    source = inspect.getsource(MainWindow._open_image_studio)
    assert "if _comfyui_ready():" in source
    ready_branch = source.split("if _comfyui_ready():", 1)[1].split("if (", 1)[0]
    assert "_launch_comfyui" not in ready_branch
    assert "_release_vram" not in ready_branch


def test_image_studio_releases_vram_before_launch():
    source = inspect.getsource(MainWindow._open_image_studio)
    assert source.index("self._release_vram()") < source.index("_launch_comfyui(launcher)")


def test_image_studio_is_fail_closed_when_localai_busy():
    source = inspect.getsource(MainWindow._open_image_studio)
    assert 'getattr(self, "worker", None) is not None' in source
    assert 'getattr(self, "pdf_worker", None) is not None' in source
    assert 'getattr(self, "scheduled_worker", None) is not None' in source
    assert "LocalAI is busy" in source


def test_launcher_has_default_and_environment_override(monkeypatch):
    monkeypatch.delenv("LOCALAI_COMFYUI_LAUNCHER", raising=False)
    assert image_studio_patch._launcher_path() == Path(
        r"C:\ComicNewsAI\comfyui\ComfyUI_windows_portable\run_nvidia_gpu.bat"
    )
    monkeypatch.setenv("LOCALAI_COMFYUI_LAUNCHER", r"D:\ComfyUI\run.bat")
    assert image_studio_patch._launcher_path() == Path(r"D:\ComfyUI\run.bat")


def test_readiness_poll_has_bounded_timeout():
    source = inspect.getsource(MainWindow._poll_comfyui_ready)
    assert "remaining <= 0" in source
    assert "startup timeout" in source
    assert "remaining - 1" in source


def test_this_slice_does_not_implement_image_generation_api():
    source = inspect.getsource(image_studio_patch)
    assert "/prompt" not in source
    assert "Krea" not in source


def test_image_tool_matches_compact_tool_button_height():
    source = inspect.getsource(MainWindow._build_tools_panel)

    assert 'button.setFixedHeight(34)' in source


def test_image_tool_uses_shared_side_menu_style():
    source = inspect.getsource(MainWindow._build_tools_panel)

    assert 'button.setObjectName("sideMenuButton")' in source

import inspect
from pathlib import Path

from app import image_studio_controller
from app.image_studio_controller import ImageStudioController
from app.main_window import MainWindow


def test_main_window_delegates_image_studio_to_explicit_controller():
    init_source = inspect.getsource(MainWindow.__init__)
    open_source = inspect.getsource(MainWindow._open_image_studio)
    poll_source = inspect.getsource(MainWindow._poll_comfyui_ready)
    tools_source = inspect.getsource(MainWindow._build_tools_panel)

    assert "self.image_studio_controller = ImageStudioController(self)" in init_source
    assert "self.image_studio_controller.open()" in open_source
    assert "self.image_studio_controller.poll_ready(remaining)" in poll_source
    assert "self.image_studio_controller.install_tool_button(layout)" in tools_source


def test_image_tool_is_installed_before_existing_artifact_tools():
    source = inspect.getsource(ImageStudioController.install_tool_button)
    assert 'QPushButton("IMAGE")' in source
    assert "layout.insertWidget(1, button)" in source
    assert 'window.tool_buttons["IMAGE"]' in source


def test_image_studio_checks_existing_service_before_launch():
    source = inspect.getsource(ImageStudioController.open)
    assert "if comfyui_ready():" in source
    ready_branch = source.split("if comfyui_ready():", 1)[1].split("if (", 1)[0]
    assert "launch_comfyui" not in ready_branch
    assert "_release_vram" not in ready_branch


def test_image_studio_releases_vram_before_launch():
    source = inspect.getsource(ImageStudioController.open)
    assert source.index("window._release_vram()") < source.index("launch_comfyui(launcher)")


def test_image_studio_is_fail_closed_when_localai_busy():
    source = inspect.getsource(ImageStudioController.open)
    assert 'getattr(window, "worker", None) is not None' in source
    assert 'getattr(window, "pdf_worker", None) is not None' in source
    assert 'getattr(window, "scheduled_worker", None) is not None' in source
    assert "LocalAI is busy" in source


def test_launcher_has_default_and_environment_override(monkeypatch):
    monkeypatch.delenv("LOCALAI_COMFYUI_LAUNCHER", raising=False)
    assert image_studio_controller.launcher_path() == Path(
        r"C:\ComicNewsAI\comfyui\ComfyUI_windows_portable\run_nvidia_gpu.bat"
    )
    monkeypatch.setenv("LOCALAI_COMFYUI_LAUNCHER", r"D:\ComfyUI\run.bat")
    assert image_studio_controller.launcher_path() == Path(r"D:\ComfyUI\run.bat")


def test_readiness_poll_has_bounded_timeout():
    source = inspect.getsource(ImageStudioController.poll_ready)
    assert "remaining <= 0" in source
    assert "startup timeout" in source
    assert "remaining - 1" in source


def test_this_slice_does_not_implement_image_generation_api():
    source = inspect.getsource(image_studio_controller)
    assert "/prompt" not in source
    assert "Krea" not in source


def test_image_tool_matches_compact_tool_button_height_and_theme():
    source = inspect.getsource(ImageStudioController.install_tool_button)

    assert "button.setFixedHeight(34)" in source
    assert 'button.setObjectName("sideMenuButton")' in source
    assert "SIDE_MENU_BUTTON_STYLE" in source

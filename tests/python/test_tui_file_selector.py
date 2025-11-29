from pathlib import Path
from unittest.mock import MagicMock, patch

# 需要确保导入路径正确
import sys

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from ming_drlms.tui.file_selector import FileSelectionModal
from textual.widgets import Static


def test_file_selector_modal_init():
    """测试FileSelectionModal初始化逻辑"""
    # 指定路径
    path = Path("/tmp/test")
    modal = FileSelectionModal(path)
    assert modal.initial_path == path

    # 默认路径 (Home)
    modal_default = FileSelectionModal(None)
    assert modal_default.initial_path == Path.home()


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
def test_chat_screen_config_loading(MockController, MockConfigManager):
    """测试ChatScreen是否正确从配置加载路径"""
    from ming_drlms.tui.chat_screen import ChatScreen

    # 模拟配置: 指定路径
    mock_config = MagicMock()
    mock_config.tui.file_picker_root = "/tmp/custom_root"
    MockConfigManager.return_value.config = mock_config

    screen = ChatScreen("user", "host:1234")
    assert screen.file_picker_root == Path("/tmp/custom_root")


@patch("ming_drlms.tui.chat_screen.ConfigManager")
@patch("ming_drlms.tui.chat_screen.ChatController")
def test_chat_screen_default_path(MockController, MockConfigManager):
    """测试ChatScreen默认路径逻辑"""
    from ming_drlms.tui.chat_screen import ChatScreen

    # 模拟配置: 空字符串
    mock_config = MagicMock()
    mock_config.tui.file_picker_root = ""
    MockConfigManager.return_value.config = mock_config

    screen = ChatScreen("user", "host:1234")
    assert screen.file_picker_root == Path.cwd()


def test_file_selection_modal_file_and_directory_events(tmp_path: Path, monkeypatch):
    """文件/目录选择时，selected_file 与按钮/提示的更新逻辑。"""

    modal = FileSelectionModal(initial_path=tmp_path)

    class DummyStatic:
        def __init__(self) -> None:
            self.text = ""

        def update(self, value: str) -> None:  # type: ignore[override]
            self.text = value

    class DummyButton:
        def __init__(self) -> None:
            self.disabled: bool = True

    path_display = DummyStatic()
    upload_btn = DummyButton()

    def fake_query(selector, typ=None):  # type: ignore[no-untyped-def]
        if selector == "#selected-path":
            return path_display
        if selector == "#upload-button":
            return upload_btn
        raise KeyError(selector)

    monkeypatch.setattr(modal, "query_one", fake_query)

    # 选中文件
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    modal.on_directory_tree_file_selected(type("Evt", (), {"path": f})())  # type: ignore[arg-type]
    assert modal.selected_file == f
    assert str(f) in path_display.text
    assert upload_btn.disabled is False

    # 选择目录时，禁用上传并清空 selected_file
    d = tmp_path / "sub"
    d.mkdir()
    modal.on_directory_tree_directory_selected(type("Evt", (), {"path": d})())  # type: ignore[arg-type]
    assert modal.selected_file is None
    assert "directory" in path_display.text
    assert upload_btn.disabled is True


def test_file_selection_modal_action_select_and_cancel(tmp_path: Path, monkeypatch):
    modal = FileSelectionModal(initial_path=tmp_path)

    path_display = Static("")

    def fake_query(selector, typ=None):  # type: ignore[no-untyped-def]
        if selector == "#selected-path":
            return path_display
        return Static("")

    monkeypatch.setattr(modal, "query_one", fake_query)

    dismissed = {"value": None}

    def fake_dismiss(value):  # type: ignore[no-untyped-def]
        dismissed["value"] = value

    monkeypatch.setattr(modal, "dismiss", fake_dismiss)

    # 有效文件 -> 应返回该路径
    f = tmp_path / "ok.bin"
    f.write_bytes(b"x")
    modal.selected_file = f
    modal.action_select()
    assert dismissed["value"] == f

    # 非文件/None -> 不关闭，仅更新错误提示
    dismissed["value"] = None
    modal.selected_file = tmp_path  # 目录
    modal.action_select()
    assert dismissed["value"] is None
    txt = (
        path_display.render().plain
        if hasattr(path_display, "render")
        else str(path_display)
    )
    assert "Please select a valid file" in txt

    # 取消应返回 None
    modal.action_cancel()
    assert dismissed["value"] is None

from pathlib import Path
from unittest.mock import MagicMock, patch

# 需要确保导入路径正确
import sys

sys.path.insert(0, str(Path(__file__).parents[3] / "src"))

from ming_drlms.tui.file_selector import FileSelectionModal


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

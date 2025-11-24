"""File selector modal for TUI.

Provides a visual file browser for uploading files, following Forest theme design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Label, Static
from textual.binding import Binding


class FileSelectionModal(ModalScreen[Optional[Path]]):
    """Modal screen for visual file selection.

    Features:
    - DirectoryTree navigation with keyboard/mouse
    - Preview of selected path
    - Cancel/Upload actions
    - Forest theme styling
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "select", "Select File", priority=True),
    ]

    CSS = """
    FileSelectionModal {
        align: center middle;
    }
    
    #modal-container {
        width: 80;
        height: 24;
        background: $surface;
        border: double $primary;
        padding: 1 2;
    }
    
    #modal-header {
        height: 3;
        background: $surface-light;
        border-bottom: solid $primary;
        content-align: center middle;
        color: $primary;
        text-style: bold;
        padding: 0 2;
    }
    
    #file-tree {
        height: 1fr;
        border: solid $text-muted;
        margin: 1 0;
        background: $background;
    }
    
    #selected-path {
        height: 3;
        background: $surface-light;
        border: solid $secondary;
        padding: 0 2;
        color: $text;
        content-align-vertical: middle;
    }
    
    #button-bar {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    
    #cancel-button {
        margin-right: 2;
        background: $surface-light;
        color: $text-muted;
        border: solid $error;
    }
    
    #cancel-button:hover {
        background: $error;
        color: $background;
        text-style: bold;
    }
    
    #upload-button {
        background: $surface-light;
        color: $text-muted;
        border: solid $primary;
    }
    
    #upload-button:hover {
        background: $primary;
        color: $background;
        text-style: bold;
    }
    
    #upload-button:disabled {
        background: $surface;
        color: $text-muted;
        border: solid $text-muted;
        opacity: 0.5;
    }
    """

    def __init__(self, initial_path: Optional[Path] = None) -> None:
        """Initialize file selector.

        Args:
            initial_path: Starting directory (defaults to home directory)
        """
        super().__init__()
        self.initial_path = initial_path or Path.home()
        self.selected_file: Optional[Path] = None

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="modal-container"):
            # Header
            yield Label("🌲 Select File to Upload 🌲", id="modal-header")

            # Directory tree
            yield DirectoryTree(str(self.initial_path), id="file-tree")

            # Selected path display
            yield Static("No file selected", id="selected-path")

            # Button bar
            with Horizontal(id="button-bar"):
                yield Button("✕ Cancel", id="cancel-button")
                yield Button("📤 Upload", id="upload-button", disabled=True)

    def on_mount(self) -> None:
        """Focus the directory tree on mount."""
        self.query_one(DirectoryTree).focus()

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        """Handle file selection in the tree.

        Args:
            event: File selection event
        """
        self.selected_file = event.path

        # Update selected path display
        path_display = self.query_one("#selected-path", Static)
        path_display.update(f"📄 {self.selected_file}")

        # Enable upload button
        upload_btn = self.query_one("#upload-button", Button)
        upload_btn.disabled = False

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Handle directory selection (disable upload for directories).

        Args:
            event: Directory selection event
        """
        # Disable upload for directories
        self.selected_file = None

        path_display = self.query_one("#selected-path", Static)
        path_display.update(f"📁 {event.path} (directory - please select a file)")

        upload_btn = self.query_one("#upload-button", Button)
        upload_btn.disabled = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button press event
        """
        if event.button.id == "cancel-button":
            self.action_cancel()
        elif event.button.id == "upload-button":
            self.action_select()

    def action_cancel(self) -> None:
        """Cancel file selection."""
        self.dismiss(None)

    def action_select(self) -> None:
        """Confirm file selection."""
        if self.selected_file and self.selected_file.is_file():
            self.dismiss(self.selected_file)
        else:
            # Show error if somehow enabled without valid file
            path_display = self.query_one("#selected-path", Static)
            path_display.update("❌ Please select a valid file")

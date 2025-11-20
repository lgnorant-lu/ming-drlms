"""Theming system for DRLMS TUI.

Supports dynamic theme switching via CSS variables and Asset Abstraction.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
from .config import ConfigManager


@dataclass
class Theme:
    """Defines a TUI theme with colors and assets."""

    name: str
    colors: Dict[str, str]
    assets: Dict[str, str] = field(default_factory=dict)

    def to_css_variables(self) -> Dict[str, str]:
        """Convert theme colors to CSS variable dictionary."""
        return {f"{key}": value for key, value in self.colors.items()}

    def get_asset(self, asset_name: str, default: str = "?") -> str:
        """Get an asset (icon/text) by name."""
        return self.assets.get(asset_name, default)


# --- Themes ---

FOREST_THEME = Theme(
    name="forest",
    colors={
        "background": "#1d2021",  # Deep soil
        "surface": "#282828",  # Dark rock
        "surface-light": "#3c3836",  # Light wood
        "primary": "#b8bb26",  # Sprout green (Spring Grass)
        "secondary": "#8ec07c",  # Moss green (Forest Canopy)
        "accent": "#d3869b",  # Berry purple (Sweet Gem Berry)
        "highlight": "#fabd2f",  # Sun yellow (Gold)
        "water": "#59c9f1",  # Blue Jeans (Water)
        "success": "#b8bb26",  # Green
        "warning": "#fabd2f",  # Yellow
        "error": "#fb4934",  # Red
        "text": "#ebdbb2",  # Parchment
        "text-muted": "#a89984",  # Dry grass
        "border-focus": "#b8bb26",  # Green focus
        "border-normal": "#504945",  # Dark wood border
    },
    assets={
        "icon_home": "[🏡]",
        "icon_room": "[🌲]",
        "icon_deep": "[🍄]",
        "icon_user": "(o.o)",
        "arrow_right": "»",
        "prompt": "›",
        "decor_star": "*",
    },
)

CYBERPUNK_THEME = Theme(
    name="cyberpunk",
    colors={
        "background": "#0f111a",
        "surface": "#1a1d27",
        "surface-light": "#232733",
        "primary": "#00ff9d",
        "secondary": "#00e5ff",
        "accent": "#7d57ff",
        "highlight": "#00e5ff",
        "water": "#00e5ff",
        "success": "#00ff9d",
        "warning": "#ffeb3b",
        "error": "#ff0055",
        "text": "#e6f1ff",
        "text-muted": "#566981",
        "border-focus": "#00ff9d",
        "border-normal": "#364252",
    },
    assets={
        "icon_home": "[#]",
        "icon_room": "[+]",
        "icon_deep": "[=]",
        "icon_user": "(@)",
        "arrow_right": "»",
        "prompt": "_",
        "decor_star": "+",
    },
)


class ThemeManager:
    """Manages active theme, assets, and configuration."""

    def __init__(self, config_manager: Optional[ConfigManager] = None):
        self.config_manager = config_manager or ConfigManager()
        self.themes = {
            "forest": FOREST_THEME,
            "cyberpunk": CYBERPUNK_THEME,
        }
        # Load theme from config
        initial_theme = self.config_manager.config.tui.theme
        self.current_theme = self.themes.get(initial_theme, FOREST_THEME)

        # Apply custom color overrides
        self._apply_overrides()

    def _apply_overrides(self) -> None:
        """Apply user custom colors from config."""
        overrides = self.config_manager.config.tui.custom_colors
        if overrides:
            self.current_theme.colors.update(overrides)

    def get_css_variables(self) -> Dict[str, str]:
        """Get CSS variables for the current theme."""
        return self.current_theme.to_css_variables()

    def get_asset(self, name: str, default: str = "?") -> str:
        """Get asset from current theme."""
        return self.current_theme.get_asset(name, default)

    def set_theme(self, theme_name: str) -> None:
        """Switch the current theme and save to config."""
        if theme_name in self.themes:
            self.current_theme = self.themes[theme_name]
            self._apply_overrides()
            # Save preference
            self.config_manager.config.tui.theme = theme_name
            self.config_manager.save()
        else:
            raise ValueError(f"Theme '{theme_name}' not found.")

"""pywebview application launcher."""

from pathlib import Path

import webview

from retro_refiner.paths import get_runtime_path
from retro_refiner.ui.api import Api, _UI_STATE_FILENAME


def get_assets_dir() -> Path:
    """Return the path to the UI assets directory."""
    return Path(__file__).parent / 'assets'


def _load_geometry() -> dict:
    """Load saved window geometry from the unified state file."""
    from retro_refiner.config import load_config  # pylint: disable=import-outside-toplevel
    defaults = {'x': None, 'y': None, 'width': 1200, 'height': 800}
    path = get_runtime_path() / _UI_STATE_FILENAME
    if not path.exists():
        return defaults
    try:
        config = load_config(path)
        win = config.window
        return {
            'x': win.x,
            'y': win.y,
            'width': win.width or 1200,
            'height': win.height or 800,
        }
    except (OSError, ValueError):
        return defaults


def start_app():
    """Launch the Retro-Refiner GUI."""
    api = Api()
    assets = get_assets_dir()
    geo = _load_geometry()

    def on_closing():
        """Save UI state and window geometry when the window is closed."""
        try:
            api._config.window.x = window.x  # pylint: disable=protected-access
            api._config.window.y = window.y  # pylint: disable=protected-access
            api._config.window.width = window.width  # pylint: disable=protected-access
            api._config.window.height = window.height  # pylint: disable=protected-access
        except AttributeError:
            pass
        api.save_ui_state()

    window = webview.create_window(
        'Retro-Refiner',
        url=str(assets / 'index.html'),
        js_api=api,
        x=geo['x'],
        y=geo['y'],
        width=geo['width'],
        height=geo['height'],
        min_size=(900, 600),
    )
    window.events.closing += on_closing
    api.set_window(window)
    webview.start(debug=False)

"""pywebview application launcher."""

import json
from pathlib import Path

import webview

from retro_refiner.paths import get_runtime_path
from retro_refiner.ui.api import Api

_GEOMETRY_FILENAME = 'retro-refiner-window.json'


def get_assets_dir() -> Path:
    """Return the path to the UI assets directory."""
    return Path(__file__).parent / 'assets'


def _load_geometry() -> dict:
    """Load saved window geometry, returning defaults if unavailable."""
    defaults = {'x': None, 'y': None, 'width': 1200, 'height': 800}
    path = get_runtime_path() / _GEOMETRY_FILENAME
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return {
            'x': data.get('x'),
            'y': data.get('y'),
            'width': data.get('width', 1200),
            'height': data.get('height', 800),
        }
    except (OSError, ValueError, KeyError):
        return defaults


def _save_geometry(window):
    """Save current window position and size."""
    path = get_runtime_path() / _GEOMETRY_FILENAME
    try:
        data = {
            'x': window.x,
            'y': window.y,
            'width': window.width,
            'height': window.height,
        }
        path.write_text(json.dumps(data), encoding='utf-8')
    except (OSError, AttributeError):
        pass


def start_app():
    """Launch the Retro-Refiner GUI."""
    api = Api()
    assets = get_assets_dir()
    geo = _load_geometry()

    def on_closing():
        """Save UI state and window geometry when the window is closed."""
        _save_geometry(window)
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

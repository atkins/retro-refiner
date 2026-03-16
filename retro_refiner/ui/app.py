"""pywebview application launcher."""

from pathlib import Path

import webview

from retro_refiner.ui.api import Api


def get_assets_dir() -> Path:
    """Return the path to the UI assets directory."""
    return Path(__file__).parent / 'assets'


def start_app():
    """Launch the Retro-Refiner GUI."""
    api = Api()
    assets = get_assets_dir()

    window = webview.create_window(
        'Retro-Refiner',
        url=str(assets / 'index.html'),
        js_api=api,
        width=1200,
        height=800,
        min_size=(900, 600),
    )
    api.set_window(window)
    webview.start(debug=False)

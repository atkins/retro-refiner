"""pywebview application launcher."""

import sys
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


def _set_window_icon(window):
    """Set the window icon from the bundled ICO file (Windows only)."""
    if sys.platform != 'win32':
        return

    icon_path = get_assets_dir() / 'icon.ico'
    if not icon_path.exists():
        return

    try:
        import ctypes  # pylint: disable=import-outside-toplevel
        from ctypes import wintypes  # pylint: disable=import-outside-toplevel

        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040

        load_image = user32.LoadImageW
        load_image.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR,
            wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        load_image.restype = wintypes.HANDLE

        icon_str = str(icon_path.resolve())
        h_icon_sm = load_image(
            None, icon_str, IMAGE_ICON, 16, 16,
            LR_LOADFROMFILE | LR_DEFAULTSIZE)
        h_icon_lg = load_image(
            None, icon_str, IMAGE_ICON, 32, 32,
            LR_LOADFROMFILE | LR_DEFAULTSIZE)

        # Find the window handle by title
        hwnd = user32.FindWindowW(None, 'Retro-Refiner')
        if hwnd and h_icon_sm:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_icon_sm)
        if hwnd and h_icon_lg:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_icon_lg)
    except (OSError, AttributeError, ValueError):
        pass


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

    def on_shown():
        """Set window icon after the window is visible."""
        _set_window_icon(window)

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
    window.events.shown += on_shown
    api.set_window(window)
    webview.start(debug=False)

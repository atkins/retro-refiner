"""Python API exposed to JavaScript via pywebview."""

import json
import threading
import time
from pathlib import Path

import webview

from retro_refiner.config import Config, load_config, save_config
from retro_refiner.systems import load_system_data


class Api:
    """Bridge between the JavaScript frontend and Python backend."""

    def __init__(self):
        self._window = None
        self._config = Config()
        self._running = False
        self._systems_data = load_system_data()

    def set_window(self, window):
        """Store a reference to the pywebview window."""
        self._window = window

    def get_config(self) -> str:
        """Return current config as JSON."""
        return json.dumps(self._config.to_dict())

    def set_config(self, config_json: str):
        """Update config from JSON."""
        data = json.loads(config_json)
        self._config = Config.from_dict(data)

    def get_systems(self) -> str:
        """Return list of known systems as JSON."""
        return json.dumps(self._systems_data.known_systems)

    def save_settings(self, path: str):
        """Save current config to file."""
        save_config(self._config, Path(path))

    def load_settings(self, path: str) -> str:
        """Load config from file and return as JSON."""
        self._config = load_config(Path(path))
        return json.dumps(self._config.to_dict())

    def run_preview(self):
        """Start a preview run (no file transfer)."""
        if self._running:
            return
        self._running = True
        thread = threading.Thread(target=self._do_run, args=(False,), daemon=True)
        thread.start()

    def run_commit(self):
        """Start a commit run (with file transfer)."""
        if self._running:
            return
        self._running = True
        thread = threading.Thread(target=self._do_run, args=(True,), daemon=True)
        thread.start()

    def cancel_run(self):
        """Cancel the current run."""
        self._running = False

    def is_running(self) -> bool:
        """Return whether a run is currently in progress."""
        return self._running

    def _do_run(self, commit: bool):
        """Execute the run in a background thread."""
        try:
            mode = 'commit' if commit else 'preview'
            self._push_event('status', {
                'state': 'running',
                'message': f'Starting {mode} run...',
            })

            # Stub: will be wired to core modules in sub-project 6
            time.sleep(1)
            self._push_event('status', {
                'state': 'completed',
                'message': 'Done (stub)',
            })
        except Exception as exc:  # pylint: disable=broad-except
            self._push_event('status', {
                'state': 'error',
                'message': str(exc),
            })
        finally:
            self._running = False

    def _push_event(self, event_type: str, data: dict):
        """Push an event to the JavaScript frontend."""
        if self._window:
            payload = json.dumps({'type': event_type, 'data': data})
            self._window.evaluate_js(
                f'window.handlePythonEvent({payload})'
            )

    def browse_folder(self) -> str:
        """Open a folder browser dialog. Returns selected path or empty."""
        if self._window:
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG
            )
            if result and len(result) > 0:
                return result[0]
        return ''

    def browse_file(self, file_types=None) -> str:
        """Open a file browser dialog."""
        if self._window:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=file_types or ('All files (*.*)',),
            )
            if result and len(result) > 0:
                return result[0]
        return ''

    def save_file_dialog(self, file_types=None) -> str:
        """Open a save file dialog."""
        if self._window:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                file_types=file_types or ('YAML files (*.yaml)',),
            )
            if result:
                if isinstance(result, str):
                    return result
                return result[0] if result else ''
        return ''

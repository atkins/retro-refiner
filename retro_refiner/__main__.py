"""Entry point for retro_refiner package."""

import sys

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def check_gui():
    """Verify the GUI backend can load. Returns a process exit code.

    Packaging can silently drop a webview platform module: the build
    succeeds, the headless CLI works, and only opening a window fails.
    This walks the same import path ``start_app`` would -- pywebview's
    renderer selection -- without creating a window, so a broken bundle
    fails the build instead of the user.
    """
    try:
        # webview/__init__.py defines a module-level ``guilib = None`` that
        # overwrites the submodule attribute, so both ``import
        # webview.guilib`` and the ``as`` form hand back None. Go through
        # importlib to get the real module.
        import importlib  # pylint: disable=import-outside-toplevel
        guilib = importlib.import_module('webview.guilib')
        renderer = guilib.initialize()
    except BaseException as exc:  # pylint: disable=broad-except
        print(f'GUI backend check FAILED: {exc!r}', file=sys.stderr)
        return 1
    print(f'GUI backend OK: {getattr(renderer, "renderer", renderer)}')
    return 0


def main():
    """Route to GUI or headless mode based on arguments."""
    if '--check-gui' in sys.argv[1:]:
        sys.exit(check_gui())
    if any(arg in sys.argv[1:] for arg in ('--run', '--export-config', '--help-cli')):
        from retro_refiner.cli import run_headless  # pylint: disable=import-outside-toplevel
        run_headless(sys.argv[1:])
    else:
        from retro_refiner.ui.app import start_app  # pylint: disable=import-outside-toplevel
        start_app()


if __name__ == '__main__':
    main()

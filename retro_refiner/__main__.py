"""Entry point for retro_refiner package."""

import sys


def main():
    """Route to GUI or headless mode based on arguments."""
    if len(sys.argv) > 1 and sys.argv[1] == '--run':
        # Headless mode — cli module added in sub-project 8
        try:
            from retro_refiner.cli import run_headless  # pylint: disable=import-outside-toplevel
        except ImportError:
            print('Headless CLI mode is not yet available.', file=sys.stderr)
            sys.exit(1)
        run_headless(sys.argv[2:])
    else:
        # GUI mode (default)
        from retro_refiner.ui.app import start_app  # pylint: disable=import-outside-toplevel
        start_app()


if __name__ == '__main__':
    main()

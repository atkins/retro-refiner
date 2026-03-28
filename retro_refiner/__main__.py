"""Entry point for retro_refiner package."""

import sys

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def main():
    """Route to GUI or headless mode based on arguments."""
    if any(arg in sys.argv[1:] for arg in ('--run', '--export-config', '--help-cli')):
        from retro_refiner.cli import run_headless  # pylint: disable=import-outside-toplevel
        run_headless(sys.argv[1:])
    else:
        from retro_refiner.ui.app import start_app  # pylint: disable=import-outside-toplevel
        start_app()


if __name__ == '__main__':
    main()

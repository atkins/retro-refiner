"""Logging configuration for Retro-Refiner.

Two log channels:
- Visual log: _push_event('log', ...) to the GUI (unchanged)
- System log: loguru file sink for debug/development (this module)

All modules should import logger from here:
    from retro_refiner.log import logger
"""
import logging
import sys

from loguru import logger

# Remove loguru's default stderr handler
logger.remove()


class _LoguruHandler(logging.Handler):
    """Route stdlib logging records to loguru."""

    def emit(self, record):
        level = record.levelname
        logger.opt(depth=6, exception=record.exc_info).log(
            level, record.getMessage())


# Redirect pywebview logging to loguru (suppress console output)
_pywebview_logger = logging.getLogger('pywebview')
_pywebview_logger.handlers.clear()
_pywebview_logger.addHandler(_LoguruHandler())
_pywebview_logger.propagate = False

# Skip file sink during tests — don't pollute the production log
if 'pytest' not in sys.modules:
    from retro_refiner.paths import get_runtime_path  # pylint: disable=ungrouped-imports

    logger.add(
        get_runtime_path() / 'retro-refiner.log',
        level='DEBUG',
        rotation='10 MB',
        retention=3,
        format='{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | '
               '{module}:{function}:{line} | {message}',
        encoding='utf-8',
    )

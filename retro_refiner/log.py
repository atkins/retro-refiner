"""Logging configuration for Retro-Refiner.

Two log channels:
- Visual log: _push_event('log', ...) to the GUI (unchanged)
- System log: loguru file sink for debug/development (this module)

All modules should import logger from here:
    from retro_refiner.log import logger
"""
import sys

from loguru import logger

# Remove loguru's default stderr handler
logger.remove()

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

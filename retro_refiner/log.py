"""Logging configuration for Retro-Refiner.

Two log channels:
- Visual log: _push_event('log', ...) to the GUI (unchanged)
- System log: loguru file sink for debug/development (this module)

All modules should import logger from here:
    from retro_refiner.log import logger
"""
from loguru import logger

from retro_refiner.paths import get_runtime_path

# Remove loguru's default stderr handler
logger.remove()

# Always-on file sink — debug level, rotating, next to the executable
logger.add(
    get_runtime_path() / 'retro-refiner.log',
    level='DEBUG',
    rotation='10 MB',
    retention=3,
    format='{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {module}:{function}:{line} | {message}',
    encoding='utf-8',
)

# retro_refiner/__init__.py
"""Retro-Refiner: Refine your ROM collection down to the essentials."""

__version__ = "dev"

# Key exports for convenience
from retro_refiner.config import Config, load_config, save_config
from retro_refiner.systems import load_system_data, SystemData

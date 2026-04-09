"""Centralized logging configuration for api-to-tools.

By default, the library is silent (WARNING level, no handler).
Users can enable debug output by calling `enable_debug_logging()`
or by configuring the root logger in their application.
"""

from __future__ import annotations

import logging

# Root logger for the library
logger = logging.getLogger("api_to_tools")
logger.addHandler(logging.NullHandler())  # Silent by default


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the api_to_tools namespace."""
    return logging.getLogger(f"api_to_tools.{name}")


def enable_debug_logging() -> None:
    """Enable verbose debug output for the entire library."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

"""Central logging setup for dk_results entrypoints."""

from __future__ import annotations

import logging
import os

NOISY_LIBRARY_LOGGERS = ("googleapiclient.discovery", "urllib3")
_HANDLER_MARKER = "_dk_results_configured_handler"


def _resolve_level(default: str = "DEBUG") -> int:
    level_name = os.getenv("LOG_LEVEL", default).upper()
    return getattr(logging, level_name, logging.DEBUG)


def _configure_library_log_levels() -> None:
    for logger_name in NOISY_LIBRARY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.INFO)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger()
    for handler in logger.handlers:
        if getattr(handler, _HANDLER_MARKER, False):
            logger.setLevel(_resolve_level())
            _configure_library_log_levels()
            return logger

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        setattr(handler, _HANDLER_MARKER, True)
        logger.addHandler(handler)
    logger.setLevel(_resolve_level())
    _configure_library_log_levels()
    return logger

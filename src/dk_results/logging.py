"""Central logging setup for dk_results entrypoints."""

from __future__ import annotations

import logging
import logging.config
import os

from dk_results.paths import repo_file

NOISY_LIBRARY_LOGGERS = ("googleapiclient.discovery", "urllib3")


def _resolve_level(default: str = "DEBUG") -> int:
    level_name = os.getenv("LOG_LEVEL", default).upper()
    return getattr(logging, level_name, logging.DEBUG)


def _configure_library_log_levels() -> None:
    for logger_name in NOISY_LIBRARY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.INFO)


def configure_logging() -> logging.Logger:
    config_path = repo_file("logging.ini")
    if config_path.is_file():
        logging.config.fileConfig(str(config_path), disable_existing_loggers=False)
        logger = logging.getLogger()
        logger.setLevel(_resolve_level())
        _configure_library_log_levels()
        return logger

    logger = logging.getLogger()
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(_resolve_level())
    _configure_library_log_levels()
    return logger

"""Central logging setup for dk_results entrypoints."""

from __future__ import annotations

import logging
import os

NOISY_LIBRARY_LOGGERS = (
    "googleapiclient.discovery",
    "urllib3",
    "rookie.browser",
    "charset_normalizer",
    "google_auth_httplib2",
)
_HANDLER_MARKER = "_dk_results_configured_handler"


def _default_level() -> int:
    return logging.DEBUG if os.getenv("DK_PLATFORM", "").strip().lower() == "pi" else logging.INFO


def _resolve_level(level_override: str | int | None = None) -> int:
    if level_override is not None:
        if isinstance(level_override, int):
            return level_override
        level_name = str(level_override).upper()
        return getattr(logging, level_name, _default_level())

    env_level = os.getenv("LOG_LEVEL")
    if env_level:
        level_name = env_level.upper()
        return getattr(logging, level_name, _default_level())

    return _default_level()


def _configure_library_log_levels() -> None:
    for logger_name in NOISY_LIBRARY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.INFO)


def configure_logging(level_override: str | int | None = None) -> logging.Logger:
    logger = logging.getLogger()
    for handler in logger.handlers:
        if getattr(handler, _HANDLER_MARKER, False):
            logger.setLevel(_resolve_level(level_override))
            _configure_library_log_levels()
            return logger

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        setattr(handler, _HANDLER_MARKER, True)
        logger.addHandler(handler)
    logger.setLevel(_resolve_level(level_override))
    _configure_library_log_levels()
    return logger

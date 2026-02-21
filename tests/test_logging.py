import logging

import pytest

import dk_results.logging as app_logging


@pytest.fixture(autouse=True)
def _restore_logging_state():
    root = logging.getLogger()
    original_root_level = root.level
    original_handlers = list(root.handlers)
    original_library_levels = {name: logging.getLogger(name).level for name in app_logging.NOISY_LIBRARY_LOGGERS}
    yield
    for handler in list(root.handlers):
        if handler not in original_handlers:
            root.removeHandler(handler)
            handler.close()
    root.handlers.clear()
    for handler in original_handlers:
        root.addHandler(handler)
    root.setLevel(original_root_level)
    for name, level in original_library_levels.items():
        logging.getLogger(name).setLevel(level)


def test_configure_logging_applies_levels_and_idempotent_handler(monkeypatch):
    root = logging.getLogger()
    root.handlers.clear()
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    logging.getLogger("googleapiclient.discovery").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)

    logger = app_logging.configure_logging()
    assert logger is root
    assert root.level == logging.WARNING
    assert len(root.handlers) == 1
    assert logging.getLogger("googleapiclient.discovery").level == logging.INFO
    assert logging.getLogger("urllib3").level == logging.INFO

    logger = app_logging.configure_logging()

    assert logger is root
    assert len(root.handlers) == 1
    assert logging.getLogger("googleapiclient.discovery").level == logging.INFO
    assert logging.getLogger("urllib3").level == logging.INFO

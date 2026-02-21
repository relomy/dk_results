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


def test_configure_logging_applies_library_levels_with_file_config(monkeypatch, tmp_path):
    config_path = tmp_path / "logging.ini"
    config_path.write_text("[loggers]\nkeys=root\n", encoding="utf-8")

    calls = {"file_config": 0}

    monkeypatch.setattr(app_logging, "repo_file", lambda *_parts: config_path)
    monkeypatch.setattr(
        app_logging.logging.config,
        "fileConfig",
        lambda *_a, **_k: calls.__setitem__("file_config", calls["file_config"] + 1),
    )
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logging.getLogger("googleapiclient.discovery").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)

    logger = app_logging.configure_logging()

    assert calls["file_config"] == 1
    assert logger is logging.getLogger()
    assert logging.getLogger("googleapiclient.discovery").level == logging.INFO
    assert logging.getLogger("urllib3").level == logging.INFO


def test_configure_logging_applies_library_levels_without_file_config(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing.ini"
    monkeypatch.setattr(app_logging, "repo_file", lambda *_parts: missing_path)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    logging.getLogger("googleapiclient.discovery").setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.DEBUG)

    logger = app_logging.configure_logging()

    assert logger is logging.getLogger()
    assert logger.level == logging.WARNING
    assert logging.getLogger("googleapiclient.discovery").level == logging.INFO
    assert logging.getLogger("urllib3").level == logging.INFO

import importlib
import logging
import os
import sys

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


def test_configure_logging_honors_level_override_without_env_mutation(monkeypatch):
    root = logging.getLogger()
    root.handlers.clear()
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setenv("DK_PLATFORM", "linux")

    app_logging.configure_logging(level_override="WARNING")

    assert root.level == logging.WARNING
    assert "LOG_LEVEL" not in os.environ


def test_configure_logging_defaults_to_debug_on_pi(monkeypatch):
    root = logging.getLogger()
    root.handlers.clear()
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setenv("DK_PLATFORM", "pi")

    app_logging.configure_logging()

    assert root.level == logging.DEBUG


def test_importing_non_entrypoint_modules_does_not_call_configure_logging(monkeypatch):
    calls = {"count": 0}

    def _fake_configure_logging(*_args, **_kwargs):
        calls["count"] += 1
        return logging.getLogger()

    monkeypatch.setattr(app_logging, "configure_logging", _fake_configure_logging)

    module_names = [
        "dk_results.classes.player",
        "dk_results.classes.user",
        "dk_results.classes.optimizer",
        "dk_results.classes.contestdatabase",
    ]
    for name in module_names:
        sys.modules.pop(name, None)

    for name in module_names:
        importlib.import_module(name)

    assert calls["count"] == 0

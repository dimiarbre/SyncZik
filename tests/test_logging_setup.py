import logging
import logging.handlers

import pytest

from SyncZik.logging_setup import log_path, setup_logging


@pytest.fixture(autouse=True)
def tmp_xdg_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    yield
    # Remove any handler this test attached, so later tests (and the real
    # app) don't keep writing into this test's tmp_path forever.
    logger = logging.getLogger("SyncZik")
    for handler in list(logger.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            logger.removeHandler(handler)
            handler.close()


class TestLogPath:
    def test_respects_xdg_state_home(self, tmp_path):
        path = log_path()
        assert str(path).startswith(str(tmp_path))
        assert path.name == "synczik.log"


class TestSetupLogging:
    def test_creates_log_file_directory(self):
        path = setup_logging()
        assert path.parent.exists()

    def test_returns_the_log_path(self):
        assert setup_logging() == log_path()

    def test_does_not_attach_duplicate_handlers(self):
        setup_logging()
        setup_logging()
        logger = logging.getLogger("SyncZik")
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(file_handlers) == 1

    def test_verbose_sets_debug_level(self):
        setup_logging(verbose=True)
        assert logging.getLogger("SyncZik").level == logging.DEBUG

    def test_messages_are_written_to_the_file(self):
        path = setup_logging()
        logging.getLogger("SyncZik").error("boom")
        for handler in logging.getLogger("SyncZik").handlers:
            handler.flush()
        assert "boom" in path.read_text(encoding="utf-8")

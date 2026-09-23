"""File-based debug logging.

Both the TUI and the CLI only ever showed errors as ephemeral toasts/stderr
lines with no way to attach an actual trace to a bug report. This gives the
"SyncZik" logger tree a rotating file handler so there's always something
concrete to look at afterwards.

The log directory is a hand-rolled XDG-ish path for now (no new dependency
for one file); Phase 5's planned move to `platformdirs` for state/snapshots
will fold this in for proper cross-platform paths.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_LOGGER_NAME = "SyncZik"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3


def log_dir() -> Path:
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
    return base / "synczik" / "log"


def log_path() -> Path:
    return log_dir() / "synczik.log"


def setup_logging(verbose: bool = False) -> Path:
    """Attach a rotating file handler to the "SyncZik" logger, once.

    Safe to call more than once (e.g. from both the CLI and the TUI entry
    points) — it won't attach a duplicate handler. Returns the log file path.
    """
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)

    return path

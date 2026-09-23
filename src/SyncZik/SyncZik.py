import logging
import sys

from .cli import run_cli
from .tui import run as run_tui

_logger = logging.getLogger("SyncZik")


def main() -> None:
    exit_code = run_cli(sys.argv[1:])
    if exit_code is None:
        try:
            run_tui()
        except Exception:
            _logger.exception("Unhandled exception in TUI")
            raise
    else:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()

# Contributing to SyncZik

## Getting started

```bash
git clone <repo>
cd SyncZik
python3.12 -m venv venv-python3.12-SyncZik
source venv-python3.12-SyncZik/bin/activate
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

## Branch workflow

One branch per feature: `feature/<name>`. Commit freely on the feature branch; merge to `main` when the feature is complete and tests pass.

```bash
git checkout -b feature/my-feature
# ... work ...
git checkout main
git merge feature/my-feature
```

## Code style

- Python 3.12+, no third-party formatter required — just keep it readable.
- All intra-package imports must be **relative** (`from .syncer import Song`, not `from syncer import Song`). Bare module names break when the package is properly installed.
- No `sys.path.insert` in source or test files. The `setup.cfg` `pythonpath = src` directive handles test resolution.
- No comments that describe *what* the code does — only comments that explain *why* (non-obvious constraints, workarounds, subtle invariants).

## Adding a new streaming provider

1. Create `src/SyncZik/providers/<service>.py`.
2. Implement all methods of `ServiceProvider` (see `providers/base.py`).
3. The service name returned by `service_name` is used as the subdirectory key in `state/` and `snapshots/`.
4. Wire into the TUI: add an option to select the provider in `action_export_playlist` and `action_clone_playlist`.
5. Add tests under `tests/` — use `unittest.mock.MagicMock(spec=ServiceProvider)` as the pattern.

## Testing

All tests are pure unit tests — no API calls. Use `MagicMock(spec=ServiceProvider)` to mock providers. Tests run in a `tmp_path`-based working directory (`monkeypatch.chdir(tmp_path)`) so file I/O never touches the repo.

```python
# Pattern for a new test file
import pytest
from unittest.mock import MagicMock
from SyncZik.providers.base import ServiceProvider


@pytest.fixture(autouse=True)
def tmp_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
```

Integration tests (hitting real APIs) go in `tests/integration/` and must be decorated with `@pytest.mark.integration`. They are skipped in CI unless credentials are present.

## Cross-platform export

The export pipeline lives in `cross_platform.py`. When adding a new platform:

- `plan_export()` is already platform-agnostic — it uses `target_provider.search_tracks()`.
- `_normalize()` strips `(feat. ...)` and punctuation for title comparison. Add more normalization cases there if a new platform uses different formatting conventions.
- `execute_export()` uses `target_provider.create_playlist()` and `target_provider.add_songs()` — both abstract methods on `ServiceProvider`.

## Filing issues

Please include:
- Python version (`python --version`)
- The exact command or TUI action that failed
- The full traceback if applicable
- Which platform (Spotify / Deezer) was involved

"""Shared fixtures. Ensures no test ever touches the real emissions.db/csv."""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import pytest  # noqa: E402

import storage  # noqa: E402


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Redirects storage.DB_PATH (and everything that writes through it -
    cloud_impact.insert_row, carbon_run's SQLiteOutput) to an isolated file."""
    db_path = tmp_path / "test_emissions.db"
    monkeypatch.setattr(storage, "DB_PATH", str(db_path))
    return db_path


@pytest.fixture
def temp_hook_state(tmp_path, monkeypatch):
    import stop_hook

    state_dir = tmp_path / ".hook_state"
    error_log = tmp_path / "hook_errors.log"
    monkeypatch.setattr(stop_hook, "STATE_DIR", str(state_dir))
    monkeypatch.setattr(stop_hook, "ERROR_LOG", str(error_log))
    return state_dir, error_log

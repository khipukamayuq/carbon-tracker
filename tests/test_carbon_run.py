import sqlite3

import carbon_run


def test_usage_error_when_missing_separator(monkeypatch, temp_db):
    monkeypatch.setattr("sys.argv", ["carbon_run.py", "label-only"])
    assert carbon_run.main() == 2


def test_usage_error_when_no_command_after_separator(monkeypatch, temp_db):
    monkeypatch.setattr("sys.argv", ["carbon_run.py", "label", "--"])
    assert carbon_run.main() == 2


def test_wraps_command_and_writes_a_real_row(monkeypatch, temp_db):
    """Light integration smoke test - wraps a trivial real command and checks
    a row lands with the right label/duration, without pinning specific
    wattage values (those are real hardware measurements, not fixed constants)."""
    monkeypatch.setattr(
        "sys.argv", ["carbon_run.py", "pytest-smoke-test", "--", "sleep", "1"]
    )
    exit_code = carbon_run.main()
    assert exit_code == 0

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    row = dict(
        conn.execute(
            "SELECT * FROM emissions WHERE project_name = 'pytest-smoke-test'"
        ).fetchone()
    )
    conn.close()

    assert row["project_name"] == "pytest-smoke-test"
    assert float(row["duration"]) > 0

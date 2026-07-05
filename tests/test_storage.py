import csv
import sqlite3

import pytest

import storage


def _sample_row(**overrides):
    row = {name: "" for name in storage.FIELDNAMES}
    row.update(
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "project_name": "test-project",
            "run_id": "abc-123",
            "duration": "1.5",
            "energy_consumed": "0.001",
            "emissions": "0.0004",
            "on_cloud": "N",
        }
    )
    row.update(overrides)
    return row


def test_init_db_creates_all_fieldnames_columns(temp_db):
    storage.init_db()
    conn = sqlite3.connect(str(temp_db))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(emissions)")]
    conn.close()
    assert columns == storage.FIELDNAMES


def test_insert_row_round_trip(temp_db):
    row = _sample_row(project_name="round-trip-test")
    storage.insert_row(row)

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    result = conn.execute("SELECT * FROM emissions").fetchone()
    conn.close()

    assert dict(result)["project_name"] == "round-trip-test"
    # duration has REAL affinity, so it round-trips as an actual float, not
    # the original text - this is the point of the numeric-typed schema.
    assert dict(result)["duration"] == 1.5
    assert isinstance(dict(result)["duration"], float)


def test_connect_closes_the_connection(monkeypatch, temp_db):
    # sqlite3.Connection's own context manager only commits/rolls back, it
    # never closes - _connect() must close explicitly or every call leaks.
    # sqlite3.Connection is a C type (can't patch its methods directly), so
    # prove closure by capturing the real connections and using them after.
    opened = []
    real_connect = sqlite3.connect

    def _tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(storage.sqlite3, "connect", _tracking_connect)

    storage.insert_row({"project_name": "leak-check"})

    assert len(opened) == 2  # insert_row() calls init_db() internally
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_init_db_migrates_old_all_text_schema(temp_db):
    # Simulate a pre-migration DB: all columns TEXT, numeric values stored as
    # strings (this was the actual schema in production before this fix).
    conn = sqlite3.connect(str(temp_db))
    old_cols = ", ".join(f'"{n}" TEXT' for n in storage.FIELDNAMES)
    conn.execute(f"CREATE TABLE emissions ({old_cols})")
    colnames = ", ".join(f'"{n}"' for n in storage.FIELDNAMES)
    placeholders = ", ".join("?" for _ in storage.FIELDNAMES)
    row = ["" for _ in storage.FIELDNAMES]
    row[storage.FIELDNAMES.index("project_name")] = "pre-migration-row"
    row[storage.FIELDNAMES.index("energy_consumed")] = "0.0022848068474496863"
    row[storage.FIELDNAMES.index("cpu_count")] = "12"
    conn.execute(f"INSERT INTO emissions ({colnames}) VALUES ({placeholders})", row)
    conn.commit()
    conn.close()

    storage.init_db()  # should detect the old schema and migrate in place

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    types = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(emissions)")}
    assert types["energy_consumed"] == "REAL"
    assert types["cpu_count"] == "INTEGER"
    assert types["project_name"] == "TEXT"

    result = dict(conn.execute("SELECT * FROM emissions").fetchone())
    assert result["project_name"] == "pre-migration-row"
    assert result["energy_consumed"] == 0.0022848068474496863
    assert result["cpu_count"] == 12
    conn.close()

    # Calling init_db() again must be a no-op, not re-migrate or lose data.
    storage.init_db()
    conn = sqlite3.connect(str(temp_db))
    count = conn.execute("SELECT COUNT(*) FROM emissions").fetchone()[0]
    conn.close()
    assert count == 1


def test_insert_row_missing_fields_default_to_empty_string(temp_db):
    storage.insert_row({"project_name": "sparse-row"})
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    result = dict(conn.execute("SELECT * FROM emissions").fetchone())
    conn.close()
    assert result["project_name"] == "sparse-row"
    assert result["cpu_power"] == ""


def test_export_to_csv_round_trip(temp_db, tmp_path):
    storage.insert_row(_sample_row(project_name="proj-a", run_id="run-1"))
    storage.insert_row(_sample_row(project_name="proj-b", run_id="run-2"))

    csv_path = tmp_path / "out.csv"
    count = storage.export_to_csv(str(csv_path))
    assert count == 2

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == storage.FIELDNAMES
        rows = list(reader)

    assert len(rows) == 2
    assert {r["project_name"] for r in rows} == {"proj-a", "proj-b"}
    assert {r["run_id"] for r in rows} == {"run-1", "run-2"}


def test_export_to_csv_empty_db_writes_header_only(temp_db, tmp_path):
    csv_path = tmp_path / "empty.csv"
    count = storage.export_to_csv(str(csv_path))
    assert count == 0
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == storage.FIELDNAMES
        assert list(reader) == []


class _FakeEmissionsData:
    def __init__(self, values: dict):
        self.values = values


def test_sqlite_output_out_inserts_row(temp_db):
    handler = storage.SQLiteOutput()
    total = _FakeEmissionsData(
        {
            "project_name": "carbon-run-test",
            "run_id": "run-xyz",
            "energy_consumed": 0.002,
            "emissions": 0.0008,
        }
    )
    handler.out(total, None)

    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    result = dict(conn.execute("SELECT * FROM emissions").fetchone())
    conn.close()
    assert result["project_name"] == "carbon-run-test"
    assert result["run_id"] == "run-xyz"

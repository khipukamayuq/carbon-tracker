"""Single source of truth for persisting emissions rows.

SQLite (WAL mode) instead of CSV: CodeCarbon's own CSV writer does a full
read-modify-write on every save, unsafe against concurrent writers (e.g.
several Claude Code sessions' Stop hooks firing at once). carbonboard only
reads CSV, so export_to_csv() regenerates one on demand - the DB is the
source of truth, the CSV is a generated view.
"""

import contextlib
import csv
import os
import sqlite3

from codecarbon.output_methods.base_output import BaseOutput

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "emissions.db")

FIELDNAMES = [
    "timestamp",
    "project_name",
    "run_id",
    "experiment_id",
    "duration",
    "emissions",
    "emissions_rate",
    "cpu_power",
    "gpu_power",
    "ram_power",
    "cpu_energy",
    "gpu_energy",
    "ram_energy",
    "energy_consumed",
    "water_consumed",
    "country_name",
    "country_iso_code",
    "region",
    "cloud_provider",
    "cloud_region",
    "os",
    "python_version",
    "codecarbon_version",
    "cpu_count",
    "cpu_model",
    "gpu_count",
    "gpu_model",
    "longitude",
    "latitude",
    "ram_total_size",
    "tracking_mode",
    "cpu_utilization_percent",
    "gpu_utilization_percent",
    "ram_utilization_percent",
    "ram_used_gb",
    "on_cloud",
    "pue",
    "wue",
]

# Numeric columns need real REAL/INTEGER affinity, not TEXT - a TEXT column
# stores inserted numbers as their text representation, which both loses
# float precision on round-trip and sorts lexicographically ("10.2" before
# "9.5") rather than numerically. Anything not listed here defaults to TEXT.
_INTEGER_COLUMNS = {"cpu_count", "gpu_count"}
_REAL_COLUMNS = {
    "duration",
    "emissions",
    "emissions_rate",
    "cpu_power",
    "gpu_power",
    "ram_power",
    "cpu_energy",
    "gpu_energy",
    "ram_energy",
    "energy_consumed",
    "water_consumed",
    "longitude",
    "latitude",
    "ram_total_size",
    "cpu_utilization_percent",
    "gpu_utilization_percent",
    "ram_utilization_percent",
    "ram_used_gb",
    "pue",
    "wue",
}


def _column_type(name: str) -> str:
    if name in _INTEGER_COLUMNS:
        return "INTEGER"
    if name in _REAL_COLUMNS:
        return "REAL"
    return "TEXT"


@contextlib.contextmanager
def _connect():
    # sqlite3.Connection's own context manager only commits/rolls back, it
    # never closes - wrap it so every _connect() caller closes properly.
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _needs_migration(conn: sqlite3.Connection) -> bool:
    info = conn.execute("PRAGMA table_info(emissions)").fetchall()
    if not info:
        return False  # table doesn't exist yet - CREATE TABLE handles that
    current_types = {row[1]: row[2] for row in info}
    return any(current_types.get(name) != _column_type(name) for name in FIELDNAMES)


def init_db() -> None:
    columns_sql = ", ".join(f'"{name}" {_column_type(name)}' for name in FIELDNAMES)
    with _connect() as conn:
        if _needs_migration(conn):
            columns = ", ".join(f'"{name}"' for name in FIELDNAMES)
            conn.execute("ALTER TABLE emissions RENAME TO emissions_old")
            conn.execute(f"CREATE TABLE emissions ({columns_sql})")
            conn.execute(
                f"INSERT INTO emissions ({columns}) SELECT {columns} FROM emissions_old"
            )
            conn.execute("DROP TABLE emissions_old")
        else:
            conn.execute(f"CREATE TABLE IF NOT EXISTS emissions ({columns_sql})")


def insert_row(row: dict) -> None:
    init_db()
    columns = ", ".join(f'"{name}"' for name in FIELDNAMES)
    placeholders = ", ".join("?" for _ in FIELDNAMES)
    values = [row.get(name, "") for name in FIELDNAMES]
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO emissions ({columns}) VALUES ({placeholders})", values
        )


def export_to_csv(csv_path: str) -> int:
    """Regenerate csv_path from the DB. Returns the number of rows written."""
    init_db()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT {', '.join(FIELDNAMES)} FROM emissions ORDER BY rowid"
        ).fetchall()

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    return len(rows)


class SQLiteOutput(BaseOutput):
    """CodeCarbon custom output handler - see base_output.py's own docstring,
    which explicitly lists 'saving to a database' as an intended use case."""

    def out(self, total, delta) -> None:
        row = {name: "" for name in FIELDNAMES}
        row.update(dict(total.values))
        insert_row(row)

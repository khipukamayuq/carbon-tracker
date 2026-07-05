"""Single source of truth for persisting emissions rows.

Replaces direct CSV writes (both CodeCarbon's own FileOutput, which does a
full read-modify-write on every save, and our own csv.DictWriter appends)
with SQLite in WAL mode: safe concurrent writers from multiple processes
(e.g. several Claude Code sessions' Stop hooks firing around the same time),
without the O(n) full-file-rewrite cost that grows with every save.

carbonboard only knows how to read CSV, so export_to_csv() regenerates that
file on demand from the DB - the DB is the source of truth, the CSV is a
generated view for the dashboard.
"""
import csv
import os
import sqlite3

from codecarbon.output_methods.base_output import BaseOutput

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "emissions.db")

FIELDNAMES = [
    "timestamp", "project_name", "run_id", "experiment_id", "duration",
    "emissions", "emissions_rate", "cpu_power", "gpu_power", "ram_power",
    "cpu_energy", "gpu_energy", "ram_energy", "energy_consumed",
    "water_consumed", "country_name", "country_iso_code", "region",
    "cloud_provider", "cloud_region", "os", "python_version",
    "codecarbon_version", "cpu_count", "cpu_model", "gpu_count", "gpu_model",
    "longitude", "latitude", "ram_total_size", "tracking_mode",
    "cpu_utilization_percent", "gpu_utilization_percent",
    "ram_utilization_percent", "ram_used_gb", "on_cloud", "pue", "wue",
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    columns_sql = ", ".join(f'"{name}" TEXT' for name in FIELDNAMES)
    with _connect() as conn:
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

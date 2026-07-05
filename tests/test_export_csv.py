import csv

import export_csv
import storage


def test_export_csv_main_round_trip(monkeypatch, temp_db, tmp_path):
    row = {name: "" for name in storage.FIELDNAMES}
    row.update({"project_name": "export-test", "run_id": "run-1", "duration": "3.0"})
    storage.insert_row(row)

    out_path = tmp_path / "out.csv"
    monkeypatch.setattr("sys.argv", ["export_csv.py", str(out_path)])
    assert export_csv.main() == 0

    with open(out_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["project_name"] == "export-test"


def test_export_csv_main_defaults_to_base_dir_path(monkeypatch, temp_db, tmp_path):
    monkeypatch.setattr(export_csv, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.argv", ["export_csv.py"]
    )  # no explicit path -> use default
    assert export_csv.main() == 0
    assert (tmp_path / "emissions.csv").exists()

#!/usr/bin/env python3
"""Regenerate emissions.csv from emissions.db, for carbonboard (CSV-only) to read."""
import os
import sys

from storage import BASE_DIR, export_to_csv


def main() -> int:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "emissions.csv")
    count = export_to_csv(csv_path)
    print(f"Exported {count} rows to {csv_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regenerate emissions.csv from emissions.db, for carbonboard (CSV-only) to read."""

import argparse
import os
import sys

from storage import BASE_DIR, export_to_csv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=os.path.join(BASE_DIR, "emissions.csv"),
        help="output CSV path (default: emissions.csv next to this script)",
    )
    args = parser.parse_args()

    count = export_to_csv(args.csv_path)
    print(f"Exported {count} rows to {args.csv_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Wrap an arbitrary command with CodeCarbon's EmissionsTracker.

Usage: carbon_run.py <label> -- <command> [args...]
"""

import subprocess
import sys

from codecarbon import EmissionsTracker

from storage import SQLiteOutput


def main() -> int:
    # Manual parsing rather than argparse: argparse's nargs=REMAINDER can wrap
    # an arbitrary trailing command fine (tested - it passes through the
    # wrapped command's own flags correctly, with or without a literal '--'),
    # but that makes '--' optional, silently loosening the interface this
    # tool's tests currently enforce (omitting '--' is a usage error, exit 2).
    args = sys.argv[1:]
    if len(args) < 2 or args[1] != "--":
        print("Usage: carbon_run.py <label> -- <command> [args...]", file=sys.stderr)
        return 2

    label, command = args[0], args[2:]
    if not command:
        print("No command given after --", file=sys.stderr)
        return 2

    tracker = EmissionsTracker(
        project_name=label,
        output_handlers=[SQLiteOutput()],
        output_methods=[],
        allow_multiple_runs=True,
        log_level="warning",
    )
    tracker.start()
    try:
        result = subprocess.run(command)
    finally:
        tracker.stop()
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

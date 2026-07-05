#!/bin/zsh
# Run by the com.carbon-tracker.carbonboard launchd agent.
# Exports fresh CSV from the DB, then execs into carbonboard so launchd tracks
# the actual long-running process (needed for KeepAlive to work correctly).
CARBON_TRACKER_HOME="$HOME/dev/carbon-tracker"
"$CARBON_TRACKER_HOME/.venv/bin/python3" "$CARBON_TRACKER_HOME/export_csv.py" "$CARBON_TRACKER_HOME/emissions.csv"
exec "$CARBON_TRACKER_HOME/.venv/bin/carbonboard" --filepath="$CARBON_TRACKER_HOME/emissions.csv" --port=3333

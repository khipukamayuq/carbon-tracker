#!/bin/zsh
# Run by the com.carbon-tracker.carbonboard launchd agent. Uses exec so
# launchd tracks the actual carbonboard process (needed for KeepAlive).
CARBON_TRACKER_HOME="$HOME/dev/carbon-tracker"
"$CARBON_TRACKER_HOME/.venv/bin/python3" "$CARBON_TRACKER_HOME/export_csv.py" "$CARBON_TRACKER_HOME/emissions.csv"
exec "$CARBON_TRACKER_HOME/.venv/bin/carbonboard" --filepath="$CARBON_TRACKER_HOME/emissions.csv" --port=3333

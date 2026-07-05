# Sourced by ~/.zshrc for carbon-tracker tooling
# CARBON_TRACKER_HOME can be set before sourcing this file to relocate the
# toolkit; defaults to where it's always lived on this machine.
: "${CARBON_TRACKER_HOME:=$HOME/dev/carbon-tracker}"

carbon-run() {
  "$CARBON_TRACKER_HOME/.venv/bin/python3" "$CARBON_TRACKER_HOME/carbon_run.py" "$@"
}

cloud-impact() {
  "$CARBON_TRACKER_HOME/.venv/bin/python3" "$CARBON_TRACKER_HOME/cloud_impact.py" "$@"
}

codecarbon() {
  "$CARBON_TRACKER_HOME/.venv/bin/codecarbon" "$@"
}

carbon-test() {
  "$CARBON_TRACKER_HOME/.venv/bin/python3" -m pytest "$CARBON_TRACKER_HOME/tests" "$@"
}

carbonboard() {
  if [[ "$*" != *--filepath* ]]; then
    "$CARBON_TRACKER_HOME/.venv/bin/python3" "$CARBON_TRACKER_HOME/export_csv.py" "$CARBON_TRACKER_HOME/emissions.csv" || return 1
    "$CARBON_TRACKER_HOME/.venv/bin/carbonboard" --filepath="$CARBON_TRACKER_HOME/emissions.csv" "$@"
  else
    "$CARBON_TRACKER_HOME/.venv/bin/carbonboard" "$@"
  fi
}

# launchd-supervised carbonboard (always-on, port 3333). Auto-restarts on
# crash (KeepAlive) and by default starts at login (RunAtLoad). carbonboard
# only reads its CSV once at startup, so use carbonboard-restart to pick up
# newly-logged data.
_carbonboard_plist="$HOME/Library/LaunchAgents/com.carbon-tracker.carbonboard.plist"
_carbonboard_label="com.carbon-tracker.carbonboard"

carbonboard-status() {
  launchctl print "gui/$(id -u)/$_carbonboard_label"
}

carbonboard-restart() {
  launchctl kickstart -k "gui/$(id -u)/$_carbonboard_label"
}

carbonboard-stop() {
  launchctl bootout "gui/$(id -u)/$_carbonboard_label"
}

carbonboard-start() {
  launchctl bootstrap "gui/$(id -u)" "$_carbonboard_plist"
}

carbonboard-autostart() {
  local val="$1"
  if [[ "$val" != "true" && "$val" != "false" ]]; then
    echo "Usage: carbonboard-autostart true|false" >&2
    return 1
  fi
  /usr/libexec/PlistBuddy -c "Set :RunAtLoad $val" "$_carbonboard_plist" || return 1
  launchctl bootout "gui/$(id -u)/$_carbonboard_label" 2>/dev/null
  sleep 1  # launchd needs a moment to fully unregister the label before re-bootstrapping
  if ! launchctl bootstrap "gui/$(id -u)" "$_carbonboard_plist"; then
    echo "carbonboard-autostart: bootstrap failed, retrying once..." >&2
    sleep 2
    launchctl bootstrap "gui/$(id -u)" "$_carbonboard_plist" || {
      echo "carbonboard-autostart: bootstrap failed again; run 'carbonboard-start' manually" >&2
      return 1
    }
  fi
  echo "carbonboard autostart set to $val"
}

# carbon-tracker

[![100% Vibe_Coded](https://img.shields.io/badge/100%25-Vibe_Coded-ff69b4?style=for-the-badge&logo=claude&logoColor=white)](https://github.com/ai-ecoverse/vibe-coded-badge-action)

## Not suitable for actual use
This was a first pass at a carbon tracking tool for estimating GenAI power consumptions and emissions. There are fundamental problems with the implementation at this time, not least of which, was my own lack of understanding of the assumptions baked into EcoLogits wide margin for error when dealing with closed models such as Claude.

Local energy/carbon impact tracking for dev work, focused on Claude Code.

Local commands are *measured* and cloud LLM calls are *estimated*, but both paths
write rows into the same SQLite schema, so they can be exported to one CSV and
viewed side by side:

- **Real local measurement** via [CodeCarbon](https://github.com/mlco2/codecarbon)
  (`carbon-run`), with Apple Silicon `powermetrics` telemetry for real CPU/GPU wattage.
- **Cloud usage estimation** via [EcoLogits](https://github.com/genai-impact/ecologits)
  (`cloud-impact`), for compute that can't be measured locally (Anthropic's API).
  This is a pure offline estimator — no API key or network call required.
- **Automatic capture**: a Claude Code `Stop` hook logs real per-turn token usage as an
  EcoLogits estimate, silently and at zero token cost, on every turn.
- **Storage**: SQLite (WAL mode) as the source of truth, exported to CSV on demand for
  [`carbonboard`](https://github.com/mlco2/codecarbon) (CodeCarbon's local dashboard),
  optionally supervised via `launchd` for crash recovery and auto-start.

## Prerequisites

- An Apple Silicon Mac — the local-measurement path depends on `powermetrics`,
  which only reports CPU/GPU power draw this way on Apple Silicon.
- [`uv`](https://github.com/astral-sh/uv) (`brew install uv`).
- Passwordless `sudo` for `powermetrics`. CodeCarbon shells out to
  `sudo powermetrics` under the hood; if that prompts for a password, it
  doesn't error — it silently reports 0 for CPU/GPU power instead. Grant it
  once with:

  ```sh
  echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/powermetrics" | sudo tee /etc/sudoers.d/codecarbon-powermetrics
  sudo chmod 440 /etc/sudoers.d/codecarbon-powermetrics
  ```

## Setup

```sh
uv venv .venv --python 3.14
uv pip install --python .venv -r requirements.txt
```

`shell_init.sh` defaults `CARBON_TRACKER_HOME` to `~/dev/carbon-tracker`. If you
clone somewhere else, set `CARBON_TRACKER_HOME` before sourcing `shell_init.sh`
*and* edit the hardcoded path at the top of `run_carbonboard.sh` — launchd runs
that script standalone, so it doesn't inherit the env var.

Add sourcing to your shell profile so the commands below persist across
terminal sessions:

```sh
echo 'source /path/to/carbon-tracker/shell_init.sh' >> ~/.zshrc
```

## Usage

```sh
source shell_init.sh

carbon-run <label> -- <command>             # measure a local command
cloud-impact --label ... --provider ...     # log a manual cloud estimate
carbonboard                                 # launch the dashboard (foreground, ad hoc)
carbonboard-start                           # bootstrap the supervised (launchd) instance
carbonboard-status / -restart / -stop       # manage the supervised (launchd) instance
carbonboard-autostart true|false            # toggle RunAtLoad for the launchd instance
carbon-test                                 # run the test suite
carbon-lint                                 # ruff check + format --check
```

See `pytest.ini`/`tests/` for the test suite.

## Claude Code Stop hook

`stop_hook.py` logs real per-turn token usage as an EcoLogits estimate on every
Claude Code turn. It's not registered automatically — add it under `hooks.Stop`
in `~/.claude/settings.json` (replace `/path/to/carbon-tracker` with your clone
path, and use the venv's python so `codecarbon`/`ecologits` are importable):

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/carbon-tracker/.venv/bin/python3 /path/to/carbon-tracker/stop_hook.py",
            "timeout": 30,
            "async": true
          }
        ]
      }
    ]
  }
}
```

The hook never fails loudly or blocks Claude Code — errors are caught and
written to `hook_errors.log`, and it always exits 0.

## carbonboard supervision (launchd)

No `launchd` plist ships in this repo, so `carbonboard-start`/`-status`/
`-restart`/`-stop`/`-autostart` won't work until you create one. Save the
following as `~/Library/LaunchAgents/com.carbon-tracker.carbonboard.plist`
(replace `/path/to/carbon-tracker` with your clone path):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.carbon-tracker.carbonboard</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/carbon-tracker/run_carbonboard.sh</string>
  </array>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
```

Then run `carbonboard-start` once to bootstrap it. Use
`carbonboard-autostart true` to flip `RunAtLoad` on so it starts at login.

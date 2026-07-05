# carbon-tracker

[![100% Vibe_Coded](https://img.shields.io/badge/100%25-Vibe_Coded-ff69b4?style=for-the-badge&logo=claude&logoColor=white)](https://github.com/ai-ecoverse/vibe-coded-badge-action)

Local energy/carbon impact tracking for dev work on this machine, focused on Claude Code.

- **Real local measurement** via [CodeCarbon](https://github.com/mlco2/codecarbon)
  (`carbon-run`), with Apple Silicon `powermetrics` telemetry for real CPU/GPU wattage.
- **Cloud usage estimation** via [EcoLogits](https://github.com/genai-impact/ecologits)
  (`cloud-impact`), for compute that can't be measured locally (Anthropic's API).
- **Automatic capture**: a Claude Code `Stop` hook logs real per-turn token usage as an
  EcoLogits estimate, silently and at zero token cost, on every turn.
- **Storage**: SQLite (WAL mode) as the source of truth, exported to CSV on demand for
  [`carbonboard`](https://github.com/mlco2/codecarbon) (CodeCarbon's local dashboard),
  supervised via `launchd` for crash recovery and auto-start.

## Setup

```sh
uv venv .venv --python 3.14
uv pip install --python .venv -r requirements.txt
```

## Usage

```sh
source shell_init.sh

carbon-run <label> -- <command>            # measure a local command
cloud-impact --label ... --provider ...     # log a manual cloud estimate
carbonboard                                 # launch the dashboard (foreground, ad hoc)
carbonboard-status / -restart / -stop       # manage the supervised (launchd) instance
carbon-test                                 # run the test suite
```

See `pytest.ini`/`tests/` for the test suite, and `stop_hook.py` for the Claude Code
`Stop` hook (registered in `~/.claude/settings.json`).

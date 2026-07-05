#!/usr/bin/env python3
"""Claude Code Stop hook: logs real per-turn token usage as an EcoLogits
estimate via cloud_impact.log_estimate().

Reads the hook's stdin JSON (transcript_path, session_id), sums output_tokens
across all assistant transcript entries since the last time this hook ran for
that session.

Must never fail loudly or block Claude Code: all errors are caught and
written to hook_errors.log, and this always exits 0 with no stdout.
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

STATE_DIR = os.path.join(BASE_DIR, ".hook_state")
ERROR_LOG = os.path.join(BASE_DIR, "hook_errors.log")


def log_error(context: str) -> None:
    try:
        with open(ERROR_LOG, "a") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {context}\n")
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass  # if we can't even log the error, just give up silently


def state_path(session_id: str) -> str:
    return os.path.join(STATE_DIR, f"{session_id}.json")


def load_last_offset(session_id: str) -> int:
    try:
        with open(state_path(session_id)) as f:
            return json.load(f).get("line_offset", 0)
    except FileNotFoundError:
        return 0


def save_offset(session_id: str, line_offset: int) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(session_id), "w") as f:
        json.dump({"line_offset": line_offset}, f)


def main() -> None:
    payload = json.load(sys.stdin)
    session_id = payload["session_id"]
    transcript_path = payload["transcript_path"]

    with open(transcript_path) as f:
        lines = f.readlines()

    last_offset = load_last_offset(session_id)
    new_lines = lines[last_offset:]

    total_output_tokens = 0
    model = None
    first_ts, last_ts = None, None

    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        usage = entry.get("message", {}).get("usage")
        if not usage:
            continue

        total_output_tokens += usage.get("output_tokens", 0)
        model = entry.get("message", {}).get("model", model)

        ts = entry.get("timestamp")
        if ts:
            if first_ts is None:
                first_ts = ts
            last_ts = ts

    if total_output_tokens == 0 or model is None:
        save_offset(session_id, len(lines))  # nothing to log, safe to advance
        return

    latency = 1.0
    if first_ts and last_ts:
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        try:
            delta = (
                datetime.strptime(last_ts, fmt) - datetime.strptime(first_ts, fmt)
            ).total_seconds()
            latency = max(delta, 1.0)
        except ValueError:
            pass

    from cloud_impact import NoEstimateAvailable, log_estimate

    try:
        log_estimate("claude-code", "anthropic", model, total_output_tokens, latency)
    except NoEstimateAvailable as e:
        # Genuinely unregistered model - retrying won't help, advance past it.
        log_error(f"session={session_id} model={model}: {e}")
        save_offset(session_id, len(lines))
    except Exception:
        # Unexpected failure (e.g. a real bug): don't advance the offset, so
        # this data is retried next Stop instead of silently dropped.
        log_error(
            f"session={session_id} model={model}: unexpected error, will retry next turn"
        )
    else:
        save_offset(session_id, len(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error("stop_hook.py top-level failure")
    sys.exit(0)

import io
import json
import subprocess
import sys
from unittest.mock import MagicMock

import stop_hook


def _assistant_line(model, output_tokens, timestamp):
    return json.dumps({
        "type": "assistant",
        "message": {"model": model, "usage": {"output_tokens": output_tokens}},
        "timestamp": timestamp,
    })


def test_load_last_offset_defaults_to_zero_when_no_state_file(temp_hook_state):
    assert stop_hook.load_last_offset("some-session") == 0


def test_save_and_load_offset_round_trip(temp_hook_state):
    stop_hook.save_offset("session-abc", 42)
    assert stop_hook.load_last_offset("session-abc") == 42


def _write_transcript(tmp_path, lines):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def _run_main_with_payload(monkeypatch, transcript_path, session_id="test-session"):
    payload = json.dumps({"session_id": session_id, "transcript_path": transcript_path})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    stop_hook.main()


def test_main_sums_output_tokens_across_assistant_entries(monkeypatch, temp_hook_state, tmp_path):
    transcript = _write_transcript(tmp_path, [
        _assistant_line("claude-sonnet-5", 10, "2026-01-01T00:00:00.000000Z"),
        _assistant_line("claude-sonnet-5", 20, "2026-01-01T00:00:05.000000Z"),
        _assistant_line("claude-sonnet-5", 30, "2026-01-01T00:00:10.000000Z"),
    ])
    mock_log_estimate = MagicMock()
    monkeypatch.setattr("cloud_impact.log_estimate", mock_log_estimate)

    _run_main_with_payload(monkeypatch, transcript)

    mock_log_estimate.assert_called_once()
    args = mock_log_estimate.call_args[0]
    assert args[0] == "claude-code"
    assert args[1] == "anthropic"
    assert args[3] == 60  # summed output_tokens


def test_main_picks_last_model_when_multiple_present(monkeypatch, temp_hook_state, tmp_path):
    transcript = _write_transcript(tmp_path, [
        _assistant_line("claude-sonnet-5", 10, "2026-01-01T00:00:00.000000Z"),
        _assistant_line("claude-opus-4-8", 10, "2026-01-01T00:00:05.000000Z"),
    ])
    mock_log_estimate = MagicMock()
    monkeypatch.setattr("cloud_impact.log_estimate", mock_log_estimate)

    _run_main_with_payload(monkeypatch, transcript)

    assert mock_log_estimate.call_args[0][2] == "claude-opus-4-8"


def test_main_skips_malformed_json_lines(monkeypatch, temp_hook_state, tmp_path):
    transcript = _write_transcript(tmp_path, [
        "{not valid json at all",
        _assistant_line("claude-sonnet-5", 15, "2026-01-01T00:00:00.000000Z"),
    ])
    mock_log_estimate = MagicMock()
    monkeypatch.setattr("cloud_impact.log_estimate", mock_log_estimate)

    _run_main_with_payload(monkeypatch, transcript)  # must not raise

    mock_log_estimate.assert_called_once()
    assert mock_log_estimate.call_args[0][3] == 15


def test_main_advances_offset_so_rerun_with_no_new_lines_logs_nothing(monkeypatch, temp_hook_state, tmp_path):
    transcript = _write_transcript(tmp_path, [
        _assistant_line("claude-sonnet-5", 10, "2026-01-01T00:00:00.000000Z"),
    ])
    mock_log_estimate = MagicMock()
    monkeypatch.setattr("cloud_impact.log_estimate", mock_log_estimate)

    _run_main_with_payload(monkeypatch, transcript, session_id="rerun-session")
    assert mock_log_estimate.call_count == 1

    _run_main_with_payload(monkeypatch, transcript, session_id="rerun-session")
    assert mock_log_estimate.call_count == 1  # no new lines since last run


def test_main_no_op_when_no_assistant_usage_entries(monkeypatch, temp_hook_state, tmp_path):
    transcript = _write_transcript(tmp_path, [
        json.dumps({"type": "user", "message": {"content": "hi"}}),
    ])
    mock_log_estimate = MagicMock()
    monkeypatch.setattr("cloud_impact.log_estimate", mock_log_estimate)

    _run_main_with_payload(monkeypatch, transcript)

    mock_log_estimate.assert_not_called()


def test_script_exits_zero_silently_for_missing_transcript():
    """Exercises the real top-level try/except guard (not just main()) via
    subprocess, matching how this was manually verified during development."""
    payload = json.dumps({
        "session_id": "missing-transcript-test",
        "transcript_path": "/nonexistent/path/transcript.jsonl",
    })
    result = subprocess.run(
        [sys.executable, stop_hook.__file__],
        input=payload, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout == ""

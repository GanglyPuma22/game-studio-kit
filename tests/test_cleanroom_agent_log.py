"""Agent-log attribution for structured (Codex JSONL) transcripts."""

import json
from pathlib import Path
import tempfile
import unittest

from studio_tools import cleanroom
from test_cleanroom_host import MB, WINDOW, snap

OPTIONS = {"busy_cpu_seconds": 1.0, "heavy_working_set_bytes": 200 * MB}


class CodexAgentLogTests(unittest.TestCase):
    def compare(self, lines):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "codex.jsonl"
            log.write_text("\n".join(lines), encoding="utf-8")
            return cleanroom.compare(snap([]), snap([]), WINDOW, agent_log=log, **OPTIONS)

    def events(self, *events):
        return self.compare([json.dumps(e) for e in events])

    def test_quoted_history_and_passive_events_do_not_count(self):
        result = self.events(
            {"timestamp": "2026-09-10T09:59:00Z", "type": "response_item", "payload": {
                "type": "function_call", "arguments": "old 2026-09-10T10:02:00 and 2026-09-10T10:03:00Z"}},
            {"timestamp": "2026-09-10T10:02:00Z", "type": "response_item", "payload": {"type": "custom_tool_call_output"}},
            {"timestamp": "2026-09-10T10:02:00Z", "type": "response_item", "payload": {"type": "function_call_output"}},
            {"timestamp": "2026-09-10T10:02:00Z", "type": "event_msg", "payload": {"type": "token_count"}},
            {"timestamp": "2026-09-10T10:02:00Z", "type": "event_msg", "payload": {"type": "user_message"}},
            {"timestamp": "2026-09-10T10:02:00Z", "type": "response_item", "payload": {"type": "message", "role": "user"}},
        )
        self.assertTrue(result["attributable"], result["reasons"])
        log = result["contamination"]["agent_log"]
        self.assertEqual((log["timestamps_in_window"], log["naive_timestamps"]), (0, 0))

    def test_agent_actions_inside_the_window_count(self):
        for payload in [{"type": "function_call"}, {"type": "custom_tool_call"},
                        {"type": "message", "role": "assistant"}, {"type": "reasoning"}]:
            with self.subTest(payload=payload):
                result = self.events({"timestamp": "2026-09-10T10:02:00Z", "type": "response_item", "payload": payload})
                self.assertFalse(result["attributable"])
                self.assertIn("agent activity logged inside the window", result["reasons"])

    def test_unknown_event_types_still_count(self):
        result = self.events({"timestamp": "2026-09-10T10:02:00Z", "type": "something_new"})
        self.assertFalse(result["attributable"])

    def test_plain_text_lines_are_scanned_as_before(self):
        result = self.compare(["started 2026-09-10T10:02:00Z", json.dumps({"no": "timestamp 2026-09-10T10:03:00Z"})])
        self.assertEqual(result["contamination"]["agent_log"]["timestamps_in_window"], 2)
        self.assertFalse(result["attributable"])

    def test_non_string_event_time_falls_back_to_the_whole_line(self):
        result = self.events({"timestamp": 1757498520, "note": "2026-09-10T10:02:00Z"})
        self.assertEqual(result["contamination"]["agent_log"]["timestamps_in_window"], 1)


if __name__ == "__main__":
    unittest.main()

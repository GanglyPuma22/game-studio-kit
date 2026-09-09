"""Behavioral policy tests for the optional supervised Blender MCP route."""

import asyncio
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from studio_tools.blender_mcp import (
    call_current_addon_status,
    load_explicit_server_config,
    require_current_native_status,
)
from studio_tools.common import StudioError
from studio_tools.config import load
from studio_tools.doctor import inspect


CURRENT = {
    "up_to_date": True,
    "protocol_version": 5,
    "expected_protocol_version": 5,
    "source": "native",
    "telemetry_consent": False,
}


class BlenderMcpPolicyTests(unittest.TestCase):
    def test_current_status_requires_native_matching_protocol_and_telemetry_off(self):
        self.assertEqual(require_current_native_status(CURRENT)["protocol_version"], 5)
        invalid = (
            {**CURRENT, "source": "cached"},
            {**CURRENT, "protocol_version": 4},
            {**CURRENT, "expected_protocol_version": 4},
            {**CURRENT, "telemetry_consent": True},
            {**CURRENT, "up_to_date": False},
        )
        for status in invalid:
            with self.subTest(status=status):
                with self.assertRaises(StudioError):
                    require_current_native_status(status)

    def test_documented_stale_status_gets_exactly_one_read_only_retry(self):
        responses = [
            {
                "source": "error",
                "warning": (
                    "Addon handshake failed: Connection to Blender lost: "
                    "[WinError 10053]"
                ),
            },
            CURRENT,
        ]
        calls = []

        async def call(tool, arguments):
            calls.append((tool, arguments))
            return responses.pop(0)

        result = asyncio.run(call_current_addon_status(call, ensure_passed=True))
        self.assertEqual(result, CURRENT)
        self.assertEqual(calls, [("get_addon_status", {}), ("get_addon_status", {})])

    def test_retry_requires_successful_ensure_and_matching_stale_shape(self):
        for ensure_passed, first in (
            (False, {"source": "error", "warning": "[WinError 10053]"}),
            (True, {"source": "error", "warning": "connection timed out"}),
        ):
            calls = []

            async def call(tool, arguments):
                calls.append(tool)
                return first

            with self.subTest(ensure_passed=ensure_passed, first=first):
                with self.assertRaises(StudioError):
                    asyncio.run(
                        call_current_addon_status(call, ensure_passed=ensure_passed)
                    )
                self.assertEqual(calls, ["get_addon_status"])

    def test_second_invalid_status_stops_without_another_retry(self):
        stale = {"source": "error", "warning": "Connection to Blender lost"}
        responses = [stale, stale]
        calls = []

        async def call(tool, arguments):
            calls.append(tool)
            return responses.pop(0)

        with self.assertRaises(StudioError):
            asyncio.run(call_current_addon_status(call, ensure_passed=True))
        self.assertEqual(calls, ["get_addon_status", "get_addon_status"])

    def test_stale_words_from_non_error_status_do_not_retry(self):
        calls = []

        async def call(tool, arguments):
            calls.append((tool, arguments))
            return {"source": "native", "warning": "Connection to Blender lost"}

        with self.assertRaises(StudioError):
            asyncio.run(call_current_addon_status(call, ensure_passed=True))
        self.assertEqual(calls, [("get_addon_status", {})])

    def test_transport_exception_is_not_retried(self):
        calls = []

        async def call(tool, arguments):
            calls.append((tool, arguments))
            raise ConnectionError("transport closed")

        with self.assertRaises(ConnectionError):
            asyncio.run(call_current_addon_status(call, ensure_passed=True))
        self.assertEqual(calls, [("get_addon_status", {})])


class BlenderMcpConfigDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name in ("blender.exe", "python.exe", "blender-mcp.exe"):
            (root / name).touch()
        self.block = {
            "working_root": str(root / "runs"),
            "blender_executable": str(root / "blender.exe"),
            "probe_python": str(root / "python.exe"),
            "owner": "studio-blender-test",
            "server": {
                "command": str(root / "blender-mcp.exe"),
                "args": [],
                "env": {
                    "BLENDER_HOST": "127.0.0.1",
                    "BLENDER_PORT": "9876",
                    "DISABLE_TELEMETRY": "true",
                    "BLENDER_MCP_DISABLE_TELEMETRY": "true",
                },
            },
        }

    def test_explicit_config_is_reported_without_implying_native_validation(self):
        config = load(overrides={"blender_mcp": self.block})
        report = inspect(config)["capabilities"]["blender_mcp"]
        self.assertEqual(report["status"], "configured")
        self.assertTrue(report["configured"])
        self.assertFalse(report["version_verified"])
        self.assertEqual(report["interactive_status"], "unverified")

    def test_missing_block_is_needs_setup(self):
        report = inspect(load())["capabilities"]["blender_mcp"]
        self.assertEqual(report["status"], "needs_setup")
        self.assertFalse(report["configured"])
        self.assertIn(
            "skills/studio-blender/references/windows-lifecycle-qualification.md",
            report["next_step"],
        )

    def test_config_rejects_non_loopback_or_telemetry_enabled_server(self):
        for env_update in (
            {"BLENDER_HOST": "0.0.0.0"},
            {"BLENDER_PORT": "9999"},
            {"DISABLE_TELEMETRY": "false"},
            {"BLENDER_MCP_DISABLE_TELEMETRY": "false"},
        ):
            block = {**self.block, "server": {**self.block["server"]}}
            block["server"]["env"] = {**self.block["server"]["env"], **env_update}
            with self.subTest(env_update=env_update):
                with self.assertRaises(StudioError):
                    load(overrides={"blender_mcp": block})

    def test_config_rejects_empty_command_or_non_string_environment(self):
        for server_update in (
            {"command": ""},
            {"env": {**self.block["server"]["env"], "EXTRA": 1}},
        ):
            block = {**self.block, "server": {**self.block["server"], **server_update}}
            with self.subTest(server_update=server_update):
                with self.assertRaises(StudioError):
                    load(overrides={"blender_mcp": block})

    def test_working_root_cannot_be_inside_installed_kit(self):
        block = {
            **self.block,
            "working_root": str(Path(__file__).resolve().parents[1] / "runs"),
        }
        with self.assertRaisesRegex(StudioError, "outside the installed kit"):
            load(overrides={"blender_mcp": block})

    def test_probe_server_config_comes_only_from_explicit_host_file(self):
        host = Path(self.temp.name) / "host.json"
        host.write_text(__import__("json").dumps({"blender_mcp": self.block}))
        self.assertEqual(load_explicit_server_config(host), self.block["server"])
        with self.assertRaises(StudioError):
            load_explicit_server_config(None)

    def test_relocated_probe_imports_kit_from_unrelated_working_directory(self):
        stub = Path(self.temp.name) / "stub"
        (stub / "mcp" / "client").mkdir(parents=True)
        (stub / "mcp" / "__init__.py").write_text(
            "class ClientSession: pass\nclass StdioServerParameters: pass\n"
        )
        (stub / "mcp" / "client" / "__init__.py").touch()
        (stub / "mcp" / "client" / "stdio.py").write_text(
            "def stdio_client(*a, **k): pass\n"
        )
        probe = (
            Path(__file__).resolve().parents[1]
            / "skills/studio-blender/scripts/lifecycle/probe_mcp.py"
        )
        result = subprocess.run(
            [sys.executable, "-B", str(probe), "--help"],
            cwd=self.temp.name,
            env={**os.environ, "PYTHONPATH": str(stub)},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--server-config", result.stdout)

    def test_config_requires_all_explicit_lifecycle_identity_fields(self):
        for field in (
            "working_root",
            "blender_executable",
            "probe_python",
            "owner",
            "server",
        ):
            block = dict(self.block)
            del block[field]
            with self.subTest(field=field):
                with self.assertRaises(StudioError):
                    load(overrides={"blender_mcp": block})

    def test_owner_identity_uses_argument_safe_identifier(self):
        for owner in ("has spaces", "quote'", 'quote"', "", "x" * 129):
            block = {**self.block, "owner": owner}
            with self.subTest(owner=owner):
                with self.assertRaises(StudioError):
                    load(overrides={"blender_mcp": block})
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.block["owner"]))


if __name__ == "__main__":
    unittest.main()

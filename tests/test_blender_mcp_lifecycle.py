"""Behavioral policy tests for the optional supervised Blender MCP route."""

import asyncio
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio_tools.blender_mcp import (
    call_current_addon_status,
    load_explicit_server_config,
    require_current_native_status,
)
from studio_tools.common import StudioError
from studio_tools.config import load
from studio_tools.doctor import inspect


ROOT = Path(__file__).resolve().parents[1]


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
            {**CURRENT, "up_to_date": "false"},
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
        # blender_mcp identity paths are Windows-only (see
        # _is_absolute_lifecycle_path); these are never resolved against
        # the real filesystem by config.py, so plain Windows-style strings
        # are enough to exercise the validator on any host.
        self.block = {
            "working_root": "C:\\StudioHost\\blender-mcp-runs",
            "blender_executable": "C:\\StudioHost\\blender.exe",
            "probe_python": "C:\\StudioHost\\blender-mcp-1.9.1\\Scripts\\python.exe",
            "owner": "studio-blender-test",
            "server": {
                "command": "C:\\StudioHost\\blender-mcp-1.9.1\\Scripts\\blender-mcp.exe",
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
        # The kit checkout on this test host has a POSIX path, which can
        # never be a prefix of a Windows-only working_root value; patch the
        # kit-root lookup to a Windows-style stand-in so this exercises the
        # same comparison a real Windows install would perform.
        with patch(
            "studio_tools.config._kit_root",
            return_value=Path("C:\\Tools\\game-studio-kit"),
        ):
            block = {**self.block, "working_root": "C:\\Tools\\game-studio-kit\\runs"}
            with self.assertRaisesRegex(StudioError, "outside the installed kit"):
                load(overrides={"blender_mcp": block})

    def test_lifecycle_identity_paths_must_be_absolute(self):
        for field in ("working_root", "blender_executable", "probe_python"):
            block = {**self.block, field: f"relative/{field}"}
            with self.subTest(field=field):
                with self.assertRaisesRegex(StudioError, f"blender_mcp.{field} must be absolute"):
                    load(overrides={"blender_mcp": block})

    def test_lifecycle_identity_paths_reject_drive_relative_windows_forms(self):
        # `C:foo` has a drive but no root, so it is relative to the current
        # directory on that drive; it must be rejected on every host, not
        # just on Windows where `Path(...).is_absolute()` would also miss it.
        for field in ("working_root", "blender_executable", "probe_python"):
            block = {**self.block, field: "C:foo"}
            with self.subTest(field=field):
                with self.assertRaisesRegex(StudioError, f"blender_mcp.{field} must be absolute"):
                    load(overrides={"blender_mcp": block})

    def test_lifecycle_identity_paths_reject_drive_less_posix_style_roots(self):
        # The supervised lifecycle only runs on native Windows; a drive-less
        # root such as `/runs` is not a path that host can resolve, even
        # though `Path(...).is_absolute()` would accept it on a POSIX host.
        for field in ("working_root", "blender_executable", "probe_python"):
            block = {**self.block, field: "/x/y"}
            with self.subTest(field=field):
                with self.assertRaisesRegex(StudioError, f"blender_mcp.{field} must be absolute"):
                    load(overrides={"blender_mcp": block})

    def test_lifecycle_identity_paths_accept_windows_absolute_form_on_linux(self):
        # `Path(...).is_absolute()` on this Linux test host returns False for
        # `C:\...`, which is a real absolute path on the Windows hosts this
        # config targets. Use fields with no other filesystem-existence or
        # kit-relative check so this exercises only the absolute-path contract.
        for field in ("blender_executable", "probe_python"):
            block = {**self.block, field: "C:\\x\\y"}
            with self.subTest(field=field):
                load(overrides={"blender_mcp": block})  # must not raise

    def test_lifecycle_identity_paths_accept_unc_form(self):
        for field in ("blender_executable", "probe_python"):
            block = {**self.block, field: "\\\\srv\\share\\x"}
            with self.subTest(field=field):
                load(overrides={"blender_mcp": block})  # must not raise

    def test_server_command_must_be_absolute(self):
        block = {
            **self.block,
            "server": {**self.block["server"], "command": "relative/blender-mcp.exe"},
        }
        with self.assertRaisesRegex(StudioError, "blender_mcp.server.command must be absolute"):
            load(overrides={"blender_mcp": block})

    def test_server_command_rejects_drive_relative_windows_form(self):
        block = {**self.block, "server": {**self.block["server"], "command": "C:foo"}}
        with self.assertRaisesRegex(StudioError, "blender_mcp.server.command must be absolute"):
            load(overrides={"blender_mcp": block})

    def test_server_command_rejects_drive_less_posix_style_root(self):
        block = {**self.block, "server": {**self.block["server"], "command": "/x/y"}}
        with self.assertRaisesRegex(StudioError, "blender_mcp.server.command must be absolute"):
            load(overrides={"blender_mcp": block})

    def test_server_command_accepts_windows_absolute_form_on_linux(self):
        block = {
            **self.block,
            "server": {**self.block["server"], "command": "C:\\x\\y\\blender-mcp.exe"},
        }
        load(overrides={"blender_mcp": block})  # must not raise

    def test_server_command_accepts_unc_form(self):
        block = {**self.block, "server": {**self.block["server"], "command": "\\\\srv\\share\\x"}}
        load(overrides={"blender_mcp": block})  # must not raise

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


class BlenderMcpLifecycleCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.game = root / "game"
        (self.game / "source").mkdir(parents=True)
        (self.game / "source" / "asset.blend").write_bytes(b"blend")
        self.host = root / "host.json"
        # blender_mcp identity paths are Windows-only and are never resolved
        # against the real filesystem by config.py or blender_mcp_lifecycle.py
        # (they are forwarded to the PowerShell scripts verbatim), so plain
        # Windows-style strings exercise these tests on any host.
        self.block = {
            "working_root": "C:\\StudioHost\\blender-mcp-runs",
            "blender_executable": "C:\\StudioHost\\blender.exe",
            "probe_python": "C:\\StudioHost\\blender-mcp-1.9.1\\Scripts\\python.exe",
            "owner": "studio-blender-test",
            "server": {
                "command": "C:\\StudioHost\\blender-mcp-1.9.1\\Scripts\\blender-mcp.exe",
                "args": [],
                "env": {
                    "BLENDER_HOST": "127.0.0.1",
                    "BLENDER_PORT": "9876",
                    "DISABLE_TELEMETRY": "true",
                    "BLENDER_MCP_DISABLE_TELEMETRY": "true",
                },
            },
        }
        self.host.write_text(json.dumps({"blender_mcp": self.block}))

    def test_entrypoint_routes_ensure_through_packaged_lifecycle_script(self):
        from studio_tools.blender_mcp_lifecycle import execute

        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"status":"PLAN_VALID"}', stderr=""
        )
        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell",
            return_value="C:\\Program Files\\PowerShell\\7\\pwsh.exe",
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.run", return_value=completed
        ) as runner:
            result = execute(
                load(path=self.host),
                self.host,
                self.game,
                "ensure",
                source="source/asset.blend",
                session="review-fix",
                plan_only=True,
            )

        self.assertEqual(result["status"], "PLAN_VALID")
        command = runner.call_args.args[0]
        self.assertEqual(command[0], "C:\\Program Files\\PowerShell\\7\\pwsh.exe")
        self.assertIn(str(ROOT / "skills/studio-blender/scripts/lifecycle/Ensure-SupervisedBlenderMCP.ps1"), command)
        self.assertIn(str((self.game / "source" / "asset.blend").resolve()), command)
        self.assertIn(str(self.host.resolve()), command)
        # working_root is a Windows-only value forwarded verbatim to the
        # PowerShell script; it is never resolved against this host's
        # filesystem, unlike the source/host paths asserted above.
        self.assertIn(self.block["working_root"], command)

    def test_entrypoint_routes_stop_through_packaged_lifecycle_script(self):
        from studio_tools.blender_mcp_lifecycle import execute

        receipt = Path(self.temp.name) / "ownership.json"
        receipt.write_text("{}")
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"status":"CLOSED"}', stderr=""
        )
        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell",
            return_value="C:\\Program Files\\PowerShell\\7\\pwsh.exe",
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.run", return_value=completed
        ) as runner:
            result = execute(
                load(path=self.host),
                self.host,
                self.game,
                "stop",
                receipt=receipt,
            )

        self.assertEqual(result["status"], "CLOSED")
        command = runner.call_args.args[0]
        self.assertIn(
            str(
                ROOT
                / "skills/studio-blender/scripts/lifecycle/Stop-SupervisedBlenderMCP.ps1"
            ),
            command,
        )
        self.assertIn(str(receipt.resolve()), command)

    def test_contract_check_wraps_plain_powershell_success_as_json(self):
        from studio_tools.blender_mcp_lifecycle import execute

        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="PASS: 5 components and 35 lifecycle contracts\n",
            stderr="",
        )
        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell", return_value="pwsh.exe"
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.run", return_value=completed
        ):
            result = execute(
                load(path=self.host), self.host, self.game, "contracts"
            )

        self.assertEqual(
            result,
            {
                "ok": True,
                "summary": "PASS: 5 components and 35 lifecycle contracts",
            },
        )

    def test_cli_requires_explicit_config_and_ensure_inputs(self):
        from studio_tools.cli import dispatch, parser

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser().parse_args(["blender-mcp", "ensure", "--project", str(self.game)])

        without_inputs = parser().parse_args(
            [
                "blender-mcp",
                "ensure",
                "--project",
                str(self.game),
                "--config",
                str(self.host),
            ]
        )
        with self.assertRaisesRegex(StudioError, "requires --source and --session"):
            dispatch(without_inputs)

        args = parser().parse_args(
            [
                "blender-mcp",
                "ensure",
                "--project",
                str(self.game),
                "--config",
                str(self.host),
                "--source",
                "source/asset.blend",
                "--session",
                "review-fix",
                "--plan-only",
            ]
        )
        self.assertEqual(args.command, "blender-mcp")
        self.assertEqual(args.operation, "ensure")


class BlenderMcpPowerShellRegressionTests(unittest.TestCase):
    @staticmethod
    def _source(name):
        return (
            ROOT / "skills/studio-blender/scripts/lifecycle" / name
        ).read_text(encoding="utf-8")

    def test_stop_serializes_before_receipt_validation(self):
        source = self._source("Stop-SupervisedBlenderMCP.ps1")
        self.assertIn("GameStudioKit-BlenderMCP-127_0_0_1-9876", source)
        self.assertLess(source.index("WaitOne"), source.index("$receiptPath"))
        self.assertIn("ReleaseMutex", source)

    def test_ensure_and_stop_recover_an_abandoned_lifecycle_mutex(self):
        for name in ("Ensure-SupervisedBlenderMCP.ps1", "Stop-SupervisedBlenderMCP.ps1"):
            source = self._source(name)
            with self.subTest(script=name):
                wait_block = source[source.index("WaitOne") : source.index("WaitOne") + 400]
                self.assertIn("AbandonedMutexException", wait_block)
                self.assertIn("$mutexAcquired = $true", wait_block)

    def test_ensure_and_stop_write_receipts_atomically(self):
        for name in ("Ensure-SupervisedBlenderMCP.ps1", "Stop-SupervisedBlenderMCP.ps1"):
            source = self._source(name)
            with self.subTest(script=name):
                self.assertIn("function Set-ReceiptContentAtomic", source)
                self.assertIn("Move-Item -LiteralPath $tempPath -Destination $Path -Force", source)
                self.assertNotIn(
                    "ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ownershipReceipt"
                    if name.startswith("Ensure")
                    else "ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath",
                    source,
                )

    def test_malformed_active_pointer_is_inside_recovery_guard(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        active_block = source[source.index("if (Test-Path -LiteralPath $activePath)") :]
        self.assertLess(active_block.index("try {"), active_block.index("ConvertFrom-Json"))

    def test_reuse_requires_canonical_source_path_and_hash(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        reuse_block = source[source.index("if (Test-Path -LiteralPath $activePath)") : source.index("$unownedBlender")]
        self.assertIn("existing.source_scene", reuse_block)
        self.assertIn("existing.source_sha256", reuse_block)
        self.assertIn("OrdinalIgnoreCase", reuse_block)

    def test_reuse_requires_matching_executable_identity(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        reuse_block = source[source.index("if (Test-Path -LiteralPath $activePath)") : source.index("$unownedBlender")]
        self.assertIn("existing.executable", reuse_block)
        self.assertIn("NEEDS_STOP", reuse_block)

    def test_reuse_never_opens_a_second_protocol_bridge_unless_forced(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        reuse_block = source[source.index("if (Test-Path -LiteralPath $activePath)") : source.index("$unownedBlender")]
        # Reuse must default to the lightweight (-SkipProtocolProbe) health
        # check and only run the full round-trip probe when -Probe is passed.
        self.assertIn("[switch]$Probe", source)
        self.assertIn("if (!$Probe) { $reuseHealthArgs['SkipProtocolProbe'] = $true }", reuse_block)
        self.assertEqual(reuse_block.count("& $testScript"), 1)

    def test_startup_failure_closes_in_memory_owned_process_without_stop_preconditions(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        startup_catch = source[source.index("} catch {", source.index("$process = $null")) :]
        self.assertNotIn("& $stopScript", startup_catch)
        self.assertIn("CloseMainWindow", startup_catch)
        self.assertIn("WaitForExit", startup_catch)
        self.assertIn("NEEDS_USER_CLOSE", startup_catch)

    def test_documented_addon_filename_matches_bootstrap_module(self):
        recipe = (ROOT / "skills/studio-blender/references/mcp.md").read_text(encoding="utf-8")
        bootstrap = self._source("supervised_bootstrap.py")
        self.assertIn("`blender_mcp.py`", recipe)
        self.assertIn('module id `addon`', recipe)
        self.assertIn('DOCUMENTED_ADDON_MODULES = ("blender_mcp", "addon")', bootstrap)
        self.assertIn('DOCUMENTED_ADDON_NAME = "MCP for Blender"', bootstrap)
        self.assertIn("DOCUMENTED_ADDON_VERSION = (1, 6)", bootstrap)

    def test_bootstrap_validates_addon_metadata_before_enabling_either_module(self):
        bootstrap = self._source("supervised_bootstrap.py")
        discovery = bootstrap[bootstrap.index("def _enable_documented_addon") :]
        self.assertLess(discovery.index("bl_info"), discovery.index("addon_utils.enable"))
        self.assertIn("DOCUMENTED_ADDON_NAME", discovery)
        self.assertIn("DOCUMENTED_ADDON_VERSION", discovery)


if __name__ == "__main__":
    unittest.main()

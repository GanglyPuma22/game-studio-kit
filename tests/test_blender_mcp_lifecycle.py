"""Behavioral policy tests for the optional supervised Blender MCP route."""

import asyncio
import contextlib
import io
import json
import os
import re
import subprocess
import signal
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

from studio_tools.blender_mcp import (
    RECONNECT_INSTRUCTION,
    app_client_state,
    call_current_addon_status,
    connection_report,
    current_connection,
    load_explicit_server_config,
    require_current_native_status,
)
from studio_tools.common import StudioError
from studio_tools.config import blender_mcp_port, load
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
            {"BLENDER_HOST": "localhost"},
            {"DISABLE_TELEMETRY": "false"},
            {"BLENDER_MCP_DISABLE_TELEMETRY": "false"},
        ):
            block = {**self.block, "server": {**self.block["server"]}}
            block["server"]["env"] = {**self.block["server"]["env"], **env_update}
            with self.subTest(env_update=env_update):
                with self.assertRaises(StudioError):
                    load(overrides={"blender_mcp": block})

    def test_config_accepts_any_ordinary_loopback_port_and_defaults_to_9876(self):
        # A Windows host that reserved 9806-9905 for Hyper-V cannot bind the
        # historical default at all, which blocked every live session while
        # the number was a requirement rather than a host fact.
        for port, expected in (("19876", 19876), ("1024", 1024), ("65535", 65535)):
            block = {**self.block, "server": {**self.block["server"]}}
            block["server"]["env"] = {**self.block["server"]["env"], "BLENDER_PORT": port}
            with self.subTest(port=port):
                config = load(overrides={"blender_mcp": block})
                self.assertEqual(blender_mcp_port(config["blender_mcp"]), expected)
        without = {**self.block, "server": {**self.block["server"]}}
        without["server"]["env"] = {
            key: value
            for key, value in self.block["server"]["env"].items()
            if key != "BLENDER_PORT"
        }
        config = load(overrides={"blender_mcp": without})
        self.assertEqual(blender_mcp_port(config["blender_mcp"]), 9876)

    def test_config_refuses_a_port_that_is_privileged_out_of_range_or_not_a_number(self):
        for port in ("80", "1023", "65536", "abc", "9876.0", " ", "-1", "0x2694"):
            block = {**self.block, "server": {**self.block["server"]}}
            block["server"]["env"] = {**self.block["server"]["env"], "BLENDER_PORT": port}
            with self.subTest(port=port):
                with self.assertRaisesRegex(StudioError, "BLENDER_PORT"):
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

    def test_working_root_symlink_into_kit_is_rejected(self):
        # The lexical PureWindowsPath comparison cannot see through a
        # symlink/junction; an existing working_root must be resolved
        # against its real target before comparing it to the kit root.
        from studio_tools.config import _working_root_is_outside_kit

        root = Path(self.temp.name)
        kit_root = root / "kit"
        kit_root.mkdir()
        elsewhere = root / "elsewhere"
        elsewhere.mkdir()
        linked_working_root = elsewhere / "runs"
        try:
            linked_working_root.symlink_to(kit_root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Host cannot create directory symlinks: {exc}")
        self.assertFalse(_working_root_is_outside_kit(str(linked_working_root), kit_root))

    def test_working_root_symlink_outside_kit_is_accepted(self):
        from studio_tools.config import _working_root_is_outside_kit

        root = Path(self.temp.name)
        kit_root = root / "kit"
        kit_root.mkdir()
        elsewhere = root / "elsewhere"
        elsewhere.mkdir()
        linked_working_root = root / "runs-link"
        try:
            linked_working_root.symlink_to(elsewhere, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Host cannot create directory symlinks: {exc}")
        self.assertTrue(_working_root_is_outside_kit(str(linked_working_root), kit_root))

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
        # The lifecycle now redirects PowerShell's own streams to files under
        # the configured working root, so that value has to be a directory
        # this host can actually create. The host JSON still declares the
        # Windows-only form the validator requires; `loaded()` swaps in the
        # temporary directory afterwards, exactly as a Windows host's own
        # external run root would behave.
        self.runs = root / "runs"
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

    def loaded(self, **overrides):
        config = load(path=self.host)
        config["blender_mcp"]["working_root"] = str(self.runs)
        config["blender_mcp"].update(overrides)
        return config

    @staticmethod
    def fake_powershell(stdout_text="{}", returncode=0):
        """Stand in for the PowerShell parent, writing to the redirected file."""

        def start(command, stdout=None, stderr=None, stdin=None):
            stdout.write(stdout_text.encode("utf-8"))
            stdout.flush()
            return SimpleNamespace(wait=lambda timeout=None: returncode, kill=lambda: None)

        return start

    def test_entrypoint_routes_ensure_through_packaged_lifecycle_script(self):
        from studio_tools.blender_mcp_lifecycle import execute

        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell",
            return_value="C:\\Program Files\\PowerShell\\7\\pwsh.exe",
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.Popen",
            side_effect=self.fake_powershell('{"status":"PLAN_VALID"}'),
        ) as runner:
            result = execute(
                self.loaded(),
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
        self.assertIn(str(self.runs), command)
        # The port the host config declares reaches the script as an explicit
        # argument; no packaged script picks one for itself.
        self.assertEqual(command[command.index("-Port") + 1], "9876")

    def test_entrypoint_routes_stop_through_packaged_lifecycle_script(self):
        from studio_tools.blender_mcp_lifecycle import execute

        receipt = Path(self.temp.name) / "ownership.json"
        receipt.write_text("{}")
        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell",
            return_value="C:\\Program Files\\PowerShell\\7\\pwsh.exe",
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.Popen",
            side_effect=self.fake_powershell('{"status":"CLOSED"}'),
        ) as runner:
            result = execute(
                self.loaded(),
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

        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell", return_value="pwsh.exe"
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.Popen",
            side_effect=self.fake_powershell(
                "PASS: 5 components and 35 lifecycle contracts\n"
            ),
        ):
            result = execute(
                self.loaded(), self.host, self.game, "contracts"
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

    def test_cli_rejects_plan_only_for_non_ensure_operations(self):
        from studio_tools import cli

        stderr = io.StringIO()
        with patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.Popen"
        ) as runner, contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(
            io.StringIO()
        ):
            exit_code = cli.main(
                [
                    "blender-mcp",
                    "stop",
                    "--project",
                    str(self.game),
                    "--config",
                    str(self.host),
                    "--plan-only",
                ]
            )
        self.assertEqual(exit_code, 1)
        runner.assert_not_called()
        self.assertEqual(
            json.loads(stderr.getvalue())["error"],
            "--plan-only is supported by blender-mcp ensure only",
        )

    def test_cli_rejects_probe_for_stop_and_contracts(self):
        from studio_tools import cli

        for operation in ("stop", "contracts"):
            stderr = io.StringIO()
            with self.subTest(operation=operation), patch(
                "studio_tools.blender_mcp_lifecycle.subprocess.Popen"
            ) as runner, contextlib.redirect_stderr(
                stderr
            ), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main(
                    [
                        "blender-mcp",
                        operation,
                        "--project",
                        str(self.game),
                        "--config",
                        str(self.host),
                        "--probe",
                    ]
                )
                self.assertEqual(exit_code, 1)
                runner.assert_not_called()
                self.assertEqual(
                    json.loads(stderr.getvalue())["error"],
                    "--probe is supported by blender-mcp ensure and status only",
                )

    def test_status_defaults_to_skip_protocol_probe_but_probe_flag_forces_it(self):
        from studio_tools.blender_mcp_lifecycle import execute

        for probe, expected in ((False, self.assertIn), (True, self.assertNotIn)):
            with patch(
                "studio_tools.blender_mcp_lifecycle._powershell", return_value="pwsh.exe"
            ), patch(
                "studio_tools.blender_mcp_lifecycle.subprocess.Popen",
                side_effect=self.fake_powershell('{"status":"PASS"}'),
            ) as runner:
                execute(self.loaded(), self.host, self.game, "status", probe=probe)
            expected("-SkipProtocolProbe", runner.call_args.args[0])

    def test_ensure_probe_flag_forwards_probe_switch(self):
        from studio_tools.blender_mcp_lifecycle import execute

        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell", return_value="pwsh.exe"
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.Popen",
            side_effect=self.fake_powershell('{"status":"PLAN_VALID"}'),
        ) as runner:
            execute(
                self.loaded(),
                self.host,
                self.game,
                "ensure",
                source="source/asset.blend",
                session="review-fix",
                probe=True,
            )
        self.assertIn("-Probe", runner.call_args.args[0])

    def test_status_and_stop_reject_a_receipt_path_inside_the_kit(self):
        from studio_tools.blender_mcp_lifecycle import execute

        receipt_inside_kit = ROOT / "runs" / "ownership.json"
        for operation in ("status", "stop"):
            with self.subTest(operation=operation), patch(
                "studio_tools.blender_mcp_lifecycle.subprocess.Popen"
            ) as runner:
                with self.assertRaisesRegex(
                    StudioError, "must be outside the installed kit"
                ):
                    execute(
                        self.loaded(),
                        self.host,
                        self.game,
                        operation,
                        receipt=receipt_inside_kit,
                    )
                runner.assert_not_called()


class BlenderMcpPowerShellRegressionTests(unittest.TestCase):
    @staticmethod
    def _source(name):
        return (
            ROOT / "skills/studio-blender/scripts/lifecycle" / name
        ).read_text(encoding="utf-8")

    def test_stop_serializes_before_receipt_validation(self):
        source = self._source("Stop-SupervisedBlenderMCP.ps1")
        self.assertIn("'Global\\GameStudioKit-BlenderMCP'", source)
        self.assertLess(source.index("WaitOne"), source.index("$receiptPath"))
        self.assertIn("ReleaseMutex", source)

    def test_stop_allows_cleanup_with_an_absent_listener_but_not_a_conflicting_one(self):
        source = self._source("Stop-SupervisedBlenderMCP.ps1")
        # A verified owned process (PID, executable and start time already
        # matched) must still be stoppable if its add-on listener died; a
        # listener owned by someone else must still block cleanup.
        process_block = source[
            source.index("$process = Get-Process") : source.index("$remainingListener")
        ]
        self.assertIn("if ($listeners.Count) {", process_block)
        self.assertIn("Refusing cleanup: loopback listener ownership is ambiguous", process_block)
        self.assertIn('$receipt.listener = "127.0.0.1:$Port"', process_block)
        self.assertIn("$receipt.listener = 'absent'", process_block)

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
        self.assertEqual(reuse_block.count("Invoke-LifecycleHealthCheck"), 1)

    def test_health_check_never_bare_compares_lastexitcode(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        # `& $testScript ...` runs another PowerShell script, not a native
        # program: $LASTEXITCODE is only set here when Test-SupervisedBlenderMCP.ps1
        # internally runs the native protocol probe. A -SkipProtocolProbe
        # reuse check runs no native program at all, so $LASTEXITCODE stays
        # $null (or a stale value); `$null -ne 0` is true, so a bare
        # comparison would treat every such reuse as a failed health check.
        self.assertNotIn("if ($LASTEXITCODE -ne 0)", source)

    def test_outside_kit_check_resolves_reparse_points(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        # [IO.Path]::GetFullPath only normalizes lexically; it never follows
        # a symlink/junction, so comparing its raw output for the kit and
        # working roots would miss a reparse point pointing into the kit.
        self.assertIn("function Resolve-ReparseTarget", source)
        self.assertIn("$kitRoot = Resolve-ReparseTarget", source)
        self.assertIn("$workingRootFull = Resolve-ReparseTarget", source)
        self.assertNotIn("$kitRoot = [IO.Path]::GetFullPath", source)
        self.assertNotIn("$workingRootFull = [IO.Path]::GetFullPath", source)

    def test_active_pointer_is_published_only_after_the_initial_probe(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        cold_start = source[source.index("$freshHealthArgs = @{") : source.index("\n} catch {")]
        probe_index = cold_start.index(
            "Invoke-LifecycleHealthCheck -Script $testScript -Arguments $freshHealthArgs"
        )
        pointer_index = cold_start.index("Set-ReceiptContentAtomic -Path $activePath")
        # A concurrent Ensure's reuse path must never be able to adopt a
        # fresh session before its own protocol probe has actually passed.
        self.assertLess(probe_index, pointer_index)

    def test_health_check_helper_judges_outcome_not_a_bare_exit_code(self):
        source = self._source("Ensure-SupervisedBlenderMCP.ps1")
        helper = source[
            source.index("function Invoke-LifecycleHealthCheck") : source.index(
                "if ($SessionId -notmatch"
            )
        ]
        self.assertIn("$global:LASTEXITCODE = $null", helper)
        self.assertIn(
            "if (!$? -or ($global:LASTEXITCODE -is [int] -and $global:LASTEXITCODE -ne 0)) {",
            helper,
        )
        self.assertIn("throw $FailureMessage", helper)
        # Both the reuse and fresh-start health checks route through the
        # shared helper instead of duplicating a bare $LASTEXITCODE check.
        self.assertEqual(source.count("Invoke-LifecycleHealthCheck -Script $testScript"), 2)

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

    def test_bootstrap_routes_every_receipt_write_through_the_atomic_helper(self):
        bootstrap = self._source("supervised_bootstrap.py")
        self.assertIn("def _write_receipt_atomic", bootstrap)
        self.assertIn("os.replace(tmp_path, path)", bootstrap)
        # One definition plus two call sites (the PASS and BLOCKED writes).
        self.assertEqual(bootstrap.count("_write_receipt_atomic"), 3)
        self.assertNotIn("receipt_path.write_text(", bootstrap)

    def test_bootstrap_write_receipt_atomic_leaves_no_partial_file(self):
        # supervised_bootstrap.py imports bpy/addon_utils, which only exist
        # inside Blender; stub them so the module can be loaded here and
        # _write_receipt_atomic exercised for real, without needing Blender.
        import importlib.util
        import types

        bootstrap_path = (
            ROOT / "skills/studio-blender/scripts/lifecycle/supervised_bootstrap.py"
        )
        fake_modules = {"bpy": types.ModuleType("bpy"), "addon_utils": types.ModuleType("addon_utils")}
        with patch.dict(sys.modules, fake_modules):
            spec = importlib.util.spec_from_file_location(
                "supervised_bootstrap_under_test", bootstrap_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "bootstrap.json"
            real_replace = os.replace
            calls = []

            def spying_replace(src, dst):
                # The source must be a distinct, already-fully-written
                # sibling file at the moment of replace, never the final
                # path itself, so a reader polling the final path never
                # observes a partially written file.
                calls.append((Path(src), Path(dst)))
                self.assertNotEqual(Path(src), Path(dst))
                self.assertEqual(Path(src).parent, Path(dst).parent)
                self.assertTrue(Path(src).is_file())
                return real_replace(src, dst)

            with patch("os.replace", side_effect=spying_replace):
                module._write_receipt_atomic(receipt_path, {"status": "PASS"})

            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(receipt_path.read_text()), {"status": "PASS"})
            leftovers = [p for p in Path(tmp).iterdir() if p != receipt_path]
            self.assertEqual(leftovers, [])


class ConfigurablePortTests(unittest.TestCase):
    """The listener port is a host fact, declared once and forwarded explicitly."""

    LIFECYCLE = ROOT / "skills/studio-blender/scripts/lifecycle"
    SCRIPTS = (
        "Ensure-SupervisedBlenderMCP.ps1",
        "Test-SupervisedBlenderMCP.ps1",
        "Stop-SupervisedBlenderMCP.ps1",
    )

    def test_no_lifecycle_script_still_hard_codes_the_historical_default_port(self):
        # Every remaining `9876` must be the parameter (or the one named
        # fallback the parameter mirrors); anything else is a listener check,
        # a mutex name or a receipt field that a host with the range reserved
        # could not use.
        default_assignment = re.compile(r"^\s*(?:\[int\])?\$[A-Za-z]*[Pp]ort\s*=\s*9876,?\s*$")
        for name in self.SCRIPTS:
            text = (self.LIFECYCLE / name).read_text(encoding="utf-8")
            offending = [
                line for line in text.splitlines()
                if "9876" in line and not default_assignment.match(line)
            ]
            with self.subTest(script=name):
                self.assertEqual(offending, [])
                self.assertRegex(text, r"\[int\]\$Port = 9876")
                self.assertIn("-LocalPort $Port", text)

    def test_the_lifecycle_lock_stays_host_wide_while_the_port_varies(self):
        # One supervised session per host, whatever port it binds. A per-port
        # lock name would let two Ensure runs start at once and only discover
        # each other halfway, after one had already copied a working scene.
        for name in ("Ensure-SupervisedBlenderMCP.ps1", "Stop-SupervisedBlenderMCP.ps1"):
            text = (self.LIFECYCLE / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertIn(
                    "[System.Threading.Mutex]::new($false, 'Global\\GameStudioKit-BlenderMCP')",
                    text,
                )
                self.assertNotIn("GameStudioKit-BlenderMCP-127_0_0_1-$Port", text)

    def test_the_receipt_and_bootstrap_both_name_the_configured_port(self):
        ensure = (self.LIFECYCLE / "Ensure-SupervisedBlenderMCP.ps1").read_text(encoding="utf-8")
        self.assertIn("port = $Port", ensure)
        self.assertIn("port_excluded", ensure)
        self.assertIn("port_occupied", ensure)
        # The refusals happen before the working copy is even made, so an
        # excluded or occupied port leaves no owned process behind.
        self.assertLess(ensure.index("port_excluded"), ensure.index("Copy-Item"))
        self.assertLess(ensure.index("port_occupied"), ensure.index("Copy-Item"))
        bootstrap = (self.LIFECYCLE / "supervised_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("port=port", bootstrap)
        self.assertNotIn("9876", bootstrap)

    def test_stop_and_health_refuse_a_receipt_that_names_another_port(self):
        for name in ("Stop-SupervisedBlenderMCP.ps1", "Test-SupervisedBlenderMCP.ps1"):
            text = (self.LIFECYCLE / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertIn("[int]$receipt.port -ne $Port", text)


class LifecyclePortForwardingTests(BlenderMcpLifecycleCliTests):
    """The configured port reaches every packaged script as an argument."""

    def port_argument(self, operation, port, **kwargs):
        from studio_tools.blender_mcp_lifecycle import execute

        config = self.loaded()
        config["blender_mcp"]["server"]["env"]["BLENDER_PORT"] = port
        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell", return_value="pwsh.exe"
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.Popen",
            side_effect=self.fake_powershell('{"status":"PASS"}'),
        ) as runner:
            execute(config, self.host, self.game, operation, **kwargs)
        command = runner.call_args.args[0]
        return command[command.index("-Port") + 1]

    def test_every_operation_forwards_the_configured_port(self):
        receipt = Path(self.temp.name) / "ownership.json"
        receipt.write_text("{}")
        for operation, kwargs in (
            ("ensure", {"source": "source/asset.blend", "session": "review-fix"}),
            ("status", {}),
            ("stop", {"receipt": receipt}),
        ):
            with self.subTest(operation=operation):
                self.assertEqual(self.port_argument(operation, "19876", **kwargs), "19876")

    def test_an_unconfigured_port_forwards_the_documented_default(self):
        self.assertEqual(self.port_argument("status", "9876"), "9876")


class EnsureReturnsTests(unittest.TestCase):
    """`ensure` returns while the Blender it started is still open."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio lifecycle space ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "runs"

    def test_run_returns_within_its_bound_while_a_grandchild_is_still_alive(self):
        from studio_tools import blender_mcp_lifecycle as lifecycle

        marker = Path(self.temp.name) / "grandchild.pid"
        # The parent writes its JSON to the stream the lifecycle redirected to
        # a file, spawns a long-lived grandchild that inherits that same
        # stream, and exits. Under the old pipe-backed capture the read would
        # have waited for the grandchild; against a file it cannot.
        child = (
            "import os,pathlib,subprocess,sys;"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],"
            "stdout=sys.stdout,stderr=sys.stderr);"
            f"pathlib.Path({str(marker)!r}).write_text(str(p.pid));"
            "sys.stdout.write('{\"status\":\"PASS\"}');sys.stdout.flush()"
        )
        started = time.monotonic()
        with patch.object(lifecycle, "_command", return_value=[sys.executable, "-c", child]):
            result = lifecycle._run(
                "Ensure-SupervisedBlenderMCP.ps1", [],
                working_root=self.root, operation="ensure",
            )
        elapsed = time.monotonic() - started
        grandchild = int(marker.read_text())
        try:
            self.assertEqual(result, {"status": "PASS"})
            self.assertLess(elapsed, lifecycle.RUN_TIMEOUT_SECONDS)
            # Still running: the return did not depend on it, and nothing
            # here stopped a process the lifecycle does not own.
            os.kill(grandchild, 0)
        finally:
            with contextlib.suppress(OSError):
                os.kill(grandchild, signal.SIGKILL)

    def test_streams_land_in_a_run_directory_named_by_operation_and_stamp(self):
        from studio_tools import blender_mcp_lifecycle as lifecycle

        child = "import sys;sys.stdout.write('{\"status\":\"CLOSED\"}');sys.stderr.write('noise')"
        with patch.object(lifecycle, "_command", return_value=[sys.executable, "-c", child]):
            lifecycle._run(
                "Stop-SupervisedBlenderMCP.ps1", [],
                working_root=self.root, operation="stop",
            )
        directories = sorted((self.root / "lifecycle").iterdir())
        self.assertEqual(len(directories), 1)
        self.assertTrue(directories[0].name.startswith("stop-"))
        self.assertEqual(
            (directories[0] / "powershell.stdout.json").read_text(), '{"status":"CLOSED"}'
        )
        self.assertEqual((directories[0] / "powershell.stderr.log").read_text(), "noise")

    def test_a_parent_that_never_returns_becomes_a_terminal_receipt(self):
        from studio_tools import blender_mcp_lifecycle as lifecycle

        child = "import time;time.sleep(120)"
        with patch.object(lifecycle, "_command", return_value=[sys.executable, "-c", child]), \
                patch.object(lifecycle, "RUN_TIMEOUT_SECONDS", 1):
            result = lifecycle._run(
                "Ensure-SupervisedBlenderMCP.ps1", [],
                working_root=self.root, operation="ensure",
            )
        self.assertEqual(result["status"], "ensure_did_not_return")
        self.assertFalse(result["ok"])
        # Nothing an ownership receipt already names was touched.
        self.assertEqual(result["owned_process_action"], "none")
        self.assertIn("blender-mcp stop", result["failure"])
        directory = sorted((self.root / "lifecycle").iterdir())[0]
        self.assertEqual(
            json.loads((directory / "lifecycle-timeout.json").read_text())["status"],
            "ensure_did_not_return",
        )
        # A receipt this kit writes names no host path: the run's own
        # directory name is the handle.
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(result["run"], directory.name)

    def test_the_bound_covers_both_bounded_phases_of_a_successful_ensure(self):
        from studio_tools import blender_mcp_lifecycle as lifecycle

        # A successful ensure waits for the bootstrap receipt and *then* runs
        # the initial protocol probe; the bound has to cover both, or a
        # healthy cold start would be reported as a parent that never returned.
        self.assertEqual(lifecycle.STARTUP_TIMEOUT_SECONDS, 60)
        self.assertEqual(lifecycle.PROBE_READ_TIMEOUT_SECONDS, 75)
        self.assertGreaterEqual(
            lifecycle.RUN_TIMEOUT_SECONDS,
            lifecycle.STARTUP_TIMEOUT_SECONDS + lifecycle.PROBE_READ_TIMEOUT_SECONDS,
        )
        self.assertEqual(lifecycle.RUN_TIMEOUT_SECONDS, 180)
        lifecycle_root = ROOT / "skills/studio-blender/scripts/lifecycle"
        ensure = (lifecycle_root / "Ensure-SupervisedBlenderMCP.ps1").read_text(encoding="utf-8")
        self.assertIn("[int]$StartupTimeoutSeconds = 60", ensure)
        # The probe's own read timeout is the second number the bound covers.
        probe = (lifecycle_root / "probe_mcp.py").read_text(encoding="utf-8")
        self.assertIn("read_timeout_seconds=timedelta(seconds=75)", probe)

    def test_ensure_refuses_to_launch_only_when_its_own_stdio_is_a_pipe(self):
        ensure = (
            ROOT / "skills/studio-blender/scripts/lifecycle/Ensure-SupervisedBlenderMCP.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("function Assert-ParentStdioIsNotAPipe", ensure)
        self.assertIn("ensure_stdio_is_pipe", ensure)
        # The handle type comes from Win32, not from a .NET stream property:
        # Windows PowerShell 5.1 reports CanSeek false even for a stdout
        # redirected to a file, so a CanSeek guard would refuse the packaged
        # entrypoint this check exists to permit.
        self.assertIn("GetStdHandle", ensure)
        self.assertIn("GetFileType", ensure)
        self.assertNotIn("OpenStandardOutput", ensure)
        self.assertNotIn("CanSeek", ensure)
        # Both standard handles are read, only FILE_TYPE_PIPE is refused, and
        # a null or invalid handle -- no stdio at all -- is skipped.
        self.assertIn("Id=-11", ensure)
        self.assertIn("Id=-12", ensure)
        self.assertIn("GetFileType($handle) -eq 3", ensure)
        self.assertIn("$handle.ToInt64() -eq -1", ensure)
        self.assertIn("[IntPtr]::Zero", ensure)
        # The guard runs before the working copy and the launch, not after.
        self.assertLess(
            ensure.index("Assert-ParentStdioIsNotAPipe\n"), ensure.index("Copy-Item")
        )


class ConnectionStateTests(unittest.TestCase):
    """Helper health and app-client connection are two answers, never one."""

    def test_overall_is_connected_only_when_both_layers_are(self):
        self.assertEqual(
            connection_report("PASS", "CONNECTED"),
            {"helper": "PASS", "app_client": "CONNECTED", "overall": "CONNECTED"},
        )
        for helper, app_client, overall in (
            ("FAIL", "CONNECTED", "FAIL"),
            ("PASS", "UNKNOWN", "UNKNOWN"),
            ("FAIL", "UNKNOWN", "FAIL"),
            ("PASS", "RECONNECT_REQUIRED", "RECONNECT_REQUIRED"),
            ("FAIL", "RECONNECT_REQUIRED", "RECONNECT_REQUIRED"),
        ):
            with self.subTest(helper=helper, app_client=app_client):
                report = connection_report(helper, app_client)
                self.assertEqual(report["overall"], overall)
                self.assertNotEqual(report["overall"], "CONNECTED")

    def test_reconnect_required_carries_the_exact_two_layer_instruction(self):
        report = connection_report("PASS", "RECONNECT_REQUIRED")
        self.assertEqual(report["instruction"], RECONNECT_INSTRUCTION)
        self.assertIn("Blender add-on listener is one layer", report["instruction"])
        self.assertIn("Codex connector is the other", report["instruction"])
        self.assertIn("Reconnect the Blender MCP connector from the Codex side",
                      report["instruction"])
        # Nothing else carries an instruction: there is nothing to do.
        for app_client in ("CONNECTED", "UNKNOWN"):
            self.assertNotIn("instruction", connection_report("PASS", app_client))

    def test_unknown_states_are_refused_rather_than_invented(self):
        for helper, app_client in (("pass", "CONNECTED"), ("PASS", "connected"),
                                   ("PASS", "DISCONNECTED"), (None, "UNKNOWN")):
            with self.subTest(helper=helper, app_client=app_client):
                with self.assertRaises(StudioError):
                    connection_report(helper, app_client)

    def test_each_app_client_status_maps_to_its_own_state(self):
        self.assertEqual(app_client_state(CURRENT), "CONNECTED")
        self.assertEqual(
            app_client_state({"source": "error", "warning": "[WinError 10053] oops"}),
            "RECONNECT_REQUIRED",
        )
        self.assertEqual(
            app_client_state({"source": "error", "warning": "Connection to Blender lost"}),
            "RECONNECT_REQUIRED",
        )
        for unknown in (
            {"source": "error", "warning": "connection timed out"},
            {**CURRENT, "protocol_version": 4},
            {**CURRENT, "telemetry_consent": True},
            {"source": "native", "warning": "Connection to Blender lost"},
            "not json",
            [],
        ):
            with self.subTest(status=unknown):
                self.assertEqual(app_client_state(unknown), "UNKNOWN")

    def test_the_documented_stale_status_is_retried_exactly_once(self):
        responses = [{"source": "error", "warning": "WinError 10053"}, CURRENT]
        calls = []

        async def call(tool, arguments):
            calls.append(tool)
            return responses.pop(0)

        report = asyncio.run(current_connection(call, ensure_passed=True, helper="PASS"))
        self.assertEqual(report["overall"], "CONNECTED")
        self.assertEqual(calls, ["get_addon_status", "get_addon_status"])

    def test_a_second_stale_status_is_reported_rather_than_retried_again(self):
        stale = {"source": "error", "warning": "Connection to Blender lost"}
        responses = [stale, stale]
        calls = []

        async def call(tool, arguments):
            calls.append(tool)
            return responses.pop(0)

        report = asyncio.run(current_connection(call, ensure_passed=True, helper="PASS"))
        self.assertEqual(report["app_client"], "RECONNECT_REQUIRED")
        self.assertEqual(report["overall"], "RECONNECT_REQUIRED")
        self.assertEqual(calls, ["get_addon_status", "get_addon_status"])

    def test_nothing_is_retried_without_a_passed_ensure_or_a_transport_failure(self):
        calls = []

        async def stale(tool, arguments):
            calls.append(tool)
            return {"source": "error", "warning": "WinError 10053"}

        report = asyncio.run(current_connection(stale, ensure_passed=False, helper="FAIL"))
        self.assertEqual(report, {
            "helper": "FAIL", "app_client": "RECONNECT_REQUIRED",
            "overall": "RECONNECT_REQUIRED", "instruction": RECONNECT_INSTRUCTION,
        })
        self.assertEqual(calls, ["get_addon_status"])

        transport = []

        async def broken(tool, arguments):
            transport.append(tool)
            raise ConnectionResetError("transport went away")

        with self.assertRaises(ConnectionResetError):
            asyncio.run(current_connection(broken, ensure_passed=True, helper="PASS"))
        self.assertEqual(transport, ["get_addon_status"])

    def test_a_mutation_is_never_routed_through_the_retrying_reader(self):
        calls = []

        async def call(tool, arguments):
            calls.append(tool)
            return {"source": "error", "warning": "WinError 10053"}

        asyncio.run(current_connection(call, ensure_passed=True, helper="PASS"))
        # Only the read-only status tool is ever called, twice at most; no
        # scene query and no mutation is repeated on a stale connection.
        self.assertEqual(set(calls), {"get_addon_status"})
        self.assertLessEqual(len(calls), 2)


class StatusReportsBothLayersTests(BlenderMcpLifecycleCliTests):
    def status(self, payload):
        from studio_tools.blender_mcp_lifecycle import execute

        with patch(
            "studio_tools.blender_mcp_lifecycle._powershell", return_value="pwsh.exe"
        ), patch(
            "studio_tools.blender_mcp_lifecycle.subprocess.Popen",
            side_effect=self.fake_powershell(json.dumps(payload)),
        ):
            return execute(self.loaded(), self.host, self.game, "status")

    def test_status_reports_the_helper_and_leaves_the_app_client_unknown(self):
        result = self.status({"status": "PASS", "pid": 4242})
        self.assertEqual(result["helper"], "PASS")
        # The kit supervises the listener; it cannot see the app's connector,
        # and a probe of its own would be a third party rather than that one.
        self.assertEqual(result["app_client"], "UNKNOWN")
        self.assertEqual(result["overall"], "UNKNOWN")
        self.assertEqual(result["pid"], 4242)

    def test_a_failing_helper_is_never_dressed_up_as_a_connection(self):
        result = self.status({"status": "BLOCKED"})
        self.assertEqual(result["helper"], "FAIL")
        self.assertEqual(result["overall"], "FAIL")


if __name__ == "__main__":
    unittest.main()

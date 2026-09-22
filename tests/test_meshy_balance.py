"""The read-only `studio meshy balance` command (offline).

Checking what is left before asking a human to approve spend was the missing
primitive that made an agent write its own balance script. The transport the
meshy adapter uses is replaced here; no network call is made.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import cli
from studio_tools.adapters.http import ProviderError
from studio_tools.common import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/studio-meshy/SKILL.md"


class FakeTransport:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class BalanceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio balance space ")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("MESHY_API_KEY", None)

    def keyfile(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def host(self, **extra):
        path = self.dir / "host.json"
        write_json(path, extra)
        return str(path)


class MeshyBalanceTests(BalanceCase):
    def balance(self, transport, *argv, config=None):
        with patch("studio_tools.adapters.meshy.Transport", return_value=transport) as made:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = cli.main(["meshy", "balance", "--config", config or self.host(), *argv])
        self.made = made
        return code, out.getvalue(), err.getvalue()

    def test_cli_balance_prints_the_number_and_nothing_else_about_the_account(self):
        os.environ["MESHY_API_KEY"] = "env-secret"
        transport = FakeTransport({"balance": 1234, "account_email": "someone@example.org"})
        code, out, err = self.balance(transport)
        self.assertEqual(err, "")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"balance": 1234, "read_only": True})
        self.assertNotIn("env-secret", out)
        self.assertNotIn("someone@example.org", out)
        (method, url, headers), _ = transport.calls[0]
        self.assertEqual((method, url), ("GET", "https://api.meshy.ai/openapi/v1/balance"))
        self.assertEqual(headers, {"Authorization": "Bearer env-secret"})

    def test_cli_balance_reads_a_declared_credential_file_and_writes_nothing(self):
        config = self.host(credential_files=[self.keyfile("keys.env", "export MESHY_API_KEY='file-secret'\n")])
        before = sorted(p.name for p in self.dir.iterdir())
        code, out, _ = self.balance(FakeTransport({"balance": 7}), config=config)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["balance"], 7)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)

    def test_provider_and_credential_failures_are_types_not_messages(self):
        os.environ["MESHY_API_KEY"] = "env-secret"
        for response, expected in (
            (ProviderError("Provider HTTP 401; echo env-secret", 401), "provider_http_401"),
            (ProviderError("Provider response unavailable"), "provider_unavailable"),
            (OSError("host is offline"), "provider_unavailable"),
            ({"result": {"units": "credits"}}, "unexpected_response"),
            ({"balance": True}, "unexpected_response"),
            # json.loads turns 1e400 into inf; a receipt or a terminal must not
            # be handed one, and this CLI's own writer refuses to serialize it.
            (json.loads('{"balance": 1e400}'), "unexpected_response"),
            (json.loads('{"balance": -1e400}'), "unexpected_response"),
            (json.loads('{"result": {"balance": 1e400}}'), "unexpected_response"),
            ("not an object", "unexpected_response"),
        ):
            with self.subTest(expected=expected):
                code, out, err = self.balance(FakeTransport(response))
                self.assertEqual(err, "")
                self.assertEqual(code, 1)
                payload = json.loads(out)
                self.assertEqual(payload["error_type"], expected)
                self.assertTrue(payload["read_only"])
                self.assertNotIn("env-secret", out)

    def test_a_missing_credential_is_refused_before_any_request(self):
        transport = FakeTransport({"balance": 1})
        code, out, _ = self.balance(transport)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {"error_type": "credential_missing", "read_only": True, "ok": False})
        self.assertEqual(transport.calls, [])
        self.made.assert_not_called()

    def test_a_nested_result_balance_is_accepted(self):
        os.environ["MESHY_API_KEY"] = "env-secret"
        code, out, _ = self.balance(FakeTransport({"result": {"balance": 42.5}}))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["balance"], 42.5)

    def test_the_operations_that_write_still_need_a_project_and_a_record(self):
        mistyped = self.dir / "typo game"
        for argv, message in (
            (["meshy", "observe", "--record", "artifacts/task.json"], "needs --project"),
            (["meshy", "archive", "--project", str(self.dir)], "needs --record"),
            (["meshy", "observe", "--project", str(mistyped)], "needs --record"),
        ):
            with self.subTest(argv=argv):
                with contextlib.redirect_stdout(io.StringIO()):
                    with contextlib.redirect_stderr(io.StringIO()) as err:
                        code = cli.main([*argv, "--config", self.host()])
                self.assertEqual(code, 1)
                self.assertIn(message, json.loads(err.getvalue())["error"])
        # The refusal comes before anything creates the project it named.
        self.assertFalse(mistyped.exists())


class BalanceDiscoverabilityTests(unittest.TestCase):
    """A wrapper script gets written whenever the kit leaves a capability unnamed."""

    def test_the_meshy_skill_description_names_the_balance_command(self):
        description = re.search(r"^description: (.+)$", SKILL.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(description)
        self.assertIn("`studio meshy balance`", description.group(1))

    def test_the_skill_puts_the_balance_check_before_the_spend_approval(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Before asking the human to approve spend", text)
        self.assertIn("meshy balance --config <HOST>", text)
        self.assertIn('"read_only": true', text)
        self.assertIn("A balance is not a price list", text)

    def test_balance_is_documented_where_a_host_configures_the_provider(self):
        setup = (ROOT / "docs/provider-setup.md").read_text(encoding="utf-8")
        self.assertIn("`meshy balance` reports the remaining account balance", setup)
        self.assertIn("read-only", setup)
        self.assertIn("meshy", read_json(ROOT / "studio-kit.json")["commands"])


if __name__ == "__main__":
    unittest.main()

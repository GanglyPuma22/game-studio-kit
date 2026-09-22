"""The read-only `studio audio balance` command (offline).

An agent that cannot ask what an ElevenLabs account has left before asking a
human to approve spend writes its own preflight script, loads the credential
file by hand and calls the subscription endpoint itself. That script existed.
The provider transport is replaced here; no network call is made.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import cli
from studio_tools.adapters.http import ProviderError
from studio_tools.common import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]

SUBSCRIPTION = {
    "tier": "creator",
    "status": "active",
    "character_count": 12000,
    "character_limit": 100000,
    # Everything below is account metadata that answers a different question.
    "next_character_count_reset_unix": 1790000000,
    "billing_period": "monthly_period",
    "currency": "usd",
    "voice_slots_used": 3,
}


class FakeTransport:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class AudioBalanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio audio balance space ")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for name in ("ELEVENLABS_API_KEY", "FISH_AUDIO_API_KEY"):
            os.environ.pop(name, None)

    def host(self, **extra):
        path = self.dir / "host.json"
        write_json(path, extra)
        return str(path)

    def balance(self, transport, *argv, config=None):
        with patch("studio_tools.adapters.elevenlabs.Transport", return_value=transport) as made:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = cli.main(["audio", "balance", "--config", config or self.host(), *argv])
        self.made = made
        return code, out.getvalue(), err.getvalue()

    def test_balance_prints_tier_status_and_character_counts_and_nothing_else(self):
        os.environ["ELEVENLABS_API_KEY"] = "env-secret"
        transport = FakeTransport(SUBSCRIPTION)
        code, out, err = self.balance(transport)
        self.assertEqual(err, "")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {
            "provider": "elevenlabs", "tier": "creator", "status": "active",
            "character_count": 12000, "character_limit": 100000,
            "characters_remaining": 88000, "read_only": True, "network_probed": True,
        })
        self.assertNotIn("env-secret", out)
        for leaked in ("billing_period", "currency", "voice_slots_used", "1790000000"):
            self.assertNotIn(leaked, out)
        (method, url, headers), _ = transport.calls[0]
        self.assertEqual((method, url), ("GET", "https://api.elevenlabs.io/v1/user/subscription"))
        self.assertEqual(headers, {"xi-api-key": "env-secret"})

    def test_balance_reads_a_declared_credential_file_and_writes_nothing(self):
        keyfile = self.dir / "keys.env"
        keyfile.write_text("export ELEVENLABS_API_KEY='file-secret'\n", encoding="utf-8")
        config = self.host(credential_files=[str(keyfile)])
        before = sorted(p.name for p in self.dir.iterdir())
        transport = FakeTransport(SUBSCRIPTION)
        code, out, _ = self.balance(transport, config=config)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["tier"], "creator")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)
        (_, _, headers), _ = transport.calls[0]
        self.assertEqual(headers["xi-api-key"], "file-secret")

    def test_every_failure_is_a_type_rather_than_a_provider_message(self):
        os.environ["ELEVENLABS_API_KEY"] = "env-secret"
        for response, expected in (
            (ProviderError("Provider HTTP 401; echo env-secret", 401), "provider_http_401"),
            (ProviderError("Provider HTTP 429", 429), "provider_http_429"),
            (ProviderError("Provider response unavailable"), "provider_unavailable"),
            (OSError("host is offline"), "provider_unavailable"),
            ({"detail": {"message": "no"}}, "unexpected_response"),
            ("not an object", "unexpected_response"),
            ({"character_count": True}, "unexpected_response"),
        ):
            with self.subTest(expected=expected):
                code, out, err = self.balance(FakeTransport(response))
                self.assertEqual(err, "")
                self.assertEqual(code, 1)
                payload = json.loads(out)
                self.assertEqual(payload["error_type"], expected)
                self.assertTrue(payload["read_only"])
                self.assertTrue(payload["network_probed"])
                self.assertNotIn("env-secret", out)

    def test_a_missing_credential_is_refused_before_any_request(self):
        transport = FakeTransport(SUBSCRIPTION)
        code, out, _ = self.balance(transport)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {
            "provider": "elevenlabs", "error_type": "credential_missing",
            "read_only": True, "network_probed": False, "ok": False,
        })
        self.assertEqual(transport.calls, [])
        self.made.assert_not_called()

    def test_fish_has_no_account_endpoint_this_adapter_knows(self):
        os.environ["FISH_AUDIO_API_KEY"] = "fish-secret"
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = cli.main(["audio", "balance", "--provider", "fish",
                                 "--config", self.host()])
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(code, 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["error_type"], "unsupported")
        self.assertFalse(payload["network_probed"])
        self.assertNotIn("fish-secret", out.getvalue())

    def test_a_partial_subscription_shape_reports_only_what_it_carried(self):
        os.environ["ELEVENLABS_API_KEY"] = "env-secret"
        code, out, _ = self.balance(FakeTransport({"tier": "free", "status": "active"}))
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["tier"], "free")
        self.assertNotIn("characters_remaining", payload)

    def test_the_operations_that_write_still_need_a_project(self):
        mistyped = self.dir / "typo game"
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = cli.main(["audio", "local", "--config", self.host()])
        self.assertEqual(code, 1)
        self.assertIn("needs --project", json.loads(err.getvalue())["error"])
        self.assertFalse(mistyped.exists())


class BalanceDiscoverabilityTests(unittest.TestCase):
    """A wrapper script gets written whenever the kit leaves a capability unnamed."""

    def test_balance_is_registered_as_an_audio_command(self):
        self.assertIn("audio", read_json(ROOT / "studio-kit.json")["commands"])

    def test_balance_is_documented_where_a_host_configures_the_provider(self):
        setup = (ROOT / "docs/provider-setup.md").read_text(encoding="utf-8")
        self.assertIn("audio balance", setup)


if __name__ == "__main__":
    unittest.main()

"""Offline package/CLI regressions; optional isolated native QOA checks."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from studio_tools import cli
from studio_tools.common import read_json, sha256, write_json
from studio_tools.package import check

KIT = Path(__file__).resolve().parents[1]


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='studio correction ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_resource_manifest_covers_required_runtime_and_templates(self):
        required = {p.relative_to(KIT).as_posix()
                    for folder in ('scripts', 'studio_tools', 'templates', 'references')
                    for p in (KIT / folder).rglob('*')
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
        self.assertFalse(required - set(read_json(KIT / 'studio-kit.json')['resources']))

    def test_each_declared_resource_omission_fails(self):
        staged = self.root / 'kit'
        shutil.copytree(KIT, staged, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        for name in read_json(KIT / 'studio-kit.json')['resources']:
            target = staged / name
            original = target.read_bytes()
            target.unlink()
            try:
                with self.subTest(resource=name):
                    result = check(staged)
                    self.assertFalse(result['ok'])
                    self.assertIn('missing resource: ' + name, result['errors'])
            finally:
                target.write_bytes(original)

    def test_export_requires_explicit_glb_destination_before_launch(self):
        args = ['blender', 'export', '--project', str(self.root), '--source', 'edited.blend', '--collection', 'RuntimeAsset']
        with patch('studio_tools.adapters.blender.export') as export, contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(cli.main(args), 1)
            export.assert_not_called()
        self.assertIn('--output', stderr.getvalue())
        self.assertIn('.glb', stderr.getvalue())
        with patch('studio_tools.adapters.blender.export', return_value={}) as export, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(args + ['--output', 'assets/edited.glb']), 0)
            self.assertEqual(export.call_args.args[-1], (self.root / 'assets/edited.glb').resolve())
        for operation in ('fixture', 'inspect', 'render'):
            with patch('studio_tools.adapters.blender.' + operation, return_value={}) as run, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['blender', operation, '--project', str(self.root), '--source', 'edited.blend']), 0)
                self.assertIn((self.root / 'artifacts/blender').resolve(), run.call_args.args)

    def test_new_candidate_template_declares_inventory_v2(self):
        self.assertEqual(read_json(KIT / 'templates/candidate.json').get('inventory_version'), 2)

    def test_documented_staging_keeps_versions_equal_and_actual_workflow_bytes(self):
        document = KIT / 'docs/plugin-staging.md'
        self.assertTrue(document.is_file(), 'Missing supported staging procedure')
        code = re.search(r'```python\n(.*?)\n```', document.read_text(), re.S).group(1)
        staged = self.root / 'staged kit'
        shutil.copytree(KIT, staged, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        game = self.root / 'unrelated game'
        game.mkdir()
        (game / 'scene.gd').write_text('original test content')
        receipt = self.root / 'packaging-receipt.json'
        original = {name: sha256(staged / name) for name in ('.codex-plugin/plugin.json', 'studio-kit.json')}
        env = {**os.environ, 'PYTHONPATH': '', 'STUDIO_CONFIG': ''}
        candidate_cmd = [sys.executable, str(staged / 'scripts/studio.py'), 'candidate', '--project', str(game), '--id', 'staging-test']
        before = subprocess.run(candidate_cmd, cwd=game, env=env, capture_output=True, text=True, check=True)
        subprocess.run([sys.executable, '-c', code, str(staged), '0.1.1+staging.test', str(receipt), 'a'*40], cwd=game, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(read_json(staged / 'studio-kit.json')['version'], '0.1.1+staging.test')
        self.assertEqual(read_json(staged / '.codex-plugin/plugin.json')['version'], '0.1.1+staging.test')
        self.assertTrue(check(staged)['ok'])
        delta = read_json(receipt)
        self.assertEqual(delta['source_revision'], 'a'*40)
        for name in original:
            self.assertEqual(delta['files'][name]['before_sha256'], original[name])
            self.assertEqual(delta['files'][name]['after_sha256'], sha256(staged / name))
        after = subprocess.run(candidate_cmd, cwd=game, env=env, capture_output=True, text=True, check=True)
        self.assertNotEqual(json.loads(before.stdout)['workflow_digest'], json.loads(after.stdout)['workflow_digest'])
        identities = 'import sys, json; sys.path.insert(0, sys.argv[1]); from studio_tools.adapters import fish, requests, elevenlabs, meshy; print(json.dumps([m.__file__ for m in (fish, requests, elevenlabs, meshy)]))'
        modules = subprocess.run([sys.executable, '-c', identities, str(staged)], cwd=game, env=env, capture_output=True, text=True, check=True)
        self.assertTrue(all(Path(path).resolve().is_relative_to(staged.resolve()) for path in json.loads(modules.stdout)))
        plugin = read_json(staged / '.codex-plugin/plugin.json')
        plugin['version'] = 'mismatched'
        write_json(staged / '.codex-plugin/plugin.json', plugin)
        self.assertIn('plugin version disagrees with package', check(staged)['errors'])

    def test_qoa_timeout_preserves_diagnostics(self):
        spec = importlib.util.spec_from_file_location('qoa_check', KIT / 'scripts/check_audio_import.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        timeout = subprocess.TimeoutExpired(['owned-godot'], 90, output=b'engine output\n', stderr=b'SCRIPT ERROR: offline forced stall\n')
        with patch.object(module.subprocess, 'run', side_effect=timeout):
            with self.assertRaisesRegex(RuntimeError, r'timed out.*90') as error:
                module.check(sys.executable)
        self.assertIn('engine output', str(error.exception))
        self.assertIn('SCRIPT ERROR: offline forced stall', str(error.exception))

    @unittest.skipUnless(os.environ.get('STUDIO_TEST_GODOT'), 'Set STUDIO_TEST_GODOT for isolated native headless QOA checks')
    def test_native_qoa_success_and_regression_exit_promptly(self):
        # Copy only the checker and the assignment it reads; preserve source kit.
        for name in ('scripts/check_audio_import.py', 'studio_tools/godot_template/main.gd'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(KIT / name, target)
        script = self.root / 'scripts/check_audio_import.py'
        spec = importlib.util.spec_from_file_location('native_qoa_check', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        good = module.check(os.environ['STUDIO_TEST_GODOT'], timeout=45)
        self.assertEqual(good['loop_end_frame'], 576000)
        template = self.root / 'studio_tools/godot_template/main.gd'
        original = template.read_text()
        assignment = next(line for line in original.splitlines() if 'stream.loop_end =' in line)
        template.write_text(original.replace(assignment, '    stream.loop_end = stream.data.size() / 4'))
        started = time.monotonic()
        # Bound the actual owned Godot child, so a regression cannot orphan it
        # by killing an outer Python process before the helper's timeout.
        with self.assertRaisesRegex(RuntimeError, 'STUDIO_QOA_FAILURE') as error:
            module.check(os.environ['STUDIO_TEST_GODOT'], timeout=10)
        self.assertLess(time.monotonic() - started, 15)
        self.assertIn('576000', str(error.exception))

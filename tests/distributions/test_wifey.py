"""Offline Wifey packaging checks; no live profiles, credentials, or model calls.

The fork can predate profile distributions. Set HERMES_DISTRIBUTION_RUNTIME to a
modern runtime source root to test its real parser/installer in a fresh process.
No parser is copied or mocked. Only version discovery is replaced to avoid git
probes of the installed checkout. Runtime integration skips explicitly when the
modern module is unavailable; source/privacy checks always run.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "distributions" / "wifey"
SKILL = Path("skills/wifey-conversation/SKILL.md")
PUBLIC_FILES = {
    ".gitignore", "distribution.yaml", "SOUL.md", "README.md", "TEST_PROMPTS.md",
    SKILL.as_posix(),
}
MODES = ("Cozy", "Playful", "Focus", "Life Admin", "Deep Talk")


class WifeyPackageTests(unittest.TestCase):
    def test_manifest_is_minimal_and_owns_only_persona_assets(self):
        manifest = yaml.safe_load((DIST / "distribution.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "wifey")
        self.assertEqual(manifest["author"], "groxaxo")
        self.assertEqual(manifest["license"], "MIT")
        self.assertIsInstance(manifest["version"], str)
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(set(manifest), {
            "name", "version", "description", "author", "license", "distribution_owned",
        })
        self.assertEqual(manifest["distribution_owned"], ["SOUL.md", "skills/wifey-conversation"])
        for owned in manifest["distribution_owned"]:
            self.assertTrue((DIST / owned).exists(), owned)
            self.assertTrue((DIST / owned).resolve().is_relative_to(DIST.resolve()))

    def test_public_tree_contains_only_reviewed_text_assets(self):
        files = set()
        for path in DIST.rglob("*"):
            self.assertFalse(path.is_symlink(), f"Symlinks must not ship: {path}")
            if path.is_file():
                files.add(path.relative_to(DIST).as_posix())
                content = path.read_text(encoding="utf-8")
                self.assertTrue(content.strip(), path)
                self.assertNotIn("\x00", content, path)
        self.assertEqual(files, PUBLIC_FILES)

    def test_public_content_has_no_credential_signatures(self):
        # Defense against common accidental pastes, not a complete secret/PII scanner.
        signatures = re.compile(
            r"(?:gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}"
            r"|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|xox[baprs]-[A-Za-z0-9-]{20,}"
            r"|\b\d{6,12}:[A-Za-z0-9_-]{30,}"
            r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
        )
        for relative in PUBLIC_FILES:
            with self.subTest(file=relative):
                content = (DIST / relative).read_text(encoding="utf-8")
                self.assertIsNone(signatures.search(content), f"Credential signature in {relative}")

    def test_modes_are_available_in_identity_skill_and_evaluation(self):
        # Structural coverage only. Conversational behavior needs the manual rubric.
        for relative in ("SOUL.md", SKILL.as_posix(), "TEST_PROMPTS.md"):
            content = (DIST / relative).read_text(encoding="utf-8")
            for mode in MODES:
                with self.subTest(file=relative, mode=mode):
                    self.assertIn(mode, content)

    @unittest.skipUnless(shutil.which("git"), "Git is needed to evaluate actual ignore rules")
    def test_gitignore_blocks_private_files_and_allows_public_assets(self):
        private = {
            ".env", ".env.local", ".env.template", "credentials.json", "auth.json",
            "oauth-tokens.json", "config.yaml", "mcp.json", "MEMORY.md", "USER.md",
            "memories/MEMORY.md", "memories/USER.md", "sessions/conversation.jsonl",
            "logs/agent.log", "state.db", "state.db-wal", "state.db-shm", "state.json",
            "gateway.pid", "gateway_state.json", "cron/jobs.json", "cache/audio.wav",
            "home/.ssh/id_ed25519", "backups/profile.tar.gz", "workspace/notes.md",
            "skills/.usage.json", "skills/wifey-conversation/.env",
            "skills/wifey-conversation/private-memory.md", "skills/other/SKILL.md",
        }
        candidates = {f"distributions/wifey/{p}" for p in private | PUBLIC_FILES}
        result = subprocess.run(
            ["git", "-c", f"core.excludesFile={os.devnull}", "check-ignore",
             "--no-index", "-z", "--stdin"],
            input="\0".join(sorted(candidates)) + "\0", text=True, capture_output=True,
            cwd=ROOT, timeout=15,
            env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": os.devnull, "GIT_OPTIONAL_LOCKS": "0"},
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        ignored = set(filter(None, result.stdout.split("\0")))
        self.assertEqual(ignored, {f"distributions/wifey/{p}" for p in private})


class WifeyNativeRuntimeTests(unittest.TestCase):
    def probe(self, body):
        runtime = Path(os.environ.get("HERMES_DISTRIBUTION_RUNTIME", str(ROOT))).expanduser().resolve()
        if not (runtime / "hermes_cli/profile_distribution.py").is_file():
            self.skipTest("Set HERMES_DISTRIBUTION_RUNTIME to a modern Hermes source root")
        # Keep all test-created state inside the checkout, even without TMPDIR set.
        scratch_root = ROOT / "tmp" / "wifey-tests"
        scratch_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="probe-", dir=scratch_root) as scratch:
            home = Path(scratch)
            temp = home / "temp"
            temp.mkdir()
            env = {
                "HOME": str(home), "HERMES_HOME": str(home / ".hermes"),
                "TMPDIR": str(temp), "PATH": os.defpath,
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "TZ": "UTC", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            }
            script = textwrap.dedent("""\
                import dataclasses
                import shutil
                import socket
                import sys
                from contextlib import ExitStack
                from pathlib import Path
                from types import SimpleNamespace
                from unittest.mock import patch

                RUNTIME, SOURCE, HOME = map(Path, sys.argv[1:])
                sys.path.insert(0, str(RUNTIME))
                with ExitStack() as guards:
                    guards.enter_context(patch.object(socket.socket, 'connect',
                        side_effect=AssertionError('Network disabled in runtime probe')))
                    guards.enter_context(patch.object(socket.socket, 'connect_ex',
                        side_effect=AssertionError('Network disabled in runtime probe')))
                    guards.enter_context(patch('subprocess.Popen',
                        side_effect=AssertionError('Process launch disabled in runtime probe')))
                    import hermes_yaml as yaml
                    from hermes_cli import profile_distribution as dist
                    guards.enter_context(patch('hermes_cli.version_info.get_version_info',
                        return_value=SimpleNamespace(base_version='0.0.0')))
            """) + textwrap.indent(textwrap.dedent(body), "    ")
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", script, str(runtime), str(DIST), str(home)],
                cwd=home, env=env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_manifest_against_actual_runtime_schema(self):
        self.probe("""
            raw = yaml.safe_load((SOURCE / 'distribution.yaml').read_text(encoding='utf-8'))
            fields = {f.name for f in dataclasses.fields(dist.DistributionManifest)}
            assert set(raw) <= fields, 'Unknown manifest fields'
            manifest = dist.read_manifest(SOURCE)
            assert isinstance(manifest, dist.DistributionManifest)
            assert manifest.to_dict() == raw
            assert not manifest.env_requires
            assert not manifest.source and not manifest.installed_at
            assert manifest.distribution_owned == ['SOUL.md', 'skills/wifey-conversation']
        """)

    def test_native_local_install_and_skill_packaging(self):
        self.probe("""
            from agent.skill_utils import parse_frontmatter
            plan = dist.install_distribution(str(SOURCE), name='wifey-test', create_alias=False)
            target = plan.target_dir
            assert target.resolve().is_relative_to(HOME.resolve())
            assert not plan.existing and not plan.has_cron
            assert plan.manifest.source == str(SOURCE.resolve())
            assert plan.manifest.installed_at
            for relative in ('SOUL.md', 'skills/wifey-conversation/SKILL.md'):
                assert (target / relative).read_bytes() == (SOURCE / relative).read_bytes()
            metadata, body = parse_frontmatter(
                (target / 'skills/wifey-conversation/SKILL.md').read_text(encoding='utf-8'))
            assert metadata['name'] == 'wifey-conversation'
            assert 0 < len(metadata['description']) <= 1024
            assert metadata['author'] == 'groxaxo' and metadata['license'] == 'MIT'
            assert metadata['version'] == plan.manifest.version
            assert metadata['metadata']['hermes']['category'] == 'communication'
            assert body.strip()
            assert not metadata.get('required_environment_variables')
            assert dist.describe_distribution('wifey-test')['name'] == 'wifey-test'
            assert not (target / 'README.md').exists()
            assert not (target / 'config.yaml').exists()
            assert not (target / '.env').exists()
            assert not (target / 'cron/jobs.json').exists()
            try:
                dist.install_distribution(str(SOURCE), name='wifey-test')
            except dist.DistributionError:
                pass
            else:
                raise AssertionError('Existing profiles must not be silently replaced')
        """)

    def test_native_update_and_force_reinstall_preserve_user_data(self):
        self.probe("""
            source = HOME / 'source'
            shutil.copytree(SOURCE, source)
            plan = dist.install_distribution(str(source), name='wifey-test')
            target = plan.target_dir
            user_files = {
                '.env': '# synthetic test placeholder only',
                'config.yaml': 'model: test-only-placeholder\\n',
                'memories/USER.md': 'Synthetic private preference',
                'sessions/test.json': '{}',
                'state.db': 'synthetic state sentinel',
                'skills/.usage.json': '{}',
                'skills/user-skill/SKILL.md': 'User-owned skill sentinel',
            }
            for relative, content in user_files.items():
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            (target / 'SOUL.md').write_text('Old installed persona', encoding='utf-8')
            update = dist.update_distribution('wifey-test')
            assert update.existing and update.preserves_config
            assert (target / 'SOUL.md').read_bytes() == (source / 'SOUL.md').read_bytes()
            # Simulate the rollback command without touching the live profile.
            dist.install_distribution(str(source), name='wifey-test', force=True)
            for relative, content in user_files.items():
                assert (target / relative).read_text(encoding='utf-8') == content, relative
        """)

    def test_source_fork_root_is_not_a_distribution(self):
        self.probe("""
            try:
                dist.plan_install(str(SOURCE.parents[1]), HOME / 'staging')
            except dist.DistributionError as error:
                assert 'distribution.yaml' in str(error)
            else:
                raise AssertionError('Install the subfolder, not the source-fork root')
        """)


if __name__ == "__main__":
    unittest.main()

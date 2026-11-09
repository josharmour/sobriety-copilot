"""No Flutter, signing assets, network, or store access needed."""
import importlib.util
from pathlib import Path
import unittest
import os
import shutil
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location(
    "mobile_release_version", Path(__file__).resolve().parents[1] / "scripts/mobile_release_version.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
plan = module.plan


class MobileReleaseVersionTests(unittest.TestCase):
    def test_new_public_versions(self):
        for kind, expected in (("patch", "1.6.2+45"), ("minor", "1.7.0+45"), ("major", "2.0.0+45")):
            with self.subTest(kind=kind):
                self.assertEqual(plan("1.6.1+44", release=kind), expected)

    def test_explicit_version(self):
        self.assertEqual(plan("1.6.1+44", version="1.8.0"), "1.8.0+45")

    def test_beta_only_increments_build(self):
        self.assertEqual(plan("1.6.1+44", build_only=True), "1.6.1+45")

    def test_candidate_and_exact_rebuild(self):
        self.assertEqual(plan("1.6.1+44", candidate=True), "1.6.1+45")
        self.assertEqual(plan("1.6.1+44", candidate=True, bump_build=False), "1.6.1+44")
        self.assertEqual(plan("1.6.1+44", build_only=True, bump_build=False), "1.6.1+44")

    def test_invalid_or_ambiguous_choices(self):
        for kwargs in ({}, {"version": "1.6.1"}, {"version": "1.5.2"},
                       {"version": "1.7"}, {"version": "1.07.0"}, {"release": "feature"},
                       {"release": "patch", "candidate": True},
                       {"version": "1.7.0", "release": "minor"},
                       {"release": "patch", "bump_build": False},
                       {"version": "1.7.0", "bump_build": False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                plan("1.6.1+44", **kwargs)

    def test_bad_current_version(self):
        for current in ("1.6.1", "1.6.1+0", "1.6.1+x", "1.6+44", "1.6.1+44+45"):
            with self.subTest(current=current), self.assertRaises(ValueError):
                plan(current, build_only=True)


class ReleaseScriptIntegrationTests(unittest.TestCase):
    def test_script_modes_without_store_or_git_actions(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            scripts = fixture / "scripts"
            scripts.mkdir()
            for name in ("release_mobile.sh", "mobile_release_version.py"):
                shutil.copy2(root / "scripts" / name, scripts / name)
            mobile = fixture / "mobile_app"
            (mobile / "ios").mkdir(parents=True)
            (mobile / "android").mkdir()
            (mobile / "android/play-service-account.json").write_text("{}")
            pubspec = mobile / "pubspec.yaml"
            pubspec.write_text("version: 1.6.1+44\n")
            bin_dir = fixture / "bin"
            bin_dir.mkdir()
            calls = fixture / "unexpected-calls"
            mocks = {
                "ruby": "exit 0",
                "flutter": 'mkdir -p build/app/outputs/bundle/release; touch build/app/outputs/bundle/release/app-release.aab',
                "git": f'touch "{calls}"; exit 99',
                "fastlane": f'touch "{calls}"; exit 99',
                "xcodebuild": f'touch "{calls}"; exit 99',
            }
            for name, body in mocks.items():
                file = bin_dir / name
                file.write_text("#!/bin/sh\n" + body + "\n")
                file.chmod(0o755)
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                       FLUTTER_BIN=str(bin_dir / "flutter"), RELEASE_OUT_DIR=str(fixture / "out"))
            def run(*args):
                return subprocess.run(["bash", str(scripts / "release_mobile.sh"), *args],
                                      env=env, capture_output=True, text=True)
            rejected = run()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Choose --release", rejected.stderr)
            self.assertEqual(pubspec.read_text(), "version: 1.6.1+44\n")
            beta = run("--build-only")
            self.assertEqual(beta.returncode, 0, beta.stdout + beta.stderr)
            self.assertEqual(pubspec.read_text(), "version: 1.6.1+45\n")
            public_preparation = run("--release", "minor", "--build-only")
            self.assertEqual(public_preparation.returncode, 0, public_preparation.stdout + public_preparation.stderr)
            self.assertEqual(pubspec.read_text(), "version: 1.7.0+46\n")
            self.assertTrue((fixture / "out/sobriety-copilot-1.7.0+46.aab").exists())
            self.assertFalse(calls.exists(), "Build-only must never call uploaders or Git")


if __name__ == "__main__":
    unittest.main()

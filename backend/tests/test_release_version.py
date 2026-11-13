"""Release identity checks use temporary metadata only, without databases/APIs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = load_module("release_version_check", ROOT / "scripts/check_release_version.py")
release_info = load_module("release_version_info", ROOT / "backend/services/release_info.py")


class ReleaseVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("backend/release.json", {"version": "1.2.7"})
        for directory in ("frontend-billing", "desktop"):
            self.write(f"{directory}/package.json", {"version": "1.2.7"})
            self.write(f"{directory}/package-lock.json", {"version": "1.2.7", "packages": {"": {"version": "1.2.7"}}})

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data), encoding="utf-8")

    def test_matching_versions_and_tag_pass_without_mutating_files(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        self.assertEqual(check.check_versions(self.root, "v1.2.7"), ("1.2.7", []))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_mismatched_tag_fails_before_publication(self):
        _, errors = check.check_versions(self.root, "v1.2.8")
        self.assertEqual(len(errors), 1)
        self.assertIn("Release tag", errors[0])

    def test_each_package_version_is_checked(self):
        for directory in ("frontend-billing", "desktop"):
            with self.subTest(directory=directory):
                self.write(f"{directory}/package.json", {"version": "1.2.6"})
                _, errors = check.check_versions(self.root)
                self.assertIn(f"{directory}/package.json: version must be 1.2.7", errors)
                self.write(f"{directory}/package.json", {"version": "1.2.7"})

    def test_lockfile_top_level_and_root_package_versions_are_checked(self):
        for directory in ("frontend-billing", "desktop"):
            with self.subTest(directory=directory):
                self.write(f"{directory}/package-lock.json", {"version": "1.2.6", "packages": {"": {"version": "1.2.6"}}})
                _, errors = check.check_versions(self.root)
                self.assertIn(f"{directory}/package-lock.json: version must be 1.2.7", errors)
                self.assertIn(f"{directory}/package-lock.json: packages[''].version must be 1.2.7", errors)
                self.write(f"{directory}/package-lock.json", {"version": "1.2.7", "packages": {"": {"version": "1.2.7"}}})

    def test_missing_or_malformed_metadata_fails(self):
        (self.root / "desktop/package-lock.json").write_text("{", encoding="utf-8")
        self.assertTrue(check.check_versions(self.root)[1])
        (self.root / "backend/release.json").unlink()
        self.assertTrue(check.check_versions(self.root)[1])

    def test_invalid_canonical_version_fails(self):
        for value in (None, "latest", "01.2.7", {}, "1.2.7\n"):
            with self.subTest(value=value):
                self.write("backend/release.json", {"version": value})
                self.assertTrue(check.check_versions(self.root)[1])

    def test_runtime_uses_packaged_version_even_with_stale_environment(self):
        with patch.dict("os.environ", {"APP_VERSION": "1.0.0"}):
            with self.assertLogs("bizassist.release", level="WARNING"):
                self.assertEqual(release_info.release_version(self.root / "backend/release.json"), "1.2.7")

    def test_missing_or_invalid_packaged_manifest_is_unknown(self):
        self.assertEqual(release_info.release_version(self.root / "missing.json"), "unknown")
        for data in ({}, {"version": "invalid"}, {"version": 123}, []):
            with self.subTest(data=data):
                self.write("backend/release.json", data)
                self.assertEqual(release_info.release_version(self.root / "backend/release.json"), "unknown")


if __name__ == "__main__":
    unittest.main()

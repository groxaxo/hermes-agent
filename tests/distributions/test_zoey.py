"""Focused offline integrity checks for the tiny Zoey companion."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2] / "distributions" / "zoey"

class ZoeyProfileTests(unittest.TestCase):
    def test_manifest_owns_only_persona(self):
        d = yaml.safe_load((ROOT / "distribution.yaml").read_text())
        self.assertEqual((d["name"], d["version"]), ("zoey", "0.2.0"))
        self.assertEqual(d["distribution_owned"], ["SOUL.md", "config.yaml"])

    def test_four_presets_and_default(self):
        d = yaml.safe_load((ROOT / "config.yaml").read_text())
        self.assertEqual(set(d["agent"]["personalities"]), {"spicy", "sweet", "chaos", "focus"})
        self.assertEqual(d["display"]["personality"], "spicy")
        self.assertEqual(set(d), {"agent", "display"})

    def test_no_extras_or_private_data(self):
        files = {p.name for p in ROOT.iterdir() if p.is_file()}
        self.assertEqual(files, {"SOUL.md", "config.yaml", "distribution.yaml", "README.md", ".gitignore"})
        self.assertFalse((ROOT / "skills").exists())
        self.assertIn("West Auckland", (ROOT / "SOUL.md").read_text())

if __name__ == "__main__":
    unittest.main()

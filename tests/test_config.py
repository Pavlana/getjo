import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import ConfigError, load_config, require_env

TARGETS = '[[company]]\nname = "Example Co"\nsource = "greenhouse"\nboard = "exampleco"\n'
PROFILE = '[filter]\ntitle_include = ["engineer"]\n\n[scoring]\nnotify_threshold = 7\n'


class LoadConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> None:
        (self.dir / name).write_text(text)

    def test_loads_targets_and_profile(self):
        self.write("targets.toml", TARGETS)
        self.write("profile.toml", PROFILE)
        cfg = load_config(self.dir)
        self.assertEqual(cfg["targets"][0]["name"], "Example Co")
        self.assertEqual(cfg["profile"]["scoring"]["notify_threshold"], 7)

    def test_missing_file_points_to_example(self):
        self.write("profile.toml", PROFILE)
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.dir)
        self.assertIn("targets.toml not found", str(ctx.exception))
        self.assertIn("targets.example.toml", str(ctx.exception))

    def test_invalid_toml_names_the_file(self):
        self.write("targets.toml", "[[company]\nname = ")
        self.write("profile.toml", PROFILE)
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.dir)
        self.assertIn("targets.toml is not valid TOML", str(ctx.exception))

    def test_missing_section(self):
        self.write("targets.toml", TARGETS)
        self.write("profile.toml", "[filter]\n")
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.dir)
        self.assertIn("missing: scoring", str(ctx.exception))


class RequireEnvTest(unittest.TestCase):
    def test_returns_values(self):
        with mock.patch.dict(os.environ, {"A": "1", "B": "2"}, clear=True):
            self.assertEqual(require_env(["A", "B"]), {"A": "1", "B": "2"})

    def test_lists_every_missing_name_and_no_values(self):
        env = {"PRESENT": "s3cret-value", "EMPTY": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError) as ctx:
                require_env(["PRESENT", "EMPTY", "ABSENT"])
        msg = str(ctx.exception)
        self.assertIn("EMPTY", msg)
        self.assertIn("ABSENT", msg)
        self.assertNotIn("PRESENT", msg)
        self.assertNotIn("s3cret-value", msg)


if __name__ == "__main__":
    unittest.main()

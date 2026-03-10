import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


APP = Path(__file__).resolve().parents[1] / "main.py"


class HelpOutputTests(unittest.TestCase):
    def test_help_uses_flags_and_features_layout(self):
        result = subprocess.run(
            [sys.executable, str(APP), "-h"],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertIn("flags:\n", result.stdout)
        self.assertIn("features:\n", result.stdout)
        self.assertIn("blog conf", result.stdout)
        self.assertIn("# blog p <text> | blog p -m <path> [<text>] | blog p -e", result.stdout)
        self.assertIn("# blog -rec [-ds] [-o <path>]", result.stdout)
        self.assertIn("# blog -a | blog -pl [-o <path>] | blog -c [-o <path>]", result.stdout)

    def test_conf_opens_real_config_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["XDG_CONFIG_HOME"] = tmp
            env["VISUAL"] = "true"
            result = subprocess.run(
                [sys.executable, str(APP), "conf"],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0)
            self.assertTrue((Path(tmp) / "blog" / "config.json").exists())

    def test_bare_publish_text_is_rejected(self):
        result = subprocess.run(
            [sys.executable, str(APP), "ship the patch"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Use: blog p <text>", result.stdout)


if __name__ == "__main__":
    unittest.main()

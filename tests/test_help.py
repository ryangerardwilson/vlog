import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / "main.py"
APP_DIR = APP.parent
VERSION_PATH = APP_DIR / "_version.py"
sys.path.insert(0, str(APP_DIR))


def load_version():
    namespace = {}
    exec(VERSION_PATH.read_text(encoding="utf-8"), namespace)
    return namespace["__version__"]


class HelpOutputTests(unittest.TestCase):
    def test_no_arg_matches_help(self):
        no_arg = subprocess.run(
            [sys.executable, str(APP)],
            capture_output=True,
            text=True,
            check=True,
        )
        help_arg = subprocess.run(
            [sys.executable, str(APP), "help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(no_arg.stdout, help_arg.stdout)

    def test_help_uses_global_actions_and_features_layout(self):
        result = subprocess.run(
            [sys.executable, str(APP), "help"],
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertIn("global actions:\n", result.stdout)
        self.assertIn("features:\n", result.stdout)
        self.assertIn("blog config", result.stdout)
        self.assertIn("# blog publish <text> | blog publish media <path> body <text> | blog publish in editor", result.stdout)
        self.assertIn("# blog record start | blog record stop and publish | blog record stop and save", result.stdout)
        self.assertIn("# blog camera align", result.stdout)
        self.assertIn("# blog recordings play latest | blog recordings clear", result.stdout)
        self.assertNotIn("blog p ", result.stdout)
        self.assertNotIn("blog -rec", result.stdout)

    def test_config_opens_real_config_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["XDG_CONFIG_HOME"] = tmp
            env["VISUAL"] = "true"
            result = subprocess.run(
                [sys.executable, str(APP), "config"],
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
        self.assertIn("valid commands:", result.stdout)

    def test_version_prints_single_value(self):
        result = subprocess.run(
            [sys.executable, str(APP), "version"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), load_version())

    def test_upgrade_passes_u_to_installer(self):
        from main import INSTALL_SCRIPT, main

        with patch("main.subprocess.run") as subprocess_run:
            subprocess_run.return_value.returncode = 0
            rc = main(["upgrade"])

        self.assertEqual(rc, 0)
        self.assertEqual(
            subprocess_run.call_args.args[0],
            ["/usr/bin/env", "bash", str(INSTALL_SCRIPT), "upgrade"],
        )


if __name__ == "__main__":
    unittest.main()

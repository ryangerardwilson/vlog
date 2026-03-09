import subprocess
import sys
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
        self.assertIn("# blog -rec [-ds] [-o <path>]", result.stdout)
        self.assertIn("# blog -a | blog -pl [-o <path>] | blog -c [-o <path>]", result.stdout)


if __name__ == "__main__":
    unittest.main()

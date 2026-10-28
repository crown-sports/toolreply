import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CLITests(unittest.TestCase):
    def run_cli(self, payload, *extra, format="openai-chat"):
        return subprocess.run(
            [sys.executable, "-m", "toolreply", "check", "-", "--format", format, *extra],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_valid_stdin(self):
        result = self.run_cli("[]")
        self.assertEqual(result.returncode, 0)
        self.assertIn("0 calls", result.stdout)
        self.assertIn("not a full API schema check", result.stdout)

    def test_bad_json_does_not_leak_input(self):
        result = self.run_cli('{"SECRET_API_KEY":"private",}', "--output", "json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("input_error", json.loads(result.stdout))
        self.assertNotIn("SECRET", result.stdout + result.stderr)

    def test_non_finite_json_rejected(self):
        self.assertEqual(self.run_cli('[{"role":"user","content":NaN}]').returncode, 2)

    def test_error_json_exit_one(self):
        result = self.run_cli(
            '[{"role":"tool","tool_call_id":"x","content":"ok"}]', "--output", "json"
        )
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["summary"]["errors"], 1)
        self.assertEqual(data["diagnostics"][0]["code"], "ORPHAN_RESULT")

    def test_warning_exit_policy(self):
        payload = (
            '[{"role":"assistant","content":[{"type":"tool_use","id":"a","name":"x","input":{}}]}]'
        )
        warning = self.run_cli(payload, "--allow-pending-tail", format="anthropic")
        strict = self.run_cli(
            payload, "--allow-pending-tail", "--warnings-as-errors", format="anthropic"
        )
        self.assertEqual(warning.returncode, 0)
        self.assertEqual(strict.returncode, 1)

    def test_explicit_format_required(self):
        result = subprocess.run(
            [sys.executable, "-m", "toolreply", "check", "-"],
            input="[]",
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_utf8_bom_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_bytes(b"\xef\xbb\xbf[]")
            result = subprocess.run(
                [sys.executable, "-m", "toolreply", "check", str(path), "--format", "openai-chat"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)

    def test_missing_file_has_no_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "toolreply",
                    "check",
                    str(Path(directory) / "absent.json"),
                    "--format",
                    "openai-chat",
                ],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_size_limit(self):
        result = self.run_cli(" " * (16 * 1024 * 1024 + 1))
        self.assertEqual(result.returncode, 2)
        self.assertIn("16 MiB", result.stderr)

    def test_network_proxy_not_needed(self):
        env = {
            **os.environ,
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "HTTP_PROXY": "http://127.0.0.1:1",
        }
        result = subprocess.run(
            [sys.executable, "-m", "toolreply", "check", "-", "--format", "anthropic"],
            input="[]",
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

"""Black-box checks for the isolated GitHub Action runner, without GitHub credentials."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_action.py"
GOOD = (ROOT / "examples" / "openai-fixed.json").read_bytes()
BAD = (ROOT / "examples" / "openai-broken.json").read_bytes()
PENDING = (ROOT / "examples" / "anthropic-pending.json").read_bytes()


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "consumer with spaces"
        self.workspace.mkdir()
        self.runner_temp = self.root / "runner temp"
        self.runner_temp.mkdir()
        self.outputs = self.root / "outputs"
        self.summary = self.root / "summary"

    def fixture(self, name, payload=GOOD):
        path = self.workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def run_action(self, files, format="openai-chat", **overrides):
        env = {
            **os.environ,
            "GITHUB_WORKSPACE": str(self.workspace),
            "RUNNER_TEMP": str(self.runner_temp),
            "GITHUB_OUTPUT": str(self.outputs),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "TOOLREPLY_FILES": files,
            "TOOLREPLY_FORMAT": format,
            "TOOLREPLY_ALLOW_PENDING_TAIL": "false",
            "TOOLREPLY_WARNINGS_AS_ERRORS": "false",
            **overrides,
        }
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(RUNNER)],
            cwd=self.workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotIn("Traceback", result.stderr)
        lines = self.outputs.read_text("utf-8").splitlines()
        start = next(i for i in reversed(range(len(lines))) if lines[i].startswith("report-path<<"))
        path = Path(lines[start + 1])
        self.assertEqual(path.parent.parent, self.runner_temp)
        report = json.loads(path.read_text("utf-8"))
        self.assertEqual(report["action_schema_version"], 1)
        for key in ("files", "errors", "warnings", "input_errors"):
            self.assertIn(f"{key.replace('_', '-')}={report['summary'][key]}", lines[start:])
        return result, report, path

    def test_multiple_files_globs_deduplication_and_failure_report(self):
        self.fixture("fixtures/a.json")
        self.fixture("fixtures/nested/b.json")
        self.fixture("fixtures/c.json", BAD)
        result, report, _ = self.run_action(
            "fixtures/**/*.json\nfixtures/a.json\nfixtures/c.json\n"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["summary"]["files"], 3)
        self.assertEqual(report["summary"]["calls"], 6)
        self.assertEqual(report["summary"]["errors"], 2)
        self.assertEqual(
            [item["path"] for item in report["files"]],
            ["fixtures/a.json", "fixtures/c.json", "fixtures/nested/b.json"],
        )

    def test_clean_and_zero_calls_are_explicit(self):
        self.fixture("clean.json")
        self.fixture("empty.json", b"[]")
        result, report, _ = self.run_action("*.json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["summary"]["zero_call_files"], 1)
        self.assertIn("1 files contained no supported tool calls", result.stdout)

    def test_each_pattern_must_match_and_other_files_still_checked(self):
        self.fixture("valid.json")
        result, report, _ = self.run_action("valid.json\nmissing/*.json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["summary"]["files"], 1)
        self.assertEqual(report["configuration_errors"], [{"code": "NO_MATCH", "pattern_index": 2}])

    def test_empty_pattern_list_is_an_input_error(self):
        result, report, _ = self.run_action("\n\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn({"code": "FILES_REQUIRED"}, report["configuration_errors"])

    def test_invalid_format_and_strict_booleans_are_not_silently_accepted(self):
        self.fixture("valid.json")
        for field, value in (
            ("TOOLREPLY_FORMAT", "openai"),
            ("TOOLREPLY_ALLOW_PENDING_TAIL", "yes"),
            ("TOOLREPLY_WARNINGS_AS_ERRORS", "False"),
        ):
            with self.subTest(field=field):
                result, report, _ = self.run_action("valid.json", **{field: value})
                self.assertEqual(result.returncode, 2)
                self.assertEqual(report["summary"]["files"], 0)

    def test_pending_tail_and_warning_policy(self):
        self.fixture("pending.json", PENDING)
        default, _, _ = self.run_action("pending.json", "anthropic")
        allowed, report, _ = self.run_action(
            "pending.json", "anthropic", TOOLREPLY_ALLOW_PENDING_TAIL="true"
        )
        strict, _, _ = self.run_action(
            "pending.json",
            "anthropic",
            TOOLREPLY_ALLOW_PENDING_TAIL="true",
            TOOLREPLY_WARNINGS_AS_ERRORS="true",
        )
        self.assertEqual((default.returncode, allowed.returncode, strict.returncode), (1, 0, 1))
        self.assertGreater(report["summary"]["warnings"], 0)

    def test_malformed_json_report_does_not_leak_payload(self):
        self.fixture("invalid.json", b'{"SECRET_API_KEY":"private",}')
        self.fixture("valid.json")
        result, report, _ = self.run_action("*.json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["summary"]["files"], 2)
        self.assertEqual(report["summary"]["input_errors"], 1)
        self.assertIn("input_error", report["files"][0]["report"])
        self.assertNotIn("SECRET", result.stdout + result.stderr + json.dumps(report))

    def test_cli_size_limit_is_preserved(self):
        self.fixture("large.json", b" " * (16 * 1024 * 1024 + 1))
        result, report, _ = self.run_action("large.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("16 MiB", report["files"][0]["report"]["input_error"])

    def test_absolute_parent_and_windows_paths_rejected(self):
        outside = self.root / "outside.json"
        outside.write_bytes(BAD)
        for pattern in (str(outside), "../outside.json", "C:/outside.json", "C:outside.json"):
            with self.subTest(pattern=pattern):
                result, report, _ = self.run_action(pattern)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(report["summary"]["files"], 0)
                self.assertEqual(report["configuration_errors"][0]["code"], "UNSAFE_PATTERN")
                self.assertNotIn("outside.json", json.dumps(report))

    def test_symlink_escape_rejected_without_reading_target(self):
        outside = self.root / "outside.json"
        outside.write_bytes(BAD)
        link = self.workspace / "escape.json"
        try:
            link.symlink_to(outside)
        except OSError as error:
            self.skipTest(f"Host cannot create symlinks: {type(error).__name__}")
        result, report, _ = self.run_action("*.json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report["summary"]["files"], 0)
        self.assertEqual(report["configuration_errors"][0]["code"], "OUTSIDE_WORKSPACE")

    def test_spaces_unicode_dash_and_shell_metacharacters_are_data(self):
        names = ["-option.json", "你好 space.json", "$(echo unsafe).json", "`echo unsafe`.json"]
        for name in names:
            self.fixture(name)
        result, report, _ = self.run_action("*.json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual({item["path"] for item in report["files"]}, set(names))
        self.assertNotIn("unsafe", result.stdout + result.stderr + self.summary.read_text("utf-8"))

    @unittest.skipIf(os.name == "nt", "Windows filenames cannot contain newlines or colons")
    def test_newline_and_workflow_command_filename_never_reaches_logs(self):
        name = "line\n::error::injected.json"
        self.fixture(name)
        result, report, path = self.run_action("*.json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["files"][0]["path"], name)
        self.assertIn("\\n::error::", path.read_text("utf-8"))
        self.assertNotIn(
            "::error::", result.stdout + result.stderr + self.summary.read_text("utf-8")
        )

    def test_consumer_imports_environment_and_working_directory_cannot_shadow_action(self):
        self.fixture("clean.json")
        poison = b"raise RuntimeError('CONSUMER_IMPORT_EXECUTED')\n"
        for name in ("toolreply.py", "json.py", "sitecustomize.py", "usercustomize.py"):
            self.fixture(name, poison)
        self.fixture("toolreply/__init__.py", poison)
        result, report, _ = self.run_action(
            "clean.json", PYTHONPATH=str(self.workspace), PYTHONHOME=str(self.workspace / "absent")
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report["summary"]["calls"], 2)
        self.assertNotIn("CONSUMER_IMPORT_EXECUTED", result.stdout + result.stderr)

    def test_reports_are_unique_and_do_not_overwrite_inputs(self):
        path = self.fixture("report.json")
        _, _, first = self.run_action("report.json")
        _, _, second = self.run_action("report.json")
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file())
        self.assertEqual(path.read_bytes(), GOOD)


if __name__ == "__main__":
    unittest.main()

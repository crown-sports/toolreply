"""GitHub Action adapter; execute with Python -I -S, never from the consumer's imports."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

# The GitHub Action checkout is the source of truth, even if the caller has another
# toolreply installed or supplies PYTHONPATH/sitecustomize in its own checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toolreply import __version__  # noqa: E402
from toolreply.audit import FORMATS  # noqa: E402
from toolreply.cli import main as check_main  # noqa: E402


def select_files(workspace: Path, patterns: list[str]) -> tuple[list[tuple[str, Path]], list]:
    """Expand only workspace-relative globs and deduplicate their resolved targets."""
    selected: dict[Path, str] = {}
    errors = []
    for index, pattern in enumerate(patterns, 1):
        error = None
        posix = PurePosixPath(pattern)
        windows = PureWindowsPath(pattern)
        if (
            posix.is_absolute()
            or windows.drive
            or windows.root
            or ".." in posix.parts
            or "\\" in pattern
            or "\x00" in pattern
        ):
            error = "UNSAFE_PATTERN"
        else:
            matches = 0
            try:
                for candidate in sorted(workspace.glob(pattern)):
                    resolved = candidate.resolve(strict=True)
                    if not resolved.is_relative_to(workspace):
                        error = "OUTSIDE_WORKSPACE"
                        continue
                    if resolved.is_file():
                        matches += 1
                        selected.setdefault(resolved, candidate.relative_to(workspace).as_posix())
            except (OSError, ValueError, RuntimeError):
                error = "UNREADABLE_PATTERN"
            if not matches and error is None:
                error = "NO_MATCH"
        if error:
            # Patterns may themselves contain private names or absolute paths.
            # Index them without copying them to logs or reports.
            errors.append({"code": error, "pattern_index": index})
    return sorted((relative, path) for path, relative in selected.items()), errors


def check_file(path: Path, format: str, pending: bool, strict: bool) -> tuple[int, dict]:
    """Reuse CLI decoding, input bounds, error messages and exit policy unchanged."""
    args = ["check", str(path), "--format", format, "--output", "json"]
    if pending:
        args.append("--allow-pending-tail")
    if strict:
        args.append("--warnings-as-errors")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = check_main(args)
    return exit_code, json.loads(output.getvalue())


def publish(report: dict, exit_code: int) -> int:
    """Write the report and outputs before returning a failing status."""
    summary = report["summary"]
    try:
        directory = Path(tempfile.mkdtemp(prefix="toolreply-", dir=os.environ["RUNNER_TEMP"]))
        report_path = directory / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", "utf-8")
        if output_path := os.environ.get("GITHUB_OUTPUT"):
            with Path(output_path).open("a", encoding="utf-8") as output:
                # A generated delimiter also handles unusual runner directory names.
                delimiter = "toolreply_" + directory.name.removeprefix("toolreply-")
                output.write(f"report-path<<{delimiter}\n{report_path}\n{delimiter}\n")
                for key in ("files", "errors", "warnings", "input_errors"):
                    output.write(f"{key.replace('_', '-')}={summary[key]}\n")
        text = (
            f"toolreply: {summary['files']} files, {summary['calls']} calls; "
            f"{summary['errors']} errors, {summary['warnings']} warnings, "
            f"{summary['input_errors']} input/configuration errors."
        )
        print(text)
        if summary["zero_call_files"]:
            print(f"{summary['zero_call_files']} files contained no supported tool calls.")
        if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(summary_path).open("a", encoding="utf-8") as output:
                output.write(f"### toolreply\n\n{text}\n\n")
                output.write(
                    f"{summary['zero_call_files']} files contained no supported tool calls. "
                    "This checks lifecycle rules, not full provider schemas or result quality.\n\n"
                )
    except (OSError, KeyError):
        print("toolreply: could not write the report or GitHub output files.", file=sys.stderr)
        return 2
    return exit_code


def main() -> int:
    summary = dict(files=0, calls=0, errors=0, warnings=0, input_errors=0, zero_call_files=0)
    report = {
        "action_schema_version": 1,
        "toolreply_version": __version__,
        "format": None,
        "summary": summary,
        "configuration_errors": [],
        "files": [],
    }
    errors = report["configuration_errors"]
    format = os.environ.get("TOOLREPLY_FORMAT", "")
    if format not in FORMATS:
        errors.append({"code": "INVALID_FORMAT"})
    else:
        report["format"] = format
    flags = []
    for name in ("ALLOW_PENDING_TAIL", "WARNINGS_AS_ERRORS"):
        value = os.environ.get(f"TOOLREPLY_{name}", "false")
        if value not in ("true", "false"):
            errors.append({"code": f"INVALID_{name}"})
        flags.append(value == "true")
    # A line is a whole pattern, not shell syntax. Spaces within filenames are kept.
    patterns = [line for line in os.environ.get("TOOLREPLY_FILES", "").splitlines() if line.strip()]
    if not patterns:
        errors.append({"code": "FILES_REQUIRED"})
    try:
        workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        if not workspace.is_dir():
            raise OSError
    except (OSError, KeyError, RuntimeError):
        errors.append({"code": "INVALID_WORKSPACE"})
    if errors:
        summary["input_errors"] = len(errors)
        return publish(report, 2)

    files, pattern_errors = select_files(workspace, patterns)
    errors.extend(pattern_errors)
    summary["input_errors"] = len(errors)
    exit_code = 2 if errors else 0
    for relative, path in files:
        code, result = check_file(path, format, *flags)
        report["files"].append({"path": relative, "exit_code": code, "report": result})
        summary["files"] += 1
        if code == 2:
            summary["input_errors"] += 1
        else:
            for key in ("calls", "errors", "warnings"):
                summary[key] += result["summary"][key]
            summary["zero_call_files"] += result["summary"]["calls"] == 0
        exit_code = max(exit_code, code)
    return publish(report, exit_code)


if __name__ == "__main__":
    raise SystemExit(main())

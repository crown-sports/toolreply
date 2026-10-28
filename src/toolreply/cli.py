"""Single-document CLI. Diagnostics never interpolate transcript payloads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .audit import FORMATS, InputError, Report, _reject_constant, audit

MAX_INPUT_BYTES = 16 * 1024 * 1024


def render_text(report: Report) -> str:
    summary = (
        f"{report.calls} calls, {report.results} results, {report.paired} paired; "
        f"{report.errors} errors, {report.warnings} warnings"
    )
    lines = [summary]
    for item in report.diagnostics:
        lines.append(f"{item.severity.upper()} {item.code} {item.location}: {item.message}")
        if item.related_locations:
            lines.append("  related: " + ", ".join(item.related_locations))
    if report.calls == 0:
        lines.append("No supported tool calls were found; this is not a full API schema check.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint saved tool-call/result conversations offline."
    )
    parser.add_argument("--version", action="version", version=f"toolreply {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="check one JSON message array or messages envelope")
    check.add_argument("input", help="UTF-8 JSON file, or - for stdin (maximum 16 MiB)")
    check.add_argument("--format", choices=FORMATS, required=True)
    check.add_argument("--output", choices=("text", "json"), default="text")
    check.add_argument(
        "--allow-pending-tail",
        action="store_true",
        help="downgrade missing results in only the final batch to warnings",
    )
    check.add_argument("--warnings-as-errors", action="store_true", help="exit 1 on any warning")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            with Path(args.input).open("rb") as stream:
                data = stream.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise InputError("Input exceeds the 16 MiB limit; split it by complete conversation.")
        document = json.loads(data.decode("utf-8-sig"), parse_constant=_reject_constant)
        report = audit(document, format=args.format, allow_pending_tail=args.allow_pending_tail)
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        # JSON error details can contain source fragments; keep console/CI logs payload-free.
        if isinstance(error, InputError):
            message = str(error)
        elif isinstance(error, OSError):
            message = "Could not read input file. Check its path and permissions."
        else:
            message = "Input must be complete UTF-8 JSON without non-finite numbers."
        if args.output == "json":
            print(json.dumps({"schema_version": 1, "input_error": message}))
        else:
            print("Input error: " + message, file=sys.stderr)
        return 2
    if args.output == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=True, indent=2))
    else:
        print(render_text(report))
    return int(report.errors > 0 or (args.warnings_as_errors and report.warnings > 0))

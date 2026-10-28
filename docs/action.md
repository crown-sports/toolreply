# Check saved histories in GitHub Actions

[中文使用说明](action.zh-CN.md)

Use toolreply on synthetic or redacted regression fixtures before replaying a conversation.
One action invocation checks multiple files of one explicitly selected provider format. It fails
on lifecycle errors and still writes a JSON report. It never replays calls or sends histories to an API.

```yaml
name: recorded histories
on: [push, pull_request]
permissions:
  contents: read
jobs:
  toolreply:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
      - uses: crown-sports/toolreply@v0.2.0
        id: histories
        with:
          files: |
            tests/fixtures/openai/**/*.json
            tests/regressions/retry-history.json
          format: openai-chat
          warnings-as-errors: "true"
      # Optional: keep the payload-free report, even if the check failed.
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        if: ${{ always() && steps.histories.outputs.report-path != '' }}
        with:
          name: toolreply-report
          path: ${{ steps.histories.outputs.report-path }}
```

Replace the fixture paths with paths in your checked-out repository. Pin toolreply to the full
commit SHA of the reviewed release when you need an immutable dependency. No Marketplace
listing, API token, package installation, or separate action repository is required.

## Inputs and outputs

| Input | Default | Meaning |
| --- | --- | --- |
| `files` | Required | Newline-separated paths or glob patterns relative to `GITHUB_WORKSPACE`. |
| `format` | Required | Exactly `openai-chat` or `anthropic`; use a second action step for the other format. |
| `allow-pending-tail` | `"false"` | `"true"` changes unresolved calls in the final unfinished batch to warnings. |
| `warnings-as-errors` | `"false"` | `"true"` makes warnings fail the step too. |

Booleans accept only the strings `true` and `false`. Quote them in YAML. Required inputs are
validated by the runner, including empty values. Omitting the format never guesses a provider.

Use `/` separators on every runner. Patterns use Python `pathlib` glob syntax: `*`, `?`, character
classes and recursive `**`; this is not shell expansion, brace expansion or a gitignore file.
Each nonblank line must match at least one file. Do not put quotes around an individual filename
inside the multiline `files` value. Spaces within a line are preserved; blank lines are ignored.
Overlapping patterns check each resolved file once. Absolute paths, parent traversal, backslashes,
and resolved targets outside the workspace are rejected. A symlink inside the workspace can
refer to another file inside it, but cannot escape it. Directories are not histories. A filename
containing a newline can be selected with a glob, not as a literal multiline entry.

| Output | Meaning |
| --- | --- |
| `report-path` | Absolute path to a unique JSON report under `RUNNER_TEMP`. |
| `files` | Number of distinct files checked, including malformed input files. |
| `errors`, `warnings` | Aggregate lifecycle diagnostic counts. |
| `input-errors` | Malformed/unreadable inputs plus invalid or unmatched input patterns/options. |

The runner processes matched files even if another pattern is invalid. It returns `2` for any
input/configuration error, otherwise `1` for lifecycle errors or strict warnings, otherwise `0`.
The report and outputs are written before this status is returned, including failed checks.
Failure to start Python or write to the runner's temporary/output directories can prevent a report.
Use the caller's `continue-on-error` if you deliberately want a non-blocking check.

The report has `action_schema_version: 1`, a `toolreply_version`, aggregate `summary`, indexed
`configuration_errors`, and a `files` list. Each file entry contains its workspace-relative `path`,
`exit_code`, and the existing CLI JSON `report` with `schema_version: 1`. Configuration errors
identify a pattern by its one-based nonblank pattern index without echoing arbitrary input text.

Only relative filenames and the CLI's payload-free diagnostics are retained. Names, IDs,
argument values, message text and result payloads from transcripts are omitted. Filenames
themselves may be sensitive: review artifact retention and visibility before enabling upload.
The action does not upload anything automatically. Console output and the job summary contain
counts only, so a hostile filename cannot become a workflow command or Markdown content.
Files with zero supported calls are reported explicitly; passing is not a full provider-schema
check or a guarantee that recorded operations actually ran.

## Runtime and local reproduction

The composite action uses the official `setup-python` action pinned to v7.1.0's commit, with
Python 3.12. Its returned absolute interpreter path launches the action-owned script with `-I -S`.
The script adds only this action checkout's `src` to the isolated import path and calls the same
`toolreply.cli.main` used by the CLI, retaining its 16 MiB per-file bound and error policy.
It does not install from PyPI, import the consumer's packages, or use the caller's working directory
to locate code. The action does not change the caller's Python selection or install dependencies.
Python setup may download a runtime; the audit itself is offline.

The action smoke workflow runs `uses: ./` on GitHub-hosted Ubuntu, Windows and macOS. It checks
passing/broken fixtures, allowed/strict pending tails, malformed JSON, and reports available from
failed steps. Bash on hosted Windows is provided by Git for Windows. Custom self-hosted runners
need a compatible Actions runner, Bash, and `setup-python` prerequisites.

Reproduce the adapter checks locally from this checkout without installing toolreply:

```sh
python -m unittest discover -s tests -p test_action.py -v
```

To reproduce a single result with the regular installed CLI:

```sh
toolreply check tests/fixtures/conversation.json --format openai-chat --warnings-as-errors --output json
```

Tests use temporary synthetic workspaces, exercise file and symlink boundaries, test shell and
workflow-command characters, preserve JSON reports on failure, and place hostile Python modules
in the consumer checkout to verify import isolation. Windows cannot create newline/colon filenames;
that case runs on Linux/macOS. Symlink tests report a skip if the local OS prohibits creating one.

Implementation references: [composite action metadata](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax),
[GitHub's injection and dependency-pinning guidance](https://docs.github.com/en/actions/reference/security/secure-use),
[Python isolated mode and site disabling](https://docs.python.org/3.12/using/cmdline.html),
[setup-python](https://github.com/actions/setup-python/tree/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0).

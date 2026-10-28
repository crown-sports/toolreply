# Changelog

## 0.2.0 — 2026-10-28

- A same-repository composite GitHub Action checks multiple saved history fixtures without a
  package installation step, using the same CLI and its existing privacy/input-size boundaries.
- Explicit provider format, workspace-contained globs, duplicate suppression, strict option
  validation, and JSON reports/outputs retained on failed checks.
- Isolated action-owned Python imports, payload-free count summaries, bilingual usage docs,
  adversarial filename/path tests, and a three-platform action smoke workflow.

Lifecycle rules and the CLI JSON schema are unchanged. Action aggregation uses a separate
`action_schema_version: 1`; zero supported calls still do not establish lifecycle coverage.

## 0.1.0 — 2026-10-28

First experimental release of offline tool-call/result lifecycle checks.

- OpenAI Chat Completions function calls and Anthropic client tool blocks.
- Batch-scoped correlation, ambiguous/duplicate/orphan/missing/late result diagnostics.
- Valid parallel permutations, multiple rounds, and adjacent Anthropic message normalization.
- Optional pending-tail mode for in-progress histories; intermediate failures remain errors.
- Text and schema-versioned JSON reports without original payload values.
- Standard-library runtime, CLI stdin/file input, documented exit codes, Python API.
- Synthetic broken/fixed examples, English/Chinese onboarding, protocol scope documentation.

This release does not validate complete provider requests, execute tools, or evaluate answer quality.

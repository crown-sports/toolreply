# Changelog

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

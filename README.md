# toolreply

**Find broken tool-call/result pairs before replaying an LLM conversation.**

An agent called two tools. Your executor returned two results. That still breaks if both results
reference the first call. toolreply finds the duplicate reply and the missing reply, with exact
locations in your saved JSON.

It runs offline, needs no API key, has no runtime dependencies, and never executes tools.
Use it in regression tests, when debugging an exporter, or before replaying a recorded conversation.

[Quick start](#try-the-broken-and-fixed-examples) · [中文说明](docs/README.zh-CN.md) ·
[Rules and scope](docs/rules.md) · [LangChain/LangGraph recipe](docs/langchain.md) · [Contributing](CONTRIBUTING.md)

## Try the broken and fixed examples

Python 3.10 or later. Install this checkout in a virtual environment:

```sh
git clone https://github.com/crown-sports/toolreply.git
cd toolreply
python3 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
toolreply check examples/openai-broken.json --format openai-chat
```

```text
2 calls, 2 results, 1 paired; 2 errors, 0 warnings
ERROR DUPLICATE_RESULT /messages/3/tool_call_id: A result already answered this call.
  related: /messages/1/tool_calls/0/id
ERROR MISSING_RESULT /messages/1/tool_calls/1/id: No unambiguous result arrived before the next turn or end of transcript.
```

The executor reused `call_north` for the south warehouse's response.
Changing that response's reference to `call_south` gives:

```sh
toolreply check examples/openai-fixed.json --format openai-chat
```

```text
2 calls, 2 results, 2 paired; 0 errors, 0 warnings
```

The examples are synthetic and do not call an API. The result says the checked lifecycle rules
pass; it does not prove the stock numbers or final answer are correct.

You can also install the wheel from [Releases](https://github.com/crown-sports/toolreply/releases)
with `python -m pip install /path/to/toolreply-0.1.0-py3-none-any.whl`.
The package is not currently published on PyPI.

## Check your own history

Save either a JSON array of messages or an object with a `messages` array.
Choose the format explicitly:

```sh
toolreply check conversation.json --format openai-chat --output json
toolreply check conversation.json --format anthropic
cat conversation.json | toolreply check - --format anthropic
```

| Format | Supported recorded calls and responses |
| --- | --- |
| `openai-chat` | Assistant `tool_calls` with `type: function`; `role: tool` responses |
| `anthropic` | Assistant `tool_use`; user `tool_result` content blocks for client tools |

Checks cover missing or duplicated IDs, ambiguous/missing/orphan/duplicate/late replies,
incomplete argument JSON, non-object inputs, call/result roles, and Anthropic result order.
Parallel results may arrive in any order. Adjacent Anthropic messages with the same role are
combined for checking while diagnostics retain their original JSON Pointer locations.

Repeated IDs in later batches are **warnings**, not automatic failures: the result is paired to
the current batch. Calls with the same name and arguments are not treated as duplicates.

### In-progress captures

```sh
toolreply check examples/anthropic-pending.json --format anthropic --allow-pending-tail
```

This downgrades unresolved calls in only the final unfinished batch to `PENDING_RESULT`
warnings. Missing results before a subsequent turn remain errors. User text that proceeds
without the remaining results also remains an error. This option does not make a partial
transcript suitable to send to a provider.

### Exit codes and CI

| Exit | Meaning |
| --- | --- |
| `0` | No errors; warnings are permitted by default |
| `1` | Errors found, or warnings with `--warnings-as-errors` |
| `2` | Bad command, unreadable input, unsupported envelope, invalid JSON, or input over 16 MiB |

```yaml
# After installing toolreply in your CI environment:
- run: toolreply check tests/fixtures/conversation.json --format openai-chat --warnings-as-errors
```

For an artifact, use `--output json > toolreply-report.json`. Reports include counts, stable
diagnostic codes, severities, and source locations. They omit tool names, IDs, argument values,
message text, and result payloads. No telemetry, remote calls, or input-file modification occurs.
Treat original transcript files as sensitive; they are not sanitized by this tool.

## Python API

```python
import json
from toolreply import audit

with open("conversation.json", encoding="utf-8") as stream:
    document = json.load(stream)
report = audit(document, format="openai-chat")
assert report.errors == 0, report.to_dict()
```

The function does not mutate its input. JSON reports use `schema_version: 1`.
`paired` counts unambiguous ID pairs, even if another diagnostic rejects a pair's role-independent
metadata or arguments; consult `errors` rather than treating the pair count as a verdict.

## Scope and related tools

This is an early release focused on **conversation lifecycle consistency**. It is not a complete
provider schema validator, tool executor, security scanner, or quality evaluator. It does not check
tool declarations/JSON Schemas, semantic argument correctness, result content schemas, model-specific
request restrictions, or whether a recorded operation really ran. Zero calls means nothing was
audited about tool lifecycles.

OpenAI Responses items, streaming deltas, legacy `function_call`, Anthropic server tools and
programmatic tool calling, and framework-specific event logs are outside this release's scope.
Recognized unsupported tool shapes generate errors. Export a complete supported message history;
do not concatenate separate conversations into one file.

[tool-call-audit](https://github.com/thisbejim/tool-call-audit) addresses saved tool calls against
JSON Schema. toolreply focuses on the later history: did each call receive one correctly placed
reply? The tools have different checks and can be used at different stages.

Protocol references and version boundaries are documented in [rules.md](docs/rules.md).

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python -m pip install build ruff
ruff check .
ruff format --check .
python -m build
```

Tests exercise parallel-result permutations, several rounds, duplicate IDs, delayed replies,
pending tails, adjacent Anthropic message normalization, source locations, report privacy,
CLI exit codes, and input limits. No live API tests or provider acceptance claims are made.

MIT licensed. Small, redacted reproductions of incorrect diagnostics are especially useful.

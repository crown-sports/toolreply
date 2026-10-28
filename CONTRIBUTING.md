# Contributing

Please start with a small reproducible transcript and the expected diagnosis. Replace all real
text, arguments, results, identifiers, URLs and personal data with synthetic values before posting.
Keep the original message structure and ordering that demonstrate the problem.

For a change in provider behavior, link the primary provider documentation. Add one failing
example and a nearby valid example to guard against false positives. New formats should have
explicit names and a separate parser; avoid guessing a provider from one field.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . build ruff
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python -m build
```

The runtime must remain offline and must not execute transcript data. Report messages must not
include payload text or interpolate tool names/IDs. Preserve stable diagnostic codes and document
changes to the JSON report shape. Small focused PRs are welcome.

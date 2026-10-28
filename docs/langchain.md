# Check a LangChain or LangGraph message history

Use this when your application already holds a complete list of LangChain message
objects. For a LangGraph application this may be the `messages` field in a selected
state. This recipe does not load checkpoints or connect to a tracing service.

LangChain provides [`convert_to_openai_messages`](https://reference.langchain.com/python/langchain-core/messages/utils/convert_to_openai_messages)
to export message objects into the OpenAI dictionary format supported by toolreply.
This is different from `messages_to_dict`, which produces LangChain's own serialization.

```python
from langchain_core.messages import convert_to_openai_messages
from toolreply import audit

# messages = state["messages"]  # Your application's complete message history.
report = audit(convert_to_openai_messages(messages), format="openai-chat")
if report.errors:
    raise ValueError(report.to_dict())
```

No additional toolreply dependency is needed in an existing LangChain environment.
The example below was tested with `toolreply==0.1.0` and `langchain-core==1.7.0`
on Python 3.12. The optional integration is also exercised in CI.

## A reproducible executor mistake

From a current source checkout, after installing toolreply in a virtual environment:

```sh
python -m pip install "langchain-core==1.7.0"
python examples/langchain_history.py
```

Expected output:

```text
broken: 1/2 paired, 2 errors
  DUPLICATE_RESULT /3/tool_call_id
  MISSING_RESULT /1/tool_calls/1/id
fixed: 2/2 paired, 0 errors
```

The sample constructs two calls, then incorrectly returns both results with
`tool_call_id="call_north"`. The message objects themselves have different `id`
values, but those are message IDs, not the call correlation IDs. Correcting the
second result's `tool_call_id` repairs the pairing. This is a synthetic mistake in
the example executor, not a reported LangChain bug. It makes no API calls and runs
no tools. A separate assertion shows that a delivered tool error is still a reply.

The example script is available on main after the v0.1.0 release; the released
v0.1.0 wheel already provides all the library functions used here.

## Choose the right history

- Audit one conversation branch at a time, not concatenated checkpoint snapshots.
- For a snapshot taken while tools are running, use `allow_pending_tail=True` only
  when the unfinished batch is at the end. Earlier missing replies remain errors.
- This recipe covers ordinary function tool calls. Streaming chunks, custom or
  server tools, `RemoveMessage` operations and provider-specific content may need
  different handling before export. Do not assume conversion proves API validity.
- Conversion preserves message content. Keep the exported history local; only
  toolreply's diagnostic report omits payloads. A clean report does not prove the
  result values or final answer are correct.

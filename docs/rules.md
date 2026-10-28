# Rules, evidence, and compatibility

The initial protocol review was performed on 2026-10-28. These are bounded lint rules,
not a claim of complete API conformance. No provider API is called during validation.

Primary references:

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
  describes complete function calls, JSON-encoded arguments, IDs and their result references.
- [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
  defines assistant function calls and tool-role messages. Responses items are a different format.
- [Anthropic handling tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
  documents client call/result blocks, immediate result turns, result-first content ordering,
  and matching `toolset_name` for toolset members.
- [Anthropic Messages reference](https://platform.claude.com/docs/en/api/typescript/messages/create)
  documents combining adjacent messages of the same role.
- [Anthropic system messages](https://platform.claude.com/docs/en/build-with-claude/working-with-messages#system-role-in-messages)
  documents model-dependent mid-conversation `system` roles. These are recognized as turn
  boundaries; placement and model compatibility are not validated here.

## Lifecycle rules

A batch is one assistant tool-call message in OpenAI Chat Completions, or one combined assistant
turn in Anthropic. OpenAI results occupy successive tool messages. Anthropic results occupy the
next combined user turn and precede other blocks. Result order within a batch does not matter.
Unresolved IDs expire when that result batch ends, so a later result cannot silently repair history.

Duplicate IDs inside a batch create ambiguity. toolreply reports it and does not guess a match.
Reuse in a later batch is a warning: provider/exporter conventions differ, and a resolved earlier
call must not cause a valid current result to be labeled a duplicate.

The default assumes a completed recorded conversation. `--allow-pending-tail` allows an unfinished
final call batch (including a partially returned batch), while preserving all intermediate errors.
In Anthropic a final user turn containing non-result content closes the batch even in pending mode.

## Diagnostic codes

| Code | Meaning / suggested investigation |
| --- | --- |
| `CALL_ID_MISSING` | A call lacks a non-empty string ID; inspect generation/export. |
| `RESULT_ID_MISSING` | A reply lacks its correlation ID; inspect executor serialization. |
| `DUPLICATE_CALL_ID` | Multiple active calls share an ID; do not key a batch by a non-unique value. |
| `REUSED_CALL_ID` | Warning: an ID appeared in a prior batch; inspect normalization. |
| `ORPHAN_RESULT` | No recorded preceding call matches; inspect truncation or wrong conversation. |
| `DUPLICATE_RESULT` | A call already received a result; inspect retries and copied IDs. |
| `LATE_RESULT` | The call's reply batch ended earlier; inspect ordering. |
| `AMBIGUOUS_RESULT` | Duplicate call IDs prevent an unambiguous pairing. |
| `MISSING_RESULT` | No unique reply arrived in the permitted batch. |
| `PENDING_RESULT` | Warning: unfinished final batch explicitly permitted. |
| `ARGUMENTS_NOT_JSON` | Function arguments are not a complete JSON string. |
| `ARGUMENTS_NOT_OBJECT` | Arguments/input must be an object, not an array/scalar/string. |
| `CALL_NAME_MISSING` | A function/client tool call needs a non-empty name. |
| `RESULT_ORDER` | Anthropic result blocks follow other content in a combined user turn. |
| `TOOLSET_MISMATCH` | A client's result has a different/missing toolset name. |
| `CALL_ROLE` / `RESULT_ROLE` | The tool block belongs in a different message role. |
| `RESULT_CONTENT_MISSING` | An OpenAI tool message has no content field. |
| `MESSAGE_SHAPE` / `MESSAGE_ROLE` | A message is not an object or has an unsupported role. |
| `CALLS_SHAPE` / `CALL_SHAPE` | The tool-call container or a call has the wrong structural shape. |
| `CONTENT_SHAPE` / `BLOCK_SHAPE` | An Anthropic content container/block has the wrong shape. |
| `FORMAT_MISMATCH` | Tool fields indicate the other supported provider format. |
| `UNSUPPORTED_TOOL` | Recognized call shape is outside this release's supported scope. |

Locations are RFC 6901 JSON Pointers with zero-based array indices. Related locations point to
the call responsible for the result diagnostic. Messages are deliberately generic: raw payloads,
names and IDs are not printed, even when malformed.
An ambiguous result lists at most eight related calls, avoiding quadratic report growth when a
broken exporter repeats one ID thousands of times; every call still receives its own diagnosis.

## Explicit non-goals

- Tool declaration, JSON Schema, tool-result content schema, or model-specific request validation.
- Checking full message alternation/system placement, token limits, authentication, tool permissions.
- Inferring missing calls from truncated transcripts, or reconstructing streaming chunks.
- Matching calls by tool name or arguments when IDs are missing.
- Inferring that duplicate replies mean a side effect executed twice. This checks records only.
- Checking custom tools, server tool cycles, programmatic/async Responses items or provider extensions.

Non-tool blocks such as text, images and thinking are not recursively interpreted as tool calls.
This is important for tool results containing JSON that happens to look like a call.

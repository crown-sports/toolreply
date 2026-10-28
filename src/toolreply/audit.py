"""Protocol-specific parsing and a batch-scoped call/result state machine."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

FORMATS = ("openai-chat", "anthropic")


class InputError(ValueError):
    """The document is not a supported transcript envelope."""


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    location: str
    message: str
    related_locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    format: str
    messages: int
    calls: int
    results: int
    paired: int
    diagnostics: tuple[Diagnostic, ...]

    @property
    def errors(self) -> int:
        return sum(item.severity == "error" for item in self.diagnostics)

    @property
    def warnings(self) -> int:
        return sum(item.severity == "warning" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        """A payload-free, JSON-serializable report with a versioned shape."""
        return {
            "schema_version": 1,
            "format": self.format,
            "summary": {
                "messages": self.messages,
                "calls": self.calls,
                "results": self.results,
                "paired": self.paired,
                "unpaired_calls": self.calls - self.paired,
                "errors": self.errors,
                "warnings": self.warnings,
            },
            "diagnostics": [asdict(item) for item in self.diagnostics],
        }


@dataclass
class _Call:
    location: str
    toolset: Any = None
    status: str = "pending"


@dataclass
class _State:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    pending: dict[str, list[_Call]] = field(default_factory=dict)
    latest: dict[str, _Call] = field(default_factory=dict)
    calls: int = 0
    results: int = 0
    paired: int = 0

    def emit(self, code, location, message, *, related=(), severity="error"):
        self.diagnostics.append(Diagnostic(code, severity, location, message, tuple(related)))

    def call(self, call_id: Any, location: str, toolset: Any = None):
        self.calls += 1
        if not _nonempty_string(call_id):
            self.emit("CALL_ID_MISSING", location, "Call ID must be a non-empty string.")
            return
        if call_id in self.pending:
            self.emit(
                "DUPLICATE_CALL_ID",
                location,
                "Calls in the same batch share an ID; a result cannot identify one call.",
                related=[self.pending[call_id][0].location],
            )
        elif call_id in self.latest:
            self.emit(
                "REUSED_CALL_ID",
                location,
                "An earlier batch used this ID. Pairing uses the current batch; "
                "check the exporter.",
                related=[self.latest[call_id].location],
                severity="warning",
            )
        call = _Call(location, toolset)
        self.pending.setdefault(call_id, []).append(call)
        self.latest[call_id] = call

    def result(self, call_id: Any, location: str, toolset: Any = None):
        self.results += 1
        if not _nonempty_string(call_id):
            self.emit("RESULT_ID_MISSING", location, "Result reference must be a non-empty string.")
            return
        candidates = self.pending.get(call_id, [])
        if len(candidates) > 1:
            self.emit(
                "AMBIGUOUS_RESULT",
                location,
                "This result refers to multiple calls in the current batch; no match was guessed.",
                related=[call.location for call in candidates[:8]],
            )
        elif candidates:
            call = candidates[0]
            if toolset != call.toolset:
                self.emit(
                    "TOOLSET_MISMATCH",
                    location,
                    "Result toolset_name must match the corresponding call.",
                    related=[call.location],
                )
            call.status = "matched"
            self.paired += 1
            del self.pending[call_id]
        elif call_id in self.latest:
            call = self.latest[call_id]
            code = "DUPLICATE_RESULT" if call.status == "matched" else "LATE_RESULT"
            self.emit(
                code,
                location,
                "A result already answered this call."
                if code == "DUPLICATE_RESULT"
                else "The call's result batch ended before this result arrived.",
                related=[call.location],
            )
        else:
            self.emit("ORPHAN_RESULT", location, "No preceding call has this result reference.")

    def close_batch(self, *, pending_tail=False):
        for calls in self.pending.values():
            for call in calls:
                self.emit(
                    "PENDING_RESULT" if pending_tail else "MISSING_RESULT",
                    call.location,
                    "The final batch is unfinished; a result is still pending."
                    if pending_tail
                    else "No unambiguous result arrived before the next turn or end of transcript.",
                    severity="warning" if pending_tail else "error",
                )
                call.status = "missing"
        self.pending.clear()


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reject_constant(value):
    raise ValueError("Non-finite numbers are not JSON.")


def _arguments(value: Any, location: str, state: _State):
    if not isinstance(value, str):
        state.emit("ARGUMENTS_NOT_JSON", location, "Function arguments must be a JSON string.")
        return
    try:
        parsed = json.loads(value, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        state.emit(
            "ARGUMENTS_NOT_JSON", location, "Function arguments are not complete valid JSON."
        )
        return
    if not isinstance(parsed, dict):
        state.emit("ARGUMENTS_NOT_OBJECT", location, "Function arguments must decode to an object.")


def _openai(messages: list, prefix: str, state: _State, pending_tail: bool):
    for i, message in enumerate(messages):
        path = f"{prefix}/{i}"
        if not isinstance(message, dict):
            state.close_batch()
            state.emit("MESSAGE_SHAPE", path, "Each message must be an object.")
            continue
        role = message.get("role")
        if role != "tool":
            state.close_batch()
        if role not in ("system", "developer", "user", "assistant", "tool"):
            state.emit("MESSAGE_ROLE", path + "/role", "Unsupported or missing message role.")
        if message.get("function_call") is not None or role == "function":
            state.emit("UNSUPPORTED_TOOL", path, "Legacy function-call messages are not supported.")
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result")
            for block in content
        ):
            state.emit(
                "FORMAT_MISMATCH", path + "/content", "Anthropic tool blocks need its format."
            )
        if role == "tool":
            state.result(message.get("tool_call_id"), path + "/tool_call_id")
            if "content" not in message:
                state.emit("RESULT_CONTENT_MISSING", path, "A tool result needs a content field.")
        calls = message.get("tool_calls")
        if calls is None:
            continue
        if role != "assistant":
            state.emit("CALL_ROLE", path + "/tool_calls", "Only assistant messages can call tools.")
            continue
        if not isinstance(calls, list):
            state.emit("CALLS_SHAPE", path + "/tool_calls", "tool_calls must be an array.")
            continue
        for j, call in enumerate(calls):
            call_path = f"{path}/tool_calls/{j}"
            if not isinstance(call, dict):
                state.emit("CALL_SHAPE", call_path, "Each call must be an object.")
                continue
            if call.get("type") != "function":
                state.emit(
                    "UNSUPPORTED_TOOL", call_path, "Only complete function calls are supported."
                )
                continue
            state.call(call.get("id"), call_path + "/id")
            function = call.get("function")
            if not isinstance(function, dict):
                state.emit(
                    "CALL_SHAPE", call_path + "/function", "Call function must be an object."
                )
                continue
            if not _nonempty_string(function.get("name")):
                state.emit(
                    "CALL_NAME_MISSING", call_path + "/function/name", "A call needs a name."
                )
            _arguments(function.get("arguments"), call_path + "/function/arguments", state)
    state.close_batch(pending_tail=pending_tail)


def _anthropic_groups(messages: list, prefix: str, state: _State):
    """Combine adjacent same-role messages, keeping original JSON Pointer locations."""
    groups: list[tuple[Any, list[tuple[Any, str]]]] = []
    for i, message in enumerate(messages):
        path = f"{prefix}/{i}"
        if not isinstance(message, dict):
            state.emit("MESSAGE_SHAPE", path, "Each message must be an object.")
            groups.append((None, []))
            continue
        role = message.get("role")
        if role not in ("user", "assistant", "system"):
            state.emit("MESSAGE_ROLE", path + "/role", "Unsupported or missing message role.")
        if "tool_calls" in message or "tool_call_id" in message:
            state.emit("FORMAT_MISMATCH", path, "OpenAI tool fields need openai-chat format.")
        content = message.get("content")
        if isinstance(content, str):
            blocks = [({"type": "text"}, path + "/content")]
        elif isinstance(content, list):
            blocks = [(block, f"{path}/content/{j}") for j, block in enumerate(content)]
        else:
            state.emit("CONTENT_SHAPE", path + "/content", "Content must be text or a block array.")
            blocks = []
        if groups and role in ("user", "assistant") and groups[-1][0] == role:
            groups[-1][1].extend(blocks)
        else:
            groups.append((role, blocks))
    return groups


def _anthropic(messages: list, prefix: str, state: _State, pending_tail: bool):
    groups = _anthropic_groups(messages, prefix, state)
    for group_index, (role, blocks) in enumerate(groups):
        if role != "user":
            state.close_batch()
        non_result_seen = False
        for block, path in blocks:
            if not isinstance(block, dict):
                state.emit("BLOCK_SHAPE", path, "Each content block must be an object.")
                non_result_seen = True
                continue
            kind = block.get("type")
            if kind == "tool_result":
                if role != "user":
                    state.emit("RESULT_ROLE", path, "Tool results belong in user messages.")
                    continue
                if non_result_seen:
                    state.emit(
                        "RESULT_ORDER",
                        path,
                        "Tool results must precede other content in the combined user turn.",
                    )
                state.result(
                    block.get("tool_use_id"), path + "/tool_use_id", block.get("toolset_name")
                )
            else:
                non_result_seen = True
                if kind == "tool_use":
                    if role != "assistant":
                        state.emit("CALL_ROLE", path, "Tool calls belong in assistant messages.")
                        continue
                    state.call(block.get("id"), path + "/id", block.get("toolset_name"))
                    if not _nonempty_string(block.get("name")):
                        state.emit("CALL_NAME_MISSING", path + "/name", "A call needs a name.")
                    if not isinstance(block.get("input"), dict):
                        state.emit(
                            "ARGUMENTS_NOT_OBJECT", path + "/input", "Tool input must be an object."
                        )
                    caller = block.get("caller")
                    if caller is not None and caller != {"type": "direct"}:
                        state.emit(
                            "UNSUPPORTED_TOOL", path, "Programmatic tool calling is not supported."
                        )
                elif isinstance(kind, str) and (
                    kind.endswith("tool_use") or kind.endswith("tool_result")
                ):
                    state.emit(
                        "UNSUPPORTED_TOOL", path, "Only client tool_use/tool_result is supported."
                    )
                elif not isinstance(kind, str):
                    state.emit("BLOCK_SHAPE", path, "A content block needs a string type.")
        # A user turn is a complete batch. Tail mode only admits its unfinished final batch.
        if role == "user":
            state.close_batch(
                pending_tail=pending_tail and group_index == len(groups) - 1 and not non_result_seen
            )
    state.close_batch(pending_tail=pending_tail)


def audit(document: Any, *, format: str, allow_pending_tail: bool = False) -> Report:
    """Audit a message array or object with a messages array, without mutating it.

    `format` is explicit; no provider detection is performed. Missing results in
    the final batch can be warnings when auditing an in-progress transcript.
    Earlier missing results always remain errors. This is not a full API schema
    validator, and a clean report is not a guarantee an API will accept a request.
    """
    if format not in FORMATS:
        raise InputError("format must be openai-chat or anthropic")
    prefix = ""
    if isinstance(document, dict):
        messages = document.get("messages")
        prefix = "/messages"
    else:
        messages = document
    if not isinstance(messages, list):
        raise InputError("Expected a message array or an object containing a messages array.")
    state = _State()
    parser = _openai if format == "openai-chat" else _anthropic
    parser(messages, prefix, state, allow_pending_tail)
    return Report(
        format, len(messages), state.calls, state.results, state.paired, tuple(state.diagnostics)
    )

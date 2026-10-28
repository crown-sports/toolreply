"""Audit synthetic LangChain histories without calling a model or executing a tool.

Optional example dependency: langchain-core==1.7.0. This is an executor mistake
constructed for demonstration, not a claim of a LangChain defect.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, convert_to_openai_messages

from toolreply import audit


def history(*, fixed: bool):
    return [
        HumanMessage(content="Compare stock in the north and south warehouses."),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call_north", "name": "stock", "args": {"warehouse": "north"}},
                {"id": "call_south", "name": "stock", "args": {"warehouse": "south"}},
            ],
        ),
        ToolMessage(content="12", tool_call_id="call_north", id="message_north"),
        ToolMessage(
            content="7",
            tool_call_id="call_south" if fixed else "call_north",
            id="message_south",
        ),
        AIMessage(content="The north warehouse has more stock."),
    ]


def main():
    for fixed in (False, True):
        messages = history(fixed=fixed)
        exported = convert_to_openai_messages(messages)
        # Message IDs and tool correlation IDs are different identifiers.
        assert exported[2]["tool_call_id"] == "call_north"
        report = audit(exported, format="openai-chat")
        codes = [diagnostic.code for diagnostic in report.diagnostics]
        expected = [] if fixed else ["DUPLICATE_RESULT", "MISSING_RESULT"]
        assert codes == expected, report.to_dict()
        assert report.paired == (2 if fixed else 1)
        assert report.warnings == 0
        print(f"{'fixed' if fixed else 'broken'}: {report.paired}/2 paired, {report.errors} errors")
        for diagnostic in report.diagnostics:
            print(f"  {diagnostic.code} {diagnostic.location}")
    # Tool failures still count as a delivered result; they are not missing replies.
    failed_tool = [
        AIMessage(content="", tool_calls=[{"id": "a", "name": "lookup", "args": {}}]),
        ToolMessage(content="Not found", tool_call_id="a", status="error"),
    ]
    assert audit(convert_to_openai_messages(failed_tool), format="openai-chat").errors == 0


if __name__ == "__main__":
    main()

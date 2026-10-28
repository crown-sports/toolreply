import copy
import itertools
import json
import unittest

from toolreply import InputError, audit


def ocall(id="a", arguments="{}"):
    return {"id": id, "type": "function", "function": {"name": "lookup", "arguments": arguments}}


def assistant(*ids):
    return {"role": "assistant", "tool_calls": [ocall(id) for id in ids]}


def result(id="a"):
    return {"role": "tool", "tool_call_id": id, "content": "ok"}


def acall(id="a", **extra):
    return {"type": "tool_use", "id": id, "name": "lookup", "input": {}, **extra}


def aresult(id="a", **extra):
    return {"type": "tool_result", "tool_use_id": id, **extra}


def message(role, *blocks):
    return {"role": role, "content": list(blocks)}


def codes(report):
    return [item.code for item in report.diagnostics]


class OpenAITests(unittest.TestCase):
    def check(self, messages, **kwargs):
        return audit(messages, format="openai-chat", **kwargs)

    def test_parallel_result_permutations_across_rounds(self):
        for order in itertools.permutations(("a", "b", "c")):
            messages = [{"role": "user", "content": "Compare providers"}, assistant("a", "b", "c")]
            messages += [result(id) for id in order]
            messages += [assistant("d"), result("d"), {"role": "assistant", "content": "Done"}]
            with self.subTest(order=order):
                report = self.check(messages)
                self.assertEqual(report.diagnostics, ())
                self.assertEqual(report.paired, 4)

    def test_same_tool_and_same_arguments_are_not_duplicate_calls(self):
        report = self.check([assistant("a", "b"), result("b"), result("a")])
        self.assertFalse(report.diagnostics)

    def test_reuse_after_resolution_is_warning_and_pairs_locally(self):
        report = self.check([assistant("a"), result(), assistant("a"), result()])
        self.assertEqual(codes(report), ["REUSED_CALL_ID"])
        self.assertEqual((report.errors, report.warnings, report.paired), (0, 1, 2))

    def test_duplicate_batch_ids_are_ambiguous(self):
        report = self.check([assistant("a", "a"), result()])
        self.assertIn("DUPLICATE_CALL_ID", codes(report))
        self.assertIn("AMBIGUOUS_RESULT", codes(report))
        self.assertEqual(report.paired, 0)
        self.assertEqual(report.to_dict()["summary"]["unpaired_calls"], 2)

    def test_orphan_result(self):
        self.assertEqual(codes(self.check([result()])), ["ORPHAN_RESULT"])

    def test_duplicate_result(self):
        report = self.check([assistant("a"), result(), result()])
        self.assertEqual(codes(report), ["DUPLICATE_RESULT"])
        self.assertEqual(report.paired, 1)

    def test_late_result(self):
        report = self.check([assistant("a"), {"role": "user", "content": "next"}, result()])
        self.assertEqual(codes(report), ["MISSING_RESULT", "LATE_RESULT"])

    def test_missing_result_at_tail(self):
        self.assertEqual(codes(self.check([assistant("a")])), ["MISSING_RESULT"])

    def test_allow_pending_tail(self):
        report = self.check([assistant("a", "b"), result("a")], allow_pending_tail=True)
        self.assertEqual(codes(report), ["PENDING_RESULT"])
        self.assertEqual((report.errors, report.warnings), (0, 1))

    def test_pending_mode_does_not_hide_intermediate_loss(self):
        report = self.check([assistant("a"), assistant("b")], allow_pending_tail=True)
        self.assertEqual(codes(report), ["MISSING_RESULT", "PENDING_RESULT"])
        self.assertEqual(report.errors, 1)

    def test_pending_mode_does_not_hide_user_turn(self):
        report = self.check(
            [assistant("a"), {"role": "user", "content": "next"}], allow_pending_tail=True
        )
        self.assertEqual(codes(report), ["MISSING_RESULT"])

    def test_missing_ids_do_not_match_each_other(self):
        for invalid in (None, "", "   ", 17, {}, []):
            with self.subTest(invalid=invalid):
                report = self.check([assistant(invalid), result(invalid)])
                self.assertEqual(codes(report), ["CALL_ID_MISSING", "RESULT_ID_MISSING"])
                self.assertEqual(report.paired, 0)

    def test_argument_json_validation(self):
        for arguments in (None, {}, "{", '{"x":NaN}', '{"x":Infinity}'):
            with self.subTest(arguments=arguments):
                report = self.check(
                    [{"role": "assistant", "tool_calls": [ocall(arguments=arguments)]}, result()]
                )
                self.assertEqual(codes(report), ["ARGUMENTS_NOT_JSON"])

    def test_arguments_must_be_object(self):
        for arguments in ("null", "[]", '"text"', "7", "true"):
            with self.subTest(arguments=arguments):
                report = self.check(
                    [{"role": "assistant", "tool_calls": [ocall(arguments=arguments)]}, result()]
                )
                self.assertEqual(codes(report), ["ARGUMENTS_NOT_OBJECT"])

    def test_valid_argument_values(self):
        report = self.check(
            [
                {
                    "role": "assistant",
                    "tool_calls": [
                        ocall(arguments='{"city":"北京","x":[true,null,2.5],"inner":{}}')
                    ],
                },
                result(),
            ]
        )
        self.assertFalse(report.diagnostics)

    def test_payload_never_appears_in_report(self):
        secret = "PRIVATE_\u001b[31m_SECRET"
        call = ocall(secret, '{"secret":"' + secret + '"}')
        call["function"]["name"] = secret
        report = self.check([{"role": "assistant", "tool_calls": [call]}, result(secret)])
        self.assertNotIn("PRIVATE", json.dumps(report.to_dict()))

    def test_source_locations_for_envelope(self):
        report = self.check({"messages": [assistant("a"), result("wrong")]})
        self.assertEqual(report.diagnostics[0].location, "/messages/1/tool_call_id")
        self.assertEqual(report.diagnostics[1].location, "/messages/0/tool_calls/0/id")

    def test_input_is_not_mutated(self):
        messages = [assistant("a"), result()]
        before = copy.deepcopy(messages)
        self.check(messages)
        self.assertEqual(messages, before)

    def test_unsupported_custom_tool_fails_explicitly(self):
        report = self.check([{"role": "assistant", "tool_calls": [{"id": "a", "type": "custom"}]}])
        self.assertIn("UNSUPPORTED_TOOL", codes(report))

    def test_unsupported_legacy_function_fails(self):
        report = self.check([{"role": "assistant", "function_call": {"name": "old"}}])
        self.assertEqual(codes(report), ["UNSUPPORTED_TOOL"])

    def test_wrong_format_is_not_silent(self):
        report = self.check([message("assistant", acall())])
        self.assertEqual(codes(report), ["FORMAT_MISMATCH"])

    def test_malformed_messages_have_diagnostics_not_tracebacks(self):
        cases = [
            None,
            1,
            [],
            {},
            {"role": []},
            {"role": "assistant", "tool_calls": {}},
            {"role": "assistant", "tool_calls": [None]},
            {"role": "assistant", "tool_calls": [{"type": "function", "id": "a"}]},
            {"role": "user", "tool_calls": [ocall()]},
            {"role": "tool", "tool_call_id": "a"},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertGreater(self.check([case]).errors, 0)


class AnthropicTests(unittest.TestCase):
    def check(self, messages, **kwargs):
        return audit(messages, format="anthropic", **kwargs)

    def test_parallel_results_permutations(self):
        for order in itertools.permutations(("a", "b", "c")):
            with self.subTest(order=order):
                report = self.check(
                    [
                        message(
                            "assistant",
                            {"type": "text", "text": "lookup"},
                            acall("a"),
                            acall("b"),
                            acall("c"),
                        ),
                        message(
                            "user", *(aresult(id) for id in order), {"type": "text", "text": "next"}
                        ),
                        message("assistant", acall("d")),
                        message("user", aresult("d", is_error=True)),
                    ]
                )
                self.assertEqual((report.paired, report.errors, report.warnings), (4, 0, 0))

    def test_adjacent_user_messages_are_one_turn(self):
        report = self.check(
            [
                message("assistant", acall("a"), acall("b")),
                message("user", aresult("a")),
                message("user", aresult("b")),
            ]
        )
        self.assertFalse(report.diagnostics)
        self.assertEqual(report.paired, 2)

    def test_adjacent_assistants_are_one_turn(self):
        report = self.check(
            [
                message("assistant", acall("a")),
                message("assistant", acall("b")),
                message("user", aresult("a"), aresult("b")),
            ]
        )
        self.assertFalse(report.diagnostics)

    def test_adjacent_assistant_duplicate_id(self):
        report = self.check(
            [
                message("assistant", acall()),
                message("assistant", acall()),
                message("user", aresult()),
            ]
        )
        self.assertIn("DUPLICATE_CALL_ID", codes(report))

    def test_order_across_adjacent_user_messages_preserves_location(self):
        report = self.check(
            [
                message("assistant", acall()),
                {"role": "user", "content": "preface"},
                message("user", aresult()),
            ]
        )
        self.assertEqual(codes(report), ["RESULT_ORDER"])
        self.assertEqual(report.diagnostics[0].location, "/2/content/0")

    def test_text_between_results_is_invalid(self):
        report = self.check(
            [
                message("assistant", acall("a"), acall("b")),
                message("user", aresult("a"), {"type": "text"}, aresult("b")),
            ]
        )
        self.assertEqual(codes(report), ["RESULT_ORDER"])

    def test_pending_assistant_tail(self):
        report = self.check([message("assistant", acall())], allow_pending_tail=True)
        self.assertEqual(codes(report), ["PENDING_RESULT"])

    def test_partial_results_pending_at_tail(self):
        report = self.check(
            [message("assistant", acall("a"), acall("b")), message("user", aresult("a"))],
            allow_pending_tail=True,
        )
        self.assertEqual(codes(report), ["PENDING_RESULT"])

    def test_tail_user_text_is_not_pending(self):
        report = self.check(
            [message("assistant", acall()), {"role": "user", "content": "next"}],
            allow_pending_tail=True,
        )
        self.assertEqual(codes(report), ["MISSING_RESULT"])

    def test_missing_intermediate_result_stays_error(self):
        report = self.check(
            [
                message("assistant", acall("a"), acall("b")),
                message("user", aresult("a")),
                message("assistant", acall("c")),
            ],
            allow_pending_tail=True,
        )
        self.assertEqual(codes(report), ["MISSING_RESULT", "PENDING_RESULT"])

    def test_duplicate_orphan_and_late_results(self):
        report = self.check(
            [
                message("assistant", acall("a"), acall("b")),
                message("user", aresult("a"), aresult("a"), aresult("x")),
                message("assistant", {"type": "text"}),
                message("user", aresult("b")),
            ]
        )
        self.assertEqual(
            codes(report), ["DUPLICATE_RESULT", "ORPHAN_RESULT", "MISSING_RESULT", "LATE_RESULT"]
        )

    def test_reused_ids_pair_new_round(self):
        report = self.check(
            [
                message("assistant", acall()),
                message("user", aresult()),
                message("assistant", acall()),
                message("user", aresult()),
            ]
        )
        self.assertEqual(codes(report), ["REUSED_CALL_ID"])
        self.assertEqual(report.paired, 2)

    def test_toolset_names_must_match(self):
        report = self.check(
            [message("assistant", acall(toolset_name="browser")), message("user", aresult())]
        )
        self.assertEqual(codes(report), ["TOOLSET_MISMATCH"])
        valid = self.check(
            [
                message("assistant", acall(toolset_name="browser")),
                message("user", aresult(toolset_name="browser")),
            ]
        )
        self.assertFalse(valid.diagnostics)

    def test_optional_result_content_and_error_are_valid(self):
        report = self.check(
            [message("assistant", acall()), message("user", aresult(is_error=True))]
        )
        self.assertFalse(report.diagnostics)

    def test_tool_input_is_object(self):
        report = self.check([message("assistant", acall(input="{}")), message("user", aresult())])
        self.assertEqual(codes(report), ["ARGUMENTS_NOT_OBJECT"])

    def test_server_and_programmatic_tools_explicitly_unsupported(self):
        for block in (
            {"type": "server_tool_use", "id": "x"},
            {"type": "web_search_tool_result", "tool_use_id": "x"},
            acall(caller={"type": "code_execution_20250825", "tool_id": "x"}),
        ):
            with self.subTest(block=block):
                self.assertIn("UNSUPPORTED_TOOL", codes(self.check([message("assistant", block)])))

    def test_wrong_roles_are_flagged(self):
        self.assertEqual(codes(self.check([message("user", acall())])), ["CALL_ROLE"])
        self.assertEqual(codes(self.check([message("assistant", aresult())])), ["RESULT_ROLE"])

    def test_wrong_format_is_not_silent(self):
        self.assertIn("FORMAT_MISMATCH", codes(self.check([assistant("a")])))

    def test_non_tool_media_are_not_recursively_interpreted(self):
        report = self.check(
            [
                message("assistant", acall()),
                message("user", aresult(content=[{"type": "image", "source": {}}])),
            ]
        )
        self.assertFalse(report.diagnostics)

    def test_malformed_shapes(self):
        for bad in (
            None,
            {},
            {"role": "user", "content": 4},
            message("user", None),
            message("user", {}),
        ):
            with self.subTest(bad=bad):
                self.assertGreater(self.check([bad]).errors, 0)

    def test_system_field_and_mid_conversation_message(self):
        report = self.check(
            {
                "system": "Initial instruction",
                "messages": [
                    message("assistant", acall()),
                    message("user", aresult()),
                    {"role": "system", "content": "Updated instruction"},
                    message("assistant", acall("b")),
                    message("user", aresult("b")),
                ],
            }
        )
        self.assertFalse(report.diagnostics)
        self.assertEqual(report.paired, 2)

    def test_system_does_not_allow_late_result(self):
        report = self.check(
            [
                message("assistant", acall()),
                {"role": "system", "content": "boundary"},
                message("user", aresult()),
            ],
            allow_pending_tail=True,
        )
        self.assertEqual(codes(report), ["MISSING_RESULT", "LATE_RESULT"])

    def test_payload_free_diagnostics_include_toolset_mismatch(self):
        private = "PRIVATE_METADATA"
        report = self.check(
            [
                message(
                    "assistant", acall(private, name=private, toolset_name=private, input=private)
                ),
                message("user", aresult(private, content=private, toolset_name="other_" + private)),
            ]
        )
        self.assertEqual(codes(report), ["ARGUMENTS_NOT_OBJECT", "TOOLSET_MISMATCH"])
        self.assertNotIn(private, json.dumps(report.to_dict()))

    def test_duplicate_id_reports_have_bounded_related_locations(self):
        report = self.check(
            [
                message("assistant", *[acall() for _ in range(2000)]),
                message("user", aresult()),
            ]
        )
        self.assertEqual(report.calls, 2000)
        self.assertEqual(report.paired, 0)
        self.assertLessEqual(max(len(d.related_locations) for d in report.diagnostics), 8)


class EnvelopeTests(unittest.TestCase):
    def test_rejects_response_and_stream_wrappers(self):
        for document in (None, 1, {}, {"choices": []}, {"messages": {}}, "hello"):
            with self.subTest(document=document), self.assertRaises(InputError):
                audit(document, format="openai-chat")

    def test_no_automatic_provider_detection(self):
        with self.assertRaises(InputError):
            audit([], format="auto")

    def test_empty_transcript(self):
        report = audit([], format="anthropic")
        self.assertEqual(report.calls, 0)
        self.assertEqual(report.errors, 0)


if __name__ == "__main__":
    unittest.main()

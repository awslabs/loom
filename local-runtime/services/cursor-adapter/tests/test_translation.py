import unittest

from cursor_adapter.planner import completion_from_planner_text, extract_json_object, normalize_tool_calls
from cursor_adapter.translation import translate_messages


class TestTranslation(unittest.TestCase):
    def test_system_and_user(self) -> None:
        result = translate_messages([
            {"role": "system", "content": "You are a reviewer."},
            {"role": "user", "content": "Look at src/"},
        ])
        self.assertIn("You are a reviewer.", result["prompt"])
        self.assertIn("User: Look at src/", result["prompt"])
        self.assertEqual(result["last_user"], "Look at src/")
        self.assertEqual(result["unsupported_parts"], [])

    def test_tool_call_and_result_kept(self) -> None:
        result = translate_messages([
            {"role": "user", "content": "list files"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "function": {"name": "ls", "arguments": "{\"path\": \".\"}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "a.py"},
        ])
        self.assertIn("[tool_call id=c1 name=ls]", result["prompt"])
        self.assertIn("[tool_result id=c1 ]a.py", result["prompt"])

    def test_image_omitted_not_fatal(self) -> None:
        result = translate_messages([
            {"role": "user", "content": [
                {"type": "text", "text": "see this"},
                {"type": "image_url", "image_url": {"url": "https://example.com/x.png"}},
            ]},
        ])
        self.assertIn("see this", result["prompt"])
        self.assertIn("image_url", result["unsupported_parts"])
        self.assertNotIn("example.com", result["prompt"])


class TestPlanner(unittest.TestCase):
    def test_extract_fenced_json(self) -> None:
        parsed = extract_json_object('```json\n{"content":"ola"}\n```')
        self.assertEqual(parsed, {"content": "ola"})

    def test_normalize_tool_calls(self) -> None:
        calls = normalize_tool_calls([
            {"function": {"name": "ado__list", "arguments": {"org": "x"}}},
        ])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "ado__list")
        self.assertIn("org", calls[0]["function"]["arguments"])

    def test_completion_tool_calls(self) -> None:
        text = (
            '{"tool_calls":[{"id":"c1","type":"function",'
            '"function":{"name":"ado__projects","arguments":"{}"}}]}'
        )
        out = completion_from_planner_text(text)
        message = out["choices"][0]["message"]
        self.assertEqual(out["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "ado__projects")
        # Content carries a JSON fallback for proxies that drop tool_calls.
        self.assertIn("ado__projects", message["content"] or "")

    def test_completion_content(self) -> None:
        out = completion_from_planner_text('{"content":"Matricula em julho"}')
        self.assertEqual(out["choices"][0]["message"]["content"], "Matricula em julho")
        self.assertEqual(out["choices"][0]["finish_reason"], "stop")

    def test_empty_planner_text_not_blank(self) -> None:
        out = completion_from_planner_text("")
        self.assertTrue(out["choices"][0]["message"]["content"])
        self.assertIn("empty", (out["choices"][0]["message"]["content"] or "").lower())

    def test_extract_tools_from_messages(self) -> None:
        from cursor_adapter.planner import extract_tools_from_messages

        tools, cleaned = extract_tools_from_messages([
            {
                "role": "system",
                "content": (
                    "<<<loom_openai_tools>>>\n"
                    '[{"type":"function","function":{"name":"ado__list","parameters":{}}}]\n'
                    "<<<end_loom_openai_tools>>>"
                ),
            },
            {"role": "user", "content": "list projects"},
        ])
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["function"]["name"], "ado__list")
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["role"], "user")


if __name__ == "__main__":
    unittest.main()

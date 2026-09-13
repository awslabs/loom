import unittest

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


if __name__ == "__main__":
    unittest.main()

import unittest

from cursor_adapter.domain.streaming import format_sse, iter_openai_chunks


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Message:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _Event:
    def __init__(self, kind: str, text: str = "") -> None:
        self.type = kind
        self.message = _Message(text)


class TestStreaming(unittest.TestCase):
    def test_assistant_then_stop(self) -> None:
        chunks = list(iter_openai_chunks([_Event("assistant", "hello"), _Event("status")], model="cursor-local"))
        texts = [c["choices"][0]["delta"].get("content") for c in chunks]
        self.assertIn("hello", texts)
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")
        self.assertTrue(any(c.get("x_cursor_event", {}).get("type") == "status" for c in chunks))

    def test_sse_shape(self) -> None:
        line = format_sse({"id": "1", "choices": []})
        self.assertTrue(line.startswith("data: {"))
        self.assertTrue(line.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()

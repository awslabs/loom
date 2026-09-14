"""Tests for local agent template BFF (Spec 026 A2)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.local_agent_templates import LocalTemplateError, materialize_local_template


class TestLocalAgentTemplatesClient(unittest.TestCase):
    @patch("app.services.local_agent_templates.agent_runtime_base_url", return_value="")
    def test_requires_runtime_url(self, _base) -> None:
        with self.assertRaises(LocalTemplateError) as ctx:
            materialize_local_template("assistente-local", params={"objective": "x"})
        self.assertEqual(ctx.exception.status_code, 503)

    @patch("app.services.local_agent_templates.agent_runtime_token", return_value="tok")
    @patch("app.services.local_agent_templates.agent_runtime_base_url", return_value="http://agent-runtime:8766")
    @patch("app.services.local_agent_templates.httpx.Client")
    def test_materialize_ok(self, client_cls, _base, _token) -> None:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.json.return_value = {
            "template_id": "assistente-local",
            "config": {
                "template_id": "assistente-local",
                "model_id": "cursor-local",
                "system_prompt": "Objetivo: x",
                "allowed_model_ids": ["cursor-local"],
            },
        }
        config = materialize_local_template("assistente-local", params={"objective": "x"})
        self.assertEqual(config["template_id"], "assistente-local")
        self.assertIn("Objetivo", config["system_prompt"])


if __name__ == "__main__":
    unittest.main()

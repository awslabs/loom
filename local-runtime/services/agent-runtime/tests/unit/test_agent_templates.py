import unittest
from pathlib import Path

from agent_runtime.adapters.outbound.yaml_agent_templates import (
    get_template,
    load_templates,
    public_templates,
    templates_dir,
)
from agent_runtime.domain.agent_template import (
    materialize_agent_config,
    parse_agent_template,
    resolve_system_prompt,
)
from agent_runtime.domain.errors import TemplateError


class TestAgentTemplates(unittest.TestCase):
    def test_templates_dir_points_at_service_allowlist(self) -> None:
        root = Path(__file__).resolve().parents[2] / "templates"
        self.assertEqual(templates_dir().resolve(), root.resolve())
        self.assertTrue((root / "guia-biblioteca.yaml").is_file())

    def test_loads_guia_biblioteca(self) -> None:
        template = get_template("guia-biblioteca")
        self.assertEqual(template.display_name, "Guia da Biblioteca")
        self.assertEqual(template.model_id, "cursor-local")
        self.assertIn("cursor-local", template.allowed_model_ids)
        self.assertIn("acervo-faq.txt", template.knowledge_files)
        self.assertIn("Biblioteca Municipal", template.system_prompt)

    def test_load_templates_includes_example(self) -> None:
        found = load_templates()
        self.assertIn("guia-biblioteca", found)

    def test_rejects_unknown_template(self) -> None:
        with self.assertRaises(TemplateError) as ctx:
            get_template("not-a-real-template")
        self.assertIn("unknown template_id", str(ctx.exception))

    def test_rejects_missing_system_prompt(self) -> None:
        with self.assertRaises(TemplateError):
            parse_agent_template({
                "id": "bad-agent",
                "model_id": "mock-echo",
                "system_prompt": "   ",
            })

    def test_rejects_bad_id(self) -> None:
        with self.assertRaises(TemplateError):
            parse_agent_template({
                "id": "Bad_ID",
                "model_id": "mock-echo",
                "system_prompt": "ok",
            })

    def test_rejects_model_not_in_allowed(self) -> None:
        with self.assertRaises(TemplateError):
            parse_agent_template({
                "id": "demo-agent",
                "model_id": "cursor-local",
                "allowed_model_ids": ["mock-echo"],
                "system_prompt": "ok",
            })

    def test_resolve_prompt_override_and_inline(self) -> None:
        base = parse_agent_template({
            "id": "demo-agent",
            "model_id": "mock-echo",
            "system_prompt": "Base prompt.",
            "knowledge": {"inline": "FAQ: horário 9–17."},
        })
        self.assertIn("FAQ:", resolve_system_prompt(base))
        self.assertEqual(
            resolve_system_prompt(base, override="  Override only.  "),
            "Override only.",
        )

    def test_materialize_config_shape(self) -> None:
        template = get_template("guia-biblioteca")
        config = materialize_agent_config(template)
        self.assertEqual(config["template_id"], "guia-biblioteca")
        self.assertEqual(config["provider"], "litellm")
        self.assertTrue(config["system_prompt"])
        self.assertEqual(config["knowledge"]["files"], ["acervo-faq.txt"])

    def test_public_templates_omit_secret_values(self) -> None:
        rows = public_templates()
        self.assertTrue(any(row["id"] == "guia-biblioteca" for row in rows))
        for row in rows:
            self.assertNotIn("system_prompt", row)


if __name__ == "__main__":
    unittest.main()

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
    validate_params,
)
from agent_runtime.domain.errors import TemplateError


class TestAgentTemplates(unittest.TestCase):
    def test_templates_dir_points_at_service_allowlist(self) -> None:
        root = Path(__file__).resolve().parents[2] / "templates"
        self.assertEqual(templates_dir().resolve(), root.resolve())
        self.assertTrue((root / "assistente-local.yaml").is_file())

    def test_loads_assistente_local(self) -> None:
        template = get_template("assistente-local")
        self.assertEqual(template.display_name, "Assistente Local")
        self.assertEqual(template.model_id, "cursor-local")
        self.assertIn("objective", template.params_schema)

    def test_materialize_applies_objective(self) -> None:
        template = get_template("assistente-local")
        config = materialize_agent_config(
            template, params={"objective": "Responder FAQ interno da equipe"}
        )
        self.assertEqual(config["template_id"], "assistente-local")
        self.assertIn("FAQ interno", config["system_prompt"])
        self.assertEqual(config["template_params"]["objective"], "Responder FAQ interno da equipe")

    def test_rejects_missing_required_param(self) -> None:
        template = get_template("assistente-local")
        with self.assertRaises(TemplateError):
            validate_params(template, {})

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

    def test_override_wins_over_template(self) -> None:
        template = get_template("assistente-local")
        text = resolve_system_prompt(
            template,
            params={"objective": "X"},
            override="  Prompt customizado.  ",
        )
        self.assertEqual(text, "Prompt customizado.")

    def test_public_templates_omit_system_prompt(self) -> None:
        rows = public_templates()
        self.assertTrue(any(row["id"] == "assistente-local" for row in rows))
        for row in rows:
            self.assertNotIn("system_prompt", row)
            self.assertIn("params_schema", row)

    def test_load_templates_includes_example(self) -> None:
        self.assertIn("assistente-local", load_templates())


if __name__ == "__main__":
    unittest.main()

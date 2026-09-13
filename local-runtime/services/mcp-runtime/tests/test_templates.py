import unittest
from pathlib import Path

from mcp_runtime.templates import TemplateError, get_template, render_args, validate_params


class TestTemplates(unittest.TestCase):
    def test_azure_devops_template_is_allowlisted(self) -> None:
        template = get_template("azure-devops")
        self.assertEqual(template["command"], "npx")
        params = validate_params(template, {"organization": "minha-org"})
        args = render_args(template, params)
        self.assertIn("minha-org", args)
        self.assertIn("--package=@azure-devops/mcp@2.9.0", args)
        self.assertIn("mcp-server-azuredevops", args)
        self.assertIn("--authentication", args)
        self.assertIn("envvar", args)

    def test_rejects_unknown_template(self) -> None:
        with self.assertRaises(TemplateError):
            get_template("not-a-real-template")

    def test_rejects_shell_metachar_in_params(self) -> None:
        template = get_template("azure-devops")
        with self.assertRaises(TemplateError):
            validate_params(template, {"organization": "org;rm -rf /"})

    def test_templates_live_in_repo_allowlist(self) -> None:
        root = Path(__file__).resolve().parents[3] / "templates"
        self.assertTrue((root / "azure-devops.yaml").is_file())

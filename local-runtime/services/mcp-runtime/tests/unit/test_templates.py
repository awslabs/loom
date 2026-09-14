import unittest
from pathlib import Path

from mcp_runtime.adapters.outbound.yaml_templates import (
    get_template,
    render_args,
    render_env,
    validate_params,
)
from mcp_runtime.domain.errors import TemplateError


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

    def test_grafana_template_injects_url_env(self) -> None:
        template = get_template("grafana")
        self.assertEqual(template["command"], "uvx")
        params = validate_params(
            template,
            {"grafana_url": "http://host.docker.internal:3000"},
        )
        args = render_args(template, params)
        self.assertIn("--from", args)
        self.assertIn("mcp-grafana==1.4.1", args)
        self.assertEqual(
            render_env(template, params)["GRAFANA_URL"],
            "http://host.docker.internal:3000",
        )

    def test_rancher_template_passes_url_arg(self) -> None:
        template = get_template("rancher")
        self.assertEqual(template["command"], "npx")
        params = validate_params(
            template,
            {"rancher_server_url": "https://host.docker.internal:8443"},
        )
        args = render_args(template, params)
        self.assertIn("--package=rancher-mcp-server@0.9.1", args)
        self.assertIn("https://host.docker.internal:8443", args)
        self.assertIn("rancher,kubernetes,fleet", args)

    def test_rejects_unknown_template(self) -> None:
        with self.assertRaises(TemplateError):
            get_template("not-a-real-template")

    def test_rejects_shell_metachar_in_params(self) -> None:
        template = get_template("azure-devops")
        with self.assertRaises(TemplateError):
            validate_params(template, {"organization": "org;rm -rf /"})

    def test_templates_live_in_repo_allowlist(self) -> None:
        root = Path(__file__).resolve().parents[2] / "templates"
        self.assertTrue((root / "azure-devops.yaml").is_file())
        self.assertTrue((root / "grafana.yaml").is_file())
        self.assertTrue((root / "rancher.yaml").is_file())

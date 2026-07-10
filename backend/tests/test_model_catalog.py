"""Tests for the dynamic model catalog service."""
import unittest
from unittest.mock import MagicMock, patch

from app.services import model_catalog
from app.services.model_catalog import (
    _build_bedrock_models,
    _build_litellm_models,
    _fetch_bedrock_availability,
    _fetch_bedrock_catalog,
    _fetch_litellm_catalog,
    _fetch_litellm_proxy_catalog,
    _litellm_pricing_by_normalized_id,
    _merge_models,
    _normalize_model_id,
    get_bedrock_models,
    get_litellm_models_live,
    get_merged_models,
)


class TestNormalizeModelId(unittest.TestCase):
    def test_strips_region_prefix(self):
        self.assertEqual(
            _normalize_model_id("us.anthropic.claude-sonnet-4-6"),
            "anthropic.claude-sonnet-4-6",
        )

    def test_strips_bedrock_prefix(self):
        self.assertEqual(
            _normalize_model_id("bedrock/anthropic.claude-sonnet-4-6"),
            "anthropic.claude-sonnet-4-6",
        )

    def test_strips_combined_prefixes(self):
        self.assertEqual(
            _normalize_model_id("bedrock/us.anthropic.claude-sonnet-4-6"),
            "anthropic.claude-sonnet-4-6",
        )

    def test_lowercases(self):
        self.assertEqual(
            _normalize_model_id("US.Anthropic.Claude-Sonnet-4-6"),
            "anthropic.claude-sonnet-4-6",
        )

    def test_no_prefix_unchanged(self):
        self.assertEqual(
            _normalize_model_id("deepseek.v3.2"),
            "deepseek.v3.2",
        )


class TestFetchBedrockAvailability(unittest.TestCase):
    @patch("boto3.client")
    def test_success_combines_models_and_profiles(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.list_foundation_models.return_value = {
            "modelSummaries": [{"modelId": "anthropic.claude-opus-4-7"}]
        }
        mock_client.list_inference_profiles.return_value = {
            "inferenceProfileSummaries": [
                {"inferenceProfileId": "us.anthropic.claude-sonnet-4-6"}
            ],
            "nextToken": None,
        }

        result = _fetch_bedrock_availability("us-east-1")

        self.assertEqual(
            result,
            {"anthropic.claude-opus-4-7", "anthropic.claude-sonnet-4-6"},
        )
        mock_boto_client.assert_called_once_with("bedrock", region_name="us-east-1")

    @patch("boto3.client")
    def test_paginates_inference_profiles(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.list_foundation_models.return_value = {"modelSummaries": []}
        mock_client.list_inference_profiles.side_effect = [
            {
                "inferenceProfileSummaries": [{"inferenceProfileId": "us.anthropic.a"}],
                "nextToken": "page2",
            },
            {
                "inferenceProfileSummaries": [{"inferenceProfileId": "us.anthropic.b"}],
            },
        ]

        result = _fetch_bedrock_availability("us-east-1")

        self.assertEqual(result, {"anthropic.a", "anthropic.b"})
        self.assertEqual(mock_client.list_inference_profiles.call_count, 2)

    @patch("boto3.client")
    def test_exception_returns_none(self, mock_boto_client):
        mock_boto_client.side_effect = Exception("no credentials")
        result = _fetch_bedrock_availability("us-east-1")
        self.assertIsNone(result)


class TestFetchBedrockCatalog(unittest.TestCase):
    @patch("boto3.client")
    def test_success_combines_models_and_profiles(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.list_foundation_models.return_value = {
            "modelSummaries": [
                {"modelId": "anthropic.claude-opus-4-7", "modelName": "Claude Opus 4.7"}
            ]
        }
        mock_client.list_inference_profiles.return_value = {
            "inferenceProfileSummaries": [
                {
                    "inferenceProfileId": "us.anthropic.claude-sonnet-4-6",
                    "inferenceProfileName": "Claude Sonnet 4.6",
                }
            ],
            "nextToken": None,
        }

        result = _fetch_bedrock_catalog("us-east-1")

        self.assertEqual(
            result["anthropic.claude-opus-4-7"],
            {"model_id": "anthropic.claude-opus-4-7", "model_name": "Claude Opus 4.7", "lab": "anthropic"},
        )
        self.assertEqual(
            result["anthropic.claude-sonnet-4-6"],
            {"model_id": "us.anthropic.claude-sonnet-4-6", "model_name": "Claude Sonnet 4.6", "lab": "anthropic"},
        )

    @patch("boto3.client")
    def test_filters_out_disallowed_labs(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.list_foundation_models.return_value = {
            "modelSummaries": [
                {"modelId": "anthropic.claude-opus-4-7", "modelName": "Claude Opus 4.7"},
                {"modelId": "meta.llama3-8b-instruct-v1:0", "modelName": "Llama 3 8B"},
                {"modelId": "amazon.nova-pro-v1:0", "modelName": "Nova Pro"},
                {"modelId": "deepseek.r1-v1:0", "modelName": "DeepSeek R1"},
                {"modelId": "qwen.qwen3-32b-v1:0", "modelName": "Qwen3 32B"},
                {"modelId": "zai.glm-5", "modelName": "GLM-5"},
                {"modelId": "openai.gpt-oss-120b-1:0", "modelName": "gpt-oss-120b"},
                {"modelId": "mistral.mistral-large-3", "modelName": "Mistral Large 3"},
                {"modelId": "cohere.command-r-v1:0", "modelName": "Command R"},
            ]
        }
        mock_client.list_inference_profiles.return_value = {"inferenceProfileSummaries": []}

        result = _fetch_bedrock_catalog("us-east-1")

        self.assertEqual(
            set(result.keys()),
            {
                "anthropic.claude-opus-4-7",
                "amazon.nova-pro-v1:0",
                "deepseek.r1-v1:0",
                "qwen.qwen3-32b-v1:0",
                "zai.glm-5",
                "openai.gpt-oss-120b-1:0",
            },
        )
        self.assertNotIn("meta.llama3-8b-instruct-v1:0", result)
        self.assertNotIn("mistral.mistral-large-3", result)
        self.assertNotIn("cohere.command-r-v1:0", result)

    @patch("boto3.client")
    def test_inference_profile_overrides_foundation_model_entry(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.list_foundation_models.return_value = {
            "modelSummaries": [
                {"modelId": "anthropic.claude-sonnet-4-6", "modelName": "Claude Sonnet 4.6"}
            ]
        }
        mock_client.list_inference_profiles.return_value = {
            "inferenceProfileSummaries": [
                {
                    "inferenceProfileId": "us.anthropic.claude-sonnet-4-6",
                    "inferenceProfileName": "US Claude Sonnet 4.6",
                }
            ],
        }

        result = _fetch_bedrock_catalog("us-east-1")

        self.assertEqual(result["anthropic.claude-sonnet-4-6"]["model_id"], "us.anthropic.claude-sonnet-4-6")

    @patch("boto3.client")
    def test_exception_returns_none(self, mock_boto_client):
        mock_boto_client.side_effect = Exception("no credentials")
        self.assertIsNone(_fetch_bedrock_catalog("us-east-1"))


class TestBuildBedrockModels(unittest.TestCase):
    def test_skips_models_already_curated(self):
        bedrock_catalog = {
            "anthropic.claude-sonnet-4-6": {
                "model_id": "us.anthropic.claude-sonnet-4-6",
                "model_name": "Claude Sonnet 4.6",
                "lab": "anthropic",
            },
        }
        static_by_normalized_id = {"anthropic.claude-sonnet-4-6": {"model_id": "us.anthropic.claude-sonnet-4-6"}}

        models = _build_bedrock_models(bedrock_catalog, {}, static_by_normalized_id)

        self.assertEqual(models, [])

    def test_new_model_with_pricing_match(self):
        bedrock_catalog = {
            "anthropic.claude-opus-4-8": {
                "model_id": "us.anthropic.claude-opus-4-8",
                "model_name": "Claude Opus 4.8",
                "lab": "anthropic",
            },
        }
        pricing = {
            "anthropic.claude-opus-4-8": {
                "input_cost_per_token": 0.000005,
                "output_cost_per_token": 0.000025,
                "max_tokens": 32000,
            }
        }

        models = _build_bedrock_models(bedrock_catalog, pricing, {})

        self.assertEqual(len(models), 1)
        entry = models[0]
        self.assertEqual(entry["model_id"], "us.anthropic.claude-opus-4-8")
        self.assertEqual(entry["display_name"], "Claude Opus 4.8")
        self.assertEqual(entry["group"], "Anthropic")
        self.assertEqual(entry["provider"], "bedrock")
        self.assertTrue(entry["available"])
        self.assertAlmostEqual(entry["input_price_per_1k_tokens"], 0.005)
        self.assertAlmostEqual(entry["output_price_per_1k_tokens"], 0.025)
        self.assertEqual(entry["max_tokens"], 32000)
        self.assertEqual(entry["pricing_source"], "litellm")

    def test_new_model_without_pricing_match_is_skipped(self):
        bedrock_catalog = {
            "deepseek.r1-v1:0": {
                "model_id": "us.deepseek.r1-v1:0",
                "model_name": "DeepSeek R1",
                "lab": "deepseek",
            },
        }

        models = _build_bedrock_models(bedrock_catalog, {}, {})

        # No pricing match -> skipped entirely, not surfaced with a fake price.
        self.assertEqual(models, [])


class TestFetchLitellmProxyCatalog(unittest.TestCase):
    """_fetch_litellm_proxy_catalog resolves the proxy connection via
    app.services.litellm.get_litellm_proxy_config (Settings-page override,
    falling back to env vars), not directly from os.environ."""

    @patch("httpx.get")
    @patch("app.services.litellm.get_litellm_proxy_config")
    def test_success_reshapes_model_info_response(self, mock_config, mock_get):
        mock_config.return_value = ("http://litellm.internal:4000", "sk-test")
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "model_name": "gpt-4o",
                    "model_info": {
                        "input_cost_per_token": 0.0000025,
                        "output_cost_per_token": 0.00001,
                        "mode": "chat",
                    },
                },
                {"model_name": "bad-entry", "model_info": "not-a-dict"},
                {"model_name": None, "model_info": {"input_cost_per_token": 0.1}},
            ]
        }
        mock_get.return_value = mock_response

        result = _fetch_litellm_proxy_catalog()

        self.assertEqual(list(result.keys()), ["gpt-4o"])
        mock_get.assert_called_once_with(
            "http://litellm.internal:4000/model/info",
            headers={"Authorization": "Bearer sk-test"},
            timeout=5.0,
        )

    @patch("app.services.litellm.get_litellm_proxy_config", return_value=None)
    def test_unconfigured_disables_fetch(self, mock_config):
        self.assertIsNone(_fetch_litellm_proxy_catalog())

    @patch("httpx.get")
    @patch("app.services.litellm.get_litellm_proxy_config")
    def test_network_failure_returns_none(self, mock_config, mock_get):
        mock_config.return_value = ("http://litellm.internal:4000", "sk-test")
        mock_get.side_effect = Exception("timeout")
        self.assertIsNone(_fetch_litellm_proxy_catalog())

    @patch("httpx.get")
    @patch("app.services.litellm.get_litellm_proxy_config")
    def test_non_dict_response_returns_none(self, mock_config, mock_get):
        mock_config.return_value = ("http://litellm.internal:4000", "sk-test")
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "not-a-list"}
        mock_get.return_value = mock_response
        self.assertIsNone(_fetch_litellm_proxy_catalog())


class TestFetchLitellmCatalog(unittest.TestCase):
    @patch("httpx.get")
    def test_success_returns_raw_catalog(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "anthropic.claude-sonnet-4-6": {
                "input_cost_per_token": 0.000003,
                "output_cost_per_token": 0.000015,
                "max_tokens": 16384,
                "litellm_provider": "bedrock",
            },
        }
        mock_get.return_value = mock_response

        result = _fetch_litellm_catalog()

        self.assertIn("anthropic.claude-sonnet-4-6", result)
        self.assertEqual(result["anthropic.claude-sonnet-4-6"]["max_tokens"], 16384)

    @patch("httpx.get")
    def test_network_failure_returns_none(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        self.assertIsNone(_fetch_litellm_catalog())

    @patch.dict("os.environ", {"LOOM_LITELLM_PRICING_URL": ""})
    def test_empty_url_disables_fetch(self):
        self.assertIsNone(_fetch_litellm_catalog())

    @patch("httpx.get")
    def test_non_dict_response_returns_none(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = ["not", "a", "dict"]
        mock_get.return_value = mock_response
        self.assertIsNone(_fetch_litellm_catalog())


class TestLitellmPricingByNormalizedId(unittest.TestCase):
    def test_parses_pricing_and_skips_invalid_entries(self):
        raw_catalog = {
            "anthropic.claude-sonnet-4-6": {
                "input_cost_per_token": 0.000003,
                "output_cost_per_token": 0.000015,
                "max_tokens": 16384,
                "litellm_provider": "bedrock",
            },
            "some-entry-without-cost": {"litellm_provider": "bedrock"},
            "not-a-dict-entry": "ignored",
        }

        result = _litellm_pricing_by_normalized_id(raw_catalog)

        self.assertIn("anthropic.claude-sonnet-4-6", result)
        entry = result["anthropic.claude-sonnet-4-6"]
        self.assertEqual(entry["input_cost_per_token"], 0.000003)
        self.assertEqual(entry["max_tokens"], 16384)
        self.assertNotIn("some-entry-without-cost", result)
        self.assertNotIn("not-a-dict-entry", result)


class TestBuildLitellmModels(unittest.TestCase):
    def test_uses_raw_key_as_model_id_and_computes_pricing(self):
        raw_catalog = {
            "gpt-4o": {
                "input_cost_per_token": 0.0000025,
                "output_cost_per_token": 0.00001,
                "max_input_tokens": 128000,
                "litellm_provider": "openai",
                "mode": "chat",
            },
        }

        models = _build_litellm_models(raw_catalog)

        self.assertEqual(len(models), 1)
        entry = models[0]
        self.assertEqual(entry["model_id"], "gpt-4o")
        self.assertEqual(entry["provider"], "litellm")
        self.assertAlmostEqual(entry["input_price_per_1k_tokens"], 0.0025)
        self.assertAlmostEqual(entry["output_price_per_1k_tokens"], 0.01)
        self.assertEqual(entry["max_tokens"], 128000)
        self.assertEqual(entry["pricing_source"], "litellm")

    def test_skips_sample_spec_and_non_chat_modes(self):
        raw_catalog = {
            "sample_spec": {"input_cost_per_token": 0.1, "output_cost_per_token": 0.1},
            "text-embedding-3-small": {
                "input_cost_per_token": 0.00000002,
                "output_cost_per_token": 0,
                "mode": "embedding",
            },
            "not-a-dict": "ignored",
            "no-cost-entry": {"mode": "chat"},
        }

        models = _build_litellm_models(raw_catalog)

        self.assertEqual(models, [])

    def test_defaults_missing_provider_and_mode(self):
        raw_catalog = {
            "custom-model": {
                "input_cost_per_token": 0.000001,
                "output_cost_per_token": 0.000002,
            },
        }

        models = _build_litellm_models(raw_catalog)

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["group"], "LiteLLM / other")

    def test_direct_bedrock_alias_grouped_as_bedrock(self):
        raw_catalog = {
            "claude-sonnet-5": {
                "key": "anthropic.claude-sonnet-5",
                "litellm_provider": "bedrock_converse",
                "mode": "chat",
                "input_cost_per_token": 0.000002,
                "output_cost_per_token": 0.00001,
            },
        }

        models = _build_litellm_models(raw_catalog)

        self.assertEqual(models[0]["group"], "Bedrock")

    def test_bedrock_backed_alias_with_mismatched_key_grouped_as_router(self):
        raw_catalog = {
            "claude-auto": {
                "key": "anthropic.claude-opus-4-8",
                "litellm_provider": "bedrock_converse",
                "mode": "chat",
                "input_cost_per_token": 0.000005,
                "output_cost_per_token": 0.000025,
            },
        }

        models = _build_litellm_models(raw_catalog)

        self.assertEqual(models[0]["group"], "Router")

    def test_auto_router_provider_grouped_as_router(self):
        raw_catalog = {
            "claude-heuristic": {
                "key": "auto_router/adaptive_router",
                "litellm_provider": "auto_router",
                "mode": None,
                "input_cost_per_token": 0,
                "output_cost_per_token": 0,
            },
        }

        models = _build_litellm_models(raw_catalog)

        self.assertEqual(models[0]["group"], "Router")

    def test_non_bedrock_provider_grouped_as_litellm_prefixed(self):
        raw_catalog = {
            "gpt-4o": {
                "key": "openai.gpt-4o",
                "litellm_provider": "openai",
                "mode": "chat",
                "input_cost_per_token": 0.0000025,
                "output_cost_per_token": 0.00001,
            },
        }

        models = _build_litellm_models(raw_catalog)

        self.assertEqual(models[0]["group"], "LiteLLM / openai")


class TestMergeModels(unittest.TestCase):
    def setUp(self):
        self.static_models = [
            {
                "model_id": "us.anthropic.claude-sonnet-4-6",
                "display_name": "Claude Sonnet 4.6",
                "input_price_per_1k_tokens": 0.003,
                "output_price_per_1k_tokens": 0.015,
                "max_tokens": 8192,
                "pricing_as_of": "2025-06-01",
            }
        ]

    def test_both_sources_succeed(self):
        availability = {"anthropic.claude-sonnet-4-6"}
        pricing = {
            "anthropic.claude-sonnet-4-6": {
                "input_cost_per_token": 0.000004,
                "output_cost_per_token": 0.00002,
                "max_tokens": 16384,
            }
        }
        merged = _merge_models(self.static_models, availability, pricing)

        entry = merged[0]
        self.assertTrue(entry["available"])
        self.assertEqual(entry["pricing_source"], "litellm")
        self.assertIsNotNone(entry["pricing_fetched_at"])
        self.assertAlmostEqual(entry["input_price_per_1k_tokens"], 0.004)
        self.assertAlmostEqual(entry["output_price_per_1k_tokens"], 0.02)
        self.assertEqual(entry["max_tokens"], 16384)
        # original static list must not be mutated
        self.assertEqual(self.static_models[0]["input_price_per_1k_tokens"], 0.003)

    def test_availability_fails_pricing_succeeds(self):
        pricing = {
            "anthropic.claude-sonnet-4-6": {
                "input_cost_per_token": 0.000004,
                "output_cost_per_token": 0.00002,
            }
        }
        merged = _merge_models(self.static_models, None, pricing)
        entry = merged[0]
        self.assertIsNone(entry["available"])
        self.assertEqual(entry["pricing_source"], "litellm")

    def test_pricing_fails_availability_succeeds(self):
        availability = {"anthropic.claude-sonnet-4-6"}
        merged = _merge_models(self.static_models, availability, None)
        entry = merged[0]
        self.assertTrue(entry["available"])
        self.assertEqual(entry["pricing_source"], "static")
        self.assertIsNone(entry["pricing_fetched_at"])
        self.assertEqual(entry["input_price_per_1k_tokens"], 0.003)

    def test_both_sources_fail_returns_static_pricing_unchanged(self):
        merged = _merge_models(self.static_models, None, None)
        entry = merged[0]
        self.assertIsNone(entry["available"])
        self.assertEqual(entry["pricing_source"], "static")
        self.assertEqual(entry["input_price_per_1k_tokens"], 0.003)
        self.assertEqual(entry["output_price_per_1k_tokens"], 0.015)

    def test_availability_false_when_not_in_live_set(self):
        merged = _merge_models(self.static_models, set(), {})
        entry = merged[0]
        self.assertFalse(entry["available"])


class TestGetBedrockModelsCaching(unittest.TestCase):
    """get_bedrock_models must never depend on the LiteLLM proxy — only the
    public catalog (for pricing enrichment) and live Bedrock data."""

    def setUp(self):
        # Reset the module-level cache before each test to avoid cross-test
        # contamination (the cache is process-global by design).
        model_catalog._cache["data"] = None
        model_catalog._cache["fetched_at"] = 0.0

    def tearDown(self):
        model_catalog._cache["data"] = None
        model_catalog._cache["fetched_at"] = 0.0

    @patch("app.services.model_catalog._fetch_bedrock_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_litellm_catalog")
    @patch("app.services.model_catalog._fetch_bedrock_availability")
    def test_fetches_once_within_ttl(self, mock_availability, mock_catalog, mock_bedrock_catalog):
        mock_availability.return_value = {"anthropic.claude-sonnet-4-6"}
        mock_catalog.return_value = {}
        fake_static = [{"model_id": "us.anthropic.claude-sonnet-4-6"}]

        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            get_bedrock_models("us-east-1")
            get_bedrock_models("us-east-1")

        self.assertEqual(mock_availability.call_count, 1)
        self.assertEqual(mock_catalog.call_count, 1)

    @patch("app.services.model_catalog._fetch_bedrock_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_litellm_catalog")
    @patch("app.services.model_catalog._fetch_bedrock_availability")
    @patch("app.services.model_catalog._ttl_seconds", return_value=0)
    def test_refetches_after_ttl_expires(self, mock_ttl, mock_availability, mock_catalog, mock_bedrock_catalog):
        mock_availability.return_value = set()
        mock_catalog.return_value = {}
        fake_static = [{"model_id": "us.anthropic.claude-sonnet-4-6"}]

        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            get_bedrock_models("us-east-1")
            get_bedrock_models("us-east-1")

        self.assertEqual(mock_availability.call_count, 2)

    @patch("app.services.model_catalog._fetch_bedrock_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_litellm_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_availability", return_value=None)
    def test_both_fetchers_failing_still_returns_static_list(self, mock_availability, mock_catalog, mock_bedrock_catalog):
        fake_static = [
            {"model_id": "us.anthropic.claude-sonnet-4-6", "input_price_per_1k_tokens": 0.003, "provider": "bedrock"},
        ]
        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            result = get_bedrock_models("us-east-1")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["input_price_per_1k_tokens"], 0.003)
        self.assertIsNone(result[0]["available"])

    @patch("app.services.model_catalog._fetch_litellm_catalog")
    @patch("app.services.model_catalog._fetch_bedrock_availability", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_catalog")
    def test_live_bedrock_catalog_adds_uncurated_models_with_pricing(
        self, mock_bedrock_catalog, mock_availability, mock_public_catalog
    ):
        mock_bedrock_catalog.return_value = {
            "anthropic.claude-sonnet-4-6": {
                "model_id": "us.anthropic.claude-sonnet-4-6",
                "model_name": "Claude Sonnet 4.6",
                "lab": "anthropic",
            },
            "anthropic.claude-opus-4-8": {
                "model_id": "us.anthropic.claude-opus-4-8",
                "model_name": "Claude Opus 4.8",
                "lab": "anthropic",
            },
        }
        mock_public_catalog.return_value = {
            "anthropic.claude-opus-4-8": {
                "input_cost_per_token": 0.000005,
                "output_cost_per_token": 0.000025,
            },
        }
        fake_static = [
            {
                "model_id": "us.anthropic.claude-sonnet-4-6",
                "display_name": "Claude Sonnet 4.6 (curated)",
                "provider": "bedrock",
            },
        ]

        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            result = get_bedrock_models("us-east-1")

        bedrock_ids = {m["model_id"] for m in result}
        self.assertEqual(bedrock_ids, {"us.anthropic.claude-sonnet-4-6", "us.anthropic.claude-opus-4-8"})
        curated_entry = next(m for m in result if m["model_id"] == "us.anthropic.claude-sonnet-4-6")
        self.assertEqual(curated_entry["display_name"], "Claude Sonnet 4.6 (curated)")
        new_entry = next(m for m in result if m["model_id"] == "us.anthropic.claude-opus-4-8")
        self.assertEqual(new_entry["display_name"], "Claude Opus 4.8")
        self.assertEqual(new_entry["pricing_source"], "litellm")

    @patch("app.services.model_catalog._fetch_litellm_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_availability", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_catalog")
    def test_live_bedrock_catalog_without_pricing_is_excluded(self, mock_bedrock_catalog, mock_availability, mock_public_catalog):
        mock_bedrock_catalog.return_value = {
            "anthropic.claude-opus-4-8": {
                "model_id": "us.anthropic.claude-opus-4-8",
                "model_name": "Claude Opus 4.8",
                "lab": "anthropic",
            },
        }
        fake_static: list = []

        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            result = get_bedrock_models("us-east-1")

        self.assertEqual(result, [])

    @patch("app.services.model_catalog._fetch_litellm_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_availability", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_catalog", return_value=None)
    def test_static_list_filtered_to_allowed_labs(self, mock_bedrock_catalog, mock_availability, mock_public_catalog):
        fake_static = [
            {"model_id": "anthropic.claude-sonnet-4-6", "provider": "bedrock", "input_price_per_1k_tokens": 0.003},
            {"model_id": "meta.llama3-70b-instruct-v1:0", "provider": "bedrock", "input_price_per_1k_tokens": 0.001},
            {"model_id": "google.gemma-3-27b-it", "provider": "bedrock", "input_price_per_1k_tokens": 0.0002},
        ]

        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            result = get_bedrock_models("us-east-1")

        self.assertEqual({m["model_id"] for m in result}, {"anthropic.claude-sonnet-4-6"})

    @patch("app.services.model_catalog._fetch_bedrock_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_availability", return_value=None)
    @patch("app.services.model_catalog._fetch_litellm_proxy_catalog")
    def test_never_calls_the_litellm_proxy(self, mock_proxy_catalog, mock_availability, mock_bedrock_catalog):
        fake_static = [{"model_id": "us.anthropic.claude-sonnet-4-6", "provider": "bedrock"}]

        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            get_bedrock_models("us-east-1")

        mock_proxy_catalog.assert_not_called()


class TestGetLitellmModelsLive(unittest.TestCase):
    """get_litellm_models_live must only ever reflect what's configured on
    the deployed proxy — no public GitHub fallback, no static placeholder."""

    def setUp(self):
        model_catalog._litellm_cache["data"] = None
        model_catalog._litellm_cache["fetched_at"] = 0.0

    def tearDown(self):
        model_catalog._litellm_cache["data"] = None
        model_catalog._litellm_cache["fetched_at"] = 0.0

    @patch("app.services.model_catalog._fetch_litellm_catalog")
    @patch("app.services.model_catalog._fetch_litellm_proxy_catalog")
    def test_returns_proxy_models_and_never_falls_back_to_public_catalog(self, mock_proxy_catalog, mock_public_catalog):
        mock_proxy_catalog.return_value = {
            "proxy-only-model": {
                "input_cost_per_token": 0.000001,
                "output_cost_per_token": 0.000002,
                "mode": "chat",
            },
        }

        result = get_litellm_models_live()

        self.assertEqual({m["model_id"] for m in result}, {"proxy-only-model"})
        mock_public_catalog.assert_not_called()

    @patch("app.services.model_catalog._fetch_litellm_proxy_catalog", return_value=None)
    def test_proxy_not_configured_returns_empty_list(self, mock_proxy_catalog):
        self.assertEqual(get_litellm_models_live(), [])

    @patch("app.services.model_catalog._fetch_litellm_proxy_catalog")
    def test_fetches_once_within_ttl(self, mock_proxy_catalog):
        mock_proxy_catalog.return_value = {}

        get_litellm_models_live()
        get_litellm_models_live()

        self.assertEqual(mock_proxy_catalog.call_count, 1)


class TestGetMergedModels(unittest.TestCase):
    """get_merged_models combines get_bedrock_models + get_litellm_models_live
    for callers that need the full universe of valid model ids."""

    def setUp(self):
        model_catalog._cache["data"] = None
        model_catalog._cache["fetched_at"] = 0.0
        model_catalog._litellm_cache["data"] = None
        model_catalog._litellm_cache["fetched_at"] = 0.0

    def tearDown(self):
        model_catalog._cache["data"] = None
        model_catalog._cache["fetched_at"] = 0.0
        model_catalog._litellm_cache["data"] = None
        model_catalog._litellm_cache["fetched_at"] = 0.0

    @patch("app.services.model_catalog._fetch_bedrock_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_availability", return_value=None)
    @patch("app.services.model_catalog._fetch_litellm_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_litellm_proxy_catalog")
    def test_live_litellm_catalog_expands_into_many_models(
        self, mock_proxy_catalog, mock_public_catalog, mock_availability, mock_bedrock_catalog
    ):
        mock_proxy_catalog.return_value = {
            "gpt-4o": {
                "input_cost_per_token": 0.0000025,
                "output_cost_per_token": 0.00001,
                "litellm_provider": "openai",
                "mode": "chat",
            },
            "claude-3-opus-20240229": {
                "input_cost_per_token": 0.000015,
                "output_cost_per_token": 0.000075,
                "litellm_provider": "anthropic",
                "mode": "chat",
            },
        }
        fake_static = [
            {"model_id": "us.anthropic.claude-sonnet-4-6", "input_price_per_1k_tokens": 0.003, "provider": "bedrock"},
            {"model_id": "litellm/router-default", "provider": "litellm", "input_price_per_1k_tokens": 0.0},
        ]

        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            result = get_merged_models("us-east-1")

        litellm_ids = {m["model_id"] for m in result if m.get("provider") == "litellm"}
        # The static placeholder is replaced by the live catalog's exact keys.
        self.assertEqual(litellm_ids, {"gpt-4o", "claude-3-opus-20240229"})
        self.assertNotIn("litellm/router-default", litellm_ids)

    @patch("app.services.model_catalog._fetch_bedrock_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_bedrock_availability", return_value=None)
    @patch("app.services.model_catalog._fetch_litellm_catalog", return_value=None)
    @patch("app.services.model_catalog._fetch_litellm_proxy_catalog", return_value=None)
    def test_litellm_unavailable_has_no_placeholder(
        self, mock_proxy_catalog, mock_public_catalog, mock_availability, mock_bedrock_catalog
    ):
        fake_static = [
            {"model_id": "us.anthropic.claude-sonnet-4-6", "input_price_per_1k_tokens": 0.003, "provider": "bedrock"},
        ]
        with patch("app.routers.agents.SUPPORTED_MODELS", fake_static):
            result = get_merged_models("us-east-1")

        # No placeholder fallback — a disabled/unreachable proxy means zero
        # litellm entries, not a fake stand-in model.
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["model_id"], "us.anthropic.claude-sonnet-4-6")


if __name__ == "__main__":
    unittest.main()

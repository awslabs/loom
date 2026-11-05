"""_is_agentcore_url must match only real AgentCore Runtime data-plane hosts.

The AgentCore invoke URL is https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<escaped-arn>/invocations/
(AWS docs, Runtime A2A page, fetched 2026-11-04). The check is on the parsed hostname, not a substring of the URL.
"""
import unittest

from app.services.a2a import _is_agentcore_url


class TestIsAgentcoreUrl(unittest.TestCase):
    def test_real_agentcore_hosts_are_detected(self):
        urls = [
            "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A123%3Aruntime%2Fx/invocations/",
            "https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/abc/invocations/",
            "https://bedrock-agentcore.eu-north-1.amazonaws.com/runtimes/abc/invocations/",
            "https://bedrock-agentcore.ap-southeast-2.amazonaws.com/runtimes/abc/invocations/",
            "https://bedrock-agentcore.us-gov-west-1.amazonaws.com/runtimes/abc/invocations/",
            "http://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/abc/invocations/",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(_is_agentcore_url(url))

    def test_substring_in_path_is_not_agentcore(self):
        self.assertFalse(_is_agentcore_url("https://evil.example.com/bedrock-agentcore"))
        self.assertFalse(_is_agentcore_url("https://evil.example.com/bedrock-agentcore.us-east-1.amazonaws.com/"))

    def test_substring_in_query_is_not_agentcore(self):
        self.assertFalse(_is_agentcore_url("https://evil.example.com/?h=bedrock-agentcore.us-east-1.amazonaws.com"))

    def test_hostname_containing_the_word_is_not_agentcore(self):
        self.assertFalse(_is_agentcore_url("http://my-bedrock-agentcore-proxy.internal"))
        self.assertFalse(_is_agentcore_url("https://bedrock-agentcore.example.com/"))

    def test_lookalike_suffix_and_prefix_hosts_are_not_agentcore(self):
        self.assertFalse(_is_agentcore_url("https://bedrock-agentcore.us-east-1.amazonaws.com.evil.example.com/"))
        self.assertFalse(_is_agentcore_url("https://evil.bedrock-agentcore.us-east-1.amazonaws.com/"))
        self.assertFalse(_is_agentcore_url("https://bedrock-agentcore.us-east-1.amazonaws.com-evil.example.com/"))

    def test_userinfo_trick_is_not_agentcore(self):
        self.assertFalse(_is_agentcore_url("https://bedrock-agentcore.us-east-1.amazonaws.com@evil.example.com/"))

    def test_uppercase_lookalike_is_not_agentcore(self):
        self.assertFalse(_is_agentcore_url("https://BEDROCK-AGENTCORE.US-EAST-1.AMAZONAWS.COM.EVIL.EXAMPLE/"))

    def test_non_http_scheme_is_not_agentcore(self):
        self.assertFalse(_is_agentcore_url("ftp://bedrock-agentcore.us-east-1.amazonaws.com/"))

    def test_unicode_lookalikes_and_stray_whitespace_are_not_agentcore(self):
        self.assertFalse(_is_agentcore_url("https://bedrock-agentcore.us-east-١.amazonaws.com/"))  # Arabic-Indic digit one
        self.assertFalse(_is_agentcore_url("https://bedrocK-agentcore.us-east-1.amazonaws.com/"))  # Kelvin sign
        self.assertFalse(_is_agentcore_url(" https://bedrock-agentcore.us-east-1.amazonaws.com/"))
        self.assertFalse(_is_agentcore_url("https://bedrock-agentcore.us-east-1.amazonaws.com/\n"))

    def test_malformed_or_empty_url_is_not_agentcore(self):
        self.assertFalse(_is_agentcore_url(""))
        self.assertFalse(_is_agentcore_url("http://[bedrock-agentcore"))


if __name__ == "__main__":
    unittest.main()

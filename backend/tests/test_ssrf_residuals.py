"""Residual SSRF paths from the net_guard review (CGNAT, NAT64, URL-classifier substrings).

Follow-on to the v1.7.0 SSRF hardening: the public-only predicate matched an
explicit list that did not include 100.64.0.0/10, and the A2A URL classifiers
were substring tests on the whole URL rather than host checks.
"""
import ipaddress
import unittest

from app.services.a2a import _is_agentcore_url, _is_salesforce_url
from app.services.net_guard import _is_always_disallowed_ip, _is_disallowed_ip


def ip(addr: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    return ipaddress.ip_address(addr)


class TestDisallowedIpResiduals(unittest.TestCase):

    def test_cgnat_blocked_in_public_only_mode(self) -> None:
        for addr in ("100.64.0.1", "100.100.100.100", "100.127.255.254", "::ffff:100.64.0.1"):
            self.assertTrue(_is_disallowed_ip(ip(addr)), addr)

    def test_cgnat_allowed_at_permissive_level(self) -> None:
        # 100.64.0.0/10 is a legitimate VPC secondary CIDR for VPC-internal
        # MCP servers / A2A agents, like RFC 1918.
        self.assertFalse(_is_always_disallowed_ip(ip("100.64.0.1")))

    def test_nat64_blocked_at_every_level(self) -> None:
        for addr in ("64:ff9b::a9fe:a9fe", "64:ff9b::a00:1", "64:ff9b::808:808", "64:ff9b:1::a9fe:a9fe"):
            self.assertTrue(_is_always_disallowed_ip(ip(addr)), addr)
            self.assertTrue(_is_disallowed_ip(ip(addr)), addr)

    def test_other_special_purpose_ranges_blocked_in_public_only_mode(self) -> None:
        for addr in ("192.0.0.1", "198.18.0.1", "192.0.2.1", "240.0.0.1", "2001:db8::1", "fc00::1"):
            self.assertTrue(_is_disallowed_ip(ip(addr)), addr)

    def test_public_addresses_still_allowed(self) -> None:
        for addr in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
            self.assertFalse(_is_disallowed_ip(ip(addr)), addr)
            self.assertFalse(_is_always_disallowed_ip(ip(addr)), addr)


class TestUrlClassifiers(unittest.TestCase):

    def test_salesforce_matches_host_and_path(self) -> None:
        self.assertTrue(_is_salesforce_url("https://api.salesforce.com/einstein/ai-agent/v1"))
        self.assertTrue(_is_salesforce_url("https://API.Salesforce.com/einstein/ai-agent"))

    def test_salesforce_substring_bypasses_rejected(self) -> None:
        for url in (
            "http://127.0.0.1:9011/salesforce.com/einstein/ai-agent",
            "https://evil.example/x?u=salesforce.com/einstein/ai-agent",
            "https://salesforce.com.evil.example/einstein/ai-agent",
            "https://evilsalesforce.com/einstein/ai-agent",
            "https://api.salesforce.com/other/path",
            "not a url",
        ):
            self.assertFalse(_is_salesforce_url(url), url)

    def test_agentcore_matches_host(self) -> None:
        self.assertTrue(_is_agentcore_url("https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/x/invocations"))
        self.assertTrue(_is_agentcore_url("https://gw1.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp"))

    def test_agentcore_substring_bypasses_rejected(self) -> None:
        for url in (
            "http://127.0.0.1/bedrock-agentcore",
            "https://bedrock-agentcore.evil.example/x",
            "https://bedrock-agentcore.amazonaws.com.evil.example/",
            "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/",
        ):
            self.assertFalse(_is_agentcore_url(url), url)


if __name__ == "__main__":
    unittest.main()

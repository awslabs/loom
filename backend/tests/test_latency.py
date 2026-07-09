"""
Unit tests for latency computation helpers.
"""

import unittest
from app.services.latency import compute_cold_start, compute_client_duration


class TestLatencyComputations(unittest.TestCase):
    """Test suite for latency calculation functions."""

    def test_compute_cold_start(self) -> None:
        """Test cold start latency calculation."""
        # Test basic calculation: 500ms difference
        client_time = 1708000000.0
        agent_time = 1708000000.5
        result = compute_cold_start(client_time, agent_time)
        self.assertAlmostEqual(result, 500.0, places=2)

    def test_compute_cold_start_zero(self) -> None:
        """Test cold start with zero difference."""
        client_time = 1708000000.0
        agent_time = 1708000000.0
        result = compute_cold_start(client_time, agent_time)
        self.assertAlmostEqual(result, 0.0, places=2)

    def test_compute_cold_start_negative(self) -> None:
        """Test cold start with negative difference (agent started before client recorded time)."""
        client_time = 1708000001.0
        agent_time = 1708000000.5
        result = compute_cold_start(client_time, agent_time)
        self.assertAlmostEqual(result, -500.0, places=2)

    def test_compute_cold_start_large_value(self) -> None:
        """Test cold start with larger time difference (2 seconds)."""
        client_time = 1708000000.0
        agent_time = 1708000002.0
        result = compute_cold_start(client_time, agent_time)
        self.assertAlmostEqual(result, 2000.0, places=2)

    def test_compute_client_duration(self) -> None:
        """Test client duration calculation."""
        # Test basic calculation: 2333ms duration
        invoke_time = 1708000000.0
        done_time = 1708000002.333
        result = compute_client_duration(invoke_time, done_time)
        self.assertAlmostEqual(result, 2333.0, places=2)

    def test_compute_client_duration_zero(self) -> None:
        """Test client duration with zero difference."""
        invoke_time = 1708000000.0
        done_time = 1708000000.0
        result = compute_client_duration(invoke_time, done_time)
        self.assertAlmostEqual(result, 0.0, places=2)

    def test_compute_client_duration_fractional_seconds(self) -> None:
        """Test client duration with fractional seconds."""
        invoke_time = 1708000000.123
        done_time = 1708000001.456
        result = compute_client_duration(invoke_time, done_time)
        self.assertAlmostEqual(result, 1333.0, places=2)


if __name__ == '__main__':
    unittest.main()

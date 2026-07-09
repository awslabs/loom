"""
Pure computation helpers for latency calculation.

This module provides simple functions to compute timing differences
for agent invocation latency measurements.
"""


def compute_cold_start(client_invoke_time: float, agent_start_time: float) -> float:
    """
    Calculate cold start latency in milliseconds.

    Args:
        client_invoke_time: Unix timestamp (seconds) when client initiated the invoke call
        agent_start_time: Unix timestamp (seconds) when agent started (from CloudWatch logs)

    Returns:
        Latency in milliseconds (delta between agent start and client invoke)
    """
    return (agent_start_time - client_invoke_time) * 1000.0


def compute_client_duration(client_invoke_time: float, client_done_time: float) -> float:
    """
    Calculate total client-side duration in milliseconds.

    Args:
        client_invoke_time: Unix timestamp (seconds) when client initiated the invoke call
        client_done_time: Unix timestamp (seconds) when client completed receiving response

    Returns:
        Duration in milliseconds (delta between completion and invoke)
    """
    return (client_done_time - client_invoke_time) * 1000.0

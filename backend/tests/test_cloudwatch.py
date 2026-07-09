"""
Unit tests for CloudWatch Logs service wrapper.
"""

import json
import unittest
from unittest.mock import MagicMock, patch
from app.services.cloudwatch import (
    list_log_streams,
    get_log_events,
    parse_agent_start_time,
    parse_memory_telemetry,
    parse_usage_telemetry,
)


class TestListLogStreams(unittest.TestCase):
    """Test suite for list_log_streams function."""

    @patch('boto3.client')
    def test_list_log_streams_success(self, mock_boto_client: MagicMock) -> None:
        """Test successful log stream listing with ordering."""
        mock_logs_client = MagicMock()
        mock_boto_client.return_value = mock_logs_client

        mock_logs_client.describe_log_streams.return_value = {
            'logStreams': [
                {
                    'logStreamName': 'stream-1',
                    'lastEventTimestamp': 1708000002000
                },
                {
                    'logStreamName': 'stream-2',
                    'lastEventTimestamp': 1708000001000
                }
            ]
        }

        result = list_log_streams('/aws/bedrock-agentcore/test', 'us-east-1')

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'stream-1')
        self.assertEqual(result[0]['last_event_time'], 1708000002000)
        self.assertEqual(result[1]['name'], 'stream-2')
        self.assertEqual(result[1]['last_event_time'], 1708000001000)

    @patch('boto3.client')
    def test_list_log_streams_filters_validation_streams(self, mock_boto_client: MagicMock) -> None:
        """Test that validation streams are filtered out."""
        mock_logs_client = MagicMock()
        mock_boto_client.return_value = mock_logs_client

        mock_logs_client.describe_log_streams.return_value = {
            'logStreams': [
                {
                    'logStreamName': 'valid-stream',
                    'lastEventTimestamp': 1708000001000
                },
                {
                    'logStreamName': 'log_stream_created_by_aws_to_validate_log_delivery_subscriptions',
                    'lastEventTimestamp': 1708000002000
                }
            ]
        }

        result = list_log_streams('/aws/bedrock-agentcore/test', 'us-east-1')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'valid-stream')

    @patch('boto3.client')
    def test_list_log_streams_fallback_on_error(self, mock_boto_client: MagicMock) -> None:
        """Test fallback behavior when ordering fails."""
        mock_logs_client = MagicMock()
        mock_boto_client.return_value = mock_logs_client

        # First call with ordering fails, second call without ordering succeeds
        mock_logs_client.describe_log_streams.side_effect = [
            Exception("Ordering not supported"),
            {
                'logStreams': [
                    {'logStreamName': 'stream-1', 'lastEventTimestamp': 1708000001000}
                ]
            }
        ]

        result = list_log_streams('/aws/bedrock-agentcore/test', 'us-east-1')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'stream-1')

    @patch('boto3.client')
    def test_list_log_streams_handles_missing_timestamp(self, mock_boto_client: MagicMock) -> None:
        """Test handling of streams without lastEventTimestamp."""
        mock_logs_client = MagicMock()
        mock_boto_client.return_value = mock_logs_client

        mock_logs_client.describe_log_streams.return_value = {
            'logStreams': [
                {'logStreamName': 'stream-without-timestamp'}
            ]
        }

        result = list_log_streams('/aws/bedrock-agentcore/test', 'us-east-1')

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'stream-without-timestamp')
        self.assertEqual(result[0]['last_event_time'], 0)


class TestGetLogEvents(unittest.TestCase):
    """Test suite for get_log_events function."""

    @patch('app.services.cloudwatch.list_log_streams')
    @patch('boto3.client')
    def test_get_log_events_success(
        self,
        mock_boto_client: MagicMock,
        mock_list_streams: MagicMock
    ) -> None:
        """Test successful log event retrieval."""
        mock_logs_client = MagicMock()
        mock_boto_client.return_value = mock_logs_client

        mock_list_streams.return_value = [
            {'name': 'test-stream', 'last_event_time': 1708000001000}
        ]

        session_id = 'test-session-123'
        mock_logs_client.filter_log_events.return_value = {
            'events': [
                {
                    'timestamp': 1708000001000,
                    'message': f'Log message with {session_id}'
                }
            ]
        }

        result = get_log_events(
            '/aws/bedrock-agentcore/test',
            session_id,
            'us-east-1',
            max_retries=1
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['timestamp'], 1708000001000)
        self.assertIn(session_id, result[0]['message'])

    @patch('app.services.cloudwatch.list_log_streams')
    @patch('boto3.client')
    def test_get_log_events_filters_by_session_id(
        self,
        mock_boto_client: MagicMock,
        mock_list_streams: MagicMock
    ) -> None:
        """Test that only matching session ID events are returned."""
        mock_logs_client = MagicMock()
        mock_boto_client.return_value = mock_logs_client

        mock_list_streams.return_value = [
            {'name': 'test-stream', 'last_event_time': 1708000001000}
        ]

        target_session_id = 'target-session'
        # CloudWatch filterPattern filters server-side; mock returns only matching events
        mock_logs_client.filter_log_events.return_value = {
            'events': [
                {
                    'timestamp': 1708000001000,
                    'message': f'Log for {target_session_id}'
                },
            ]
        }

        result = get_log_events(
            '/aws/bedrock-agentcore/test',
            target_session_id,
            'us-east-1',
            max_retries=1
        )

        self.assertEqual(len(result), 1)
        self.assertIn(target_session_id, result[0]['message'])

    @patch('app.services.cloudwatch.list_log_streams')
    @patch('app.services.cloudwatch.time.sleep')
    @patch('boto3.client')
    def test_get_log_events_retries(
        self,
        mock_boto_client: MagicMock,
        mock_sleep: MagicMock,
        mock_list_streams: MagicMock
    ) -> None:
        """Test retry behavior when logs are not immediately available."""
        mock_logs_client = MagicMock()
        mock_boto_client.return_value = mock_logs_client

        mock_list_streams.return_value = [
            {'name': 'test-stream', 'last_event_time': 1708000001000}
        ]

        session_id = 'test-session'

        # First call returns no events, second call returns matching event
        mock_logs_client.filter_log_events.side_effect = [
            {'events': []},
            {'events': [{'timestamp': 1708000001000, 'message': f'Found {session_id}'}]}
        ]

        result = get_log_events(
            '/aws/bedrock-agentcore/test',
            session_id,
            'us-east-1',
            max_retries=3,
            retry_interval=0.1
        )

        self.assertEqual(len(result), 1)
        self.assertIn(session_id, result[0]['message'])
        mock_sleep.assert_called()

    @patch('app.services.cloudwatch.list_log_streams')
    @patch('boto3.client')
    def test_get_log_events_json_wrapped_session_id(
        self,
        mock_boto_client: MagicMock,
        mock_list_streams: MagicMock
    ) -> None:
        """Test filtering events with JSON-wrapped session IDs."""
        mock_logs_client = MagicMock()
        mock_boto_client.return_value = mock_logs_client

        mock_list_streams.return_value = [
            {'name': 'test-stream', 'last_event_time': 1708000001000}
        ]

        session_id = 'json-session-123'
        json_message = json.dumps({
            'sessionId': session_id,
            'message': 'Agent invoked'
        })

        mock_logs_client.filter_log_events.return_value = {
            'events': [
                {'timestamp': 1708000001000, 'message': json_message}
            ]
        }

        result = get_log_events(
            '/aws/bedrock-agentcore/test',
            session_id,
            'us-east-1',
            max_retries=1
        )

        self.assertEqual(len(result), 1)
        self.assertIn(session_id, result[0]['message'])


class TestParseAgentStartTime(unittest.TestCase):
    """Test suite for parse_agent_start_time function."""

    def test_parse_agent_start_time_basic_format(self) -> None:
        """Test parsing agent start time from basic log message format."""
        log_events = [
            {
                'timestamp': 1708000001000,
                'message': 'Agent invoked - Start time: 2026-02-11T19:44:38.558763, Request ID: abc-123'
            }
        ]

        result = parse_agent_start_time(log_events)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)

    def test_parse_agent_start_time_json_wrapped(self) -> None:
        """Test parsing agent start time from JSON-wrapped log message."""
        json_message = json.dumps({
            'sessionId': 'test-session',
            'message': 'Agent invoked - Start time: 2026-02-11T19:44:38.558763, Request ID: xyz-456'
        })

        log_events = [
            {'timestamp': 1708000001000, 'message': json_message}
        ]

        result = parse_agent_start_time(log_events)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)

    def test_parse_agent_start_time_not_found_falls_back_to_event_timestamp(self) -> None:
        """Test that earliest event timestamp is used as fallback when no Start time pattern found."""
        log_events = [
            {'timestamp': 1708000001000, 'message': 'Some other log message'},
            {'timestamp': 1708000002000, 'message': 'Another unrelated log'}
        ]

        result = parse_agent_start_time(log_events)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 1708000001.0, places=1)

    def test_parse_agent_start_time_no_events(self) -> None:
        """Test that None is returned when no log events exist."""
        result = parse_agent_start_time([])
        self.assertIsNone(result)

    def test_parse_agent_start_time_missing_start_time_field(self) -> None:
        """Test handling of agent invoked message without Start time field falls back to event timestamp."""
        log_events = [
            {'timestamp': 1708000001000, 'message': 'Agent invoked - Request ID: abc-123'}
        ]

        result = parse_agent_start_time(log_events)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 1708000001.0, places=1)

    def test_parse_agent_start_time_multiple_events(self) -> None:
        """Test parsing when multiple events exist (returns first match)."""
        log_events = [
            {'timestamp': 1708000001000, 'message': 'Unrelated log'},
            {'timestamp': 1708000002000, 'message': 'Agent invoked - Start time: 2026-02-11T19:44:38.558763'},
            {'timestamp': 1708000003000, 'message': 'Agent invoked - Start time: 2026-02-11T19:44:39.000000'}
        ]

        result = parse_agent_start_time(log_events)

        self.assertIsNotNone(result)
        # Should match the first occurrence
        self.assertIsInstance(result, float)

    def test_parse_agent_start_time_with_z_timezone(self) -> None:
        """Test parsing timestamp with Z timezone indicator."""
        log_events = [
            {
                'timestamp': 1708000001000,
                'message': 'Agent invoked - Start time: 2026-02-11T19:44:38.558763Z'
            }
        ]

        result = parse_agent_start_time(log_events)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)

    def test_parse_agent_start_time_invalid_timestamp(self) -> None:
        """Test handling of invalid timestamp format falls back to event timestamp."""
        log_events = [
            {
                'timestamp': 1708000001000,
                'message': 'Agent invoked - Start time: invalid-timestamp-format'
            }
        ]

        result = parse_agent_start_time(log_events)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 1708000001.0, places=1)


class TestParseMemoryTelemetry(unittest.TestCase):
    """Test suite for parse_memory_telemetry function."""

    def test_parse_memory_telemetry_basic(self) -> None:
        """Test parsing memory telemetry from a plain log message."""
        events = [
            {
                "timestamp": 1708000001000,
                "message": "2026-02-11 19:44:38 INFO src.integrations.memory LOOM_MEMORY_TELEMETRY: retrievals=5, events_sent=3",
            }
        ]
        result = parse_memory_telemetry(events)
        self.assertEqual(result["retrievals"], 5)
        self.assertEqual(result["events_sent"], 3)

    def test_parse_memory_telemetry_json_wrapped(self) -> None:
        """Test parsing memory telemetry from a JSON-wrapped log message."""
        events = [
            {
                "timestamp": 1708000001000,
                "message": json.dumps({
                    "message": "LOOM_MEMORY_TELEMETRY: retrievals=10, events_sent=7",
                }),
            }
        ]
        result = parse_memory_telemetry(events)
        self.assertEqual(result["retrievals"], 10)
        self.assertEqual(result["events_sent"], 7)

    def test_parse_memory_telemetry_not_found(self) -> None:
        """Test that defaults are returned when no telemetry line exists."""
        events = [
            {"timestamp": 1708000001000, "message": "Some other log message"},
        ]
        result = parse_memory_telemetry(events)
        self.assertEqual(result["retrievals"], 0)
        self.assertEqual(result["events_sent"], 0)

    def test_parse_memory_telemetry_empty_events(self) -> None:
        """Test with empty event list."""
        result = parse_memory_telemetry([])
        self.assertEqual(result["retrievals"], 0)
        self.assertEqual(result["events_sent"], 0)

    def test_parse_memory_telemetry_zero_values(self) -> None:
        """Test parsing when counters are zero."""
        events = [
            {
                "timestamp": 1708000001000,
                "message": "LOOM_MEMORY_TELEMETRY: retrievals=0, events_sent=0",
            }
        ]
        result = parse_memory_telemetry(events)
        self.assertEqual(result["retrievals"], 0)
        self.assertEqual(result["events_sent"], 0)

    def test_parse_memory_telemetry_malformed(self) -> None:
        """Test handling of malformed telemetry line."""
        events = [
            {
                "timestamp": 1708000001000,
                "message": "LOOM_MEMORY_TELEMETRY: garbled data",
            }
        ]
        result = parse_memory_telemetry(events)
        self.assertEqual(result["retrievals"], 0)
        self.assertEqual(result["events_sent"], 0)


class TestParseUsageTelemetry(unittest.TestCase):
    """Test suite for parse_usage_telemetry function."""

    def test_parse_usage_telemetry_basic(self) -> None:
        """Test parsing vCPU and memory hours from USAGE_LOGS events."""
        events = [
            {
                "timestamp": 1708000001000,
                "message": json.dumps({
                    "session.id": "sess-1",
                    "agent.runtime.vcpu.hours.used": 0.000556,
                    "agent.runtime.memory.gb_hours.used": 0.002222,
                    "elapsed_time_seconds": 10,
                }),
            },
            {
                "timestamp": 1708000002000,
                "message": json.dumps({
                    "session.id": "sess-1",
                    "agent.runtime.vcpu.hours.used": 0.000556,
                    "agent.runtime.memory.gb_hours.used": 0.002222,
                    "elapsed_time_seconds": 20,
                }),
            },
        ]
        result = parse_usage_telemetry(events)
        self.assertAlmostEqual(result["vcpu_hours"], 0.001112, places=6)
        self.assertAlmostEqual(result["memory_gb_hours"], 0.004444, places=6)
        self.assertAlmostEqual(result["elapsed_seconds"], 20.0)

    def test_parse_usage_telemetry_empty(self) -> None:
        """Test with empty event list."""
        result = parse_usage_telemetry([])
        self.assertEqual(result["vcpu_hours"], 0.0)
        self.assertEqual(result["memory_gb_hours"], 0.0)
        self.assertEqual(result["elapsed_seconds"], 0.0)

    def test_parse_usage_telemetry_non_json(self) -> None:
        """Test that non-JSON messages are skipped."""
        events = [
            {"timestamp": 1708000001000, "message": "plain text log line"},
        ]
        result = parse_usage_telemetry(events)
        self.assertEqual(result["vcpu_hours"], 0.0)

    def test_parse_usage_telemetry_missing_fields(self) -> None:
        """Test events with partial fields."""
        events = [
            {
                "timestamp": 1708000001000,
                "message": json.dumps({"agent.runtime.vcpu.hours.used": 0.001}),
            },
        ]
        result = parse_usage_telemetry(events)
        self.assertAlmostEqual(result["vcpu_hours"], 0.001)
        self.assertEqual(result["memory_gb_hours"], 0.0)


if __name__ == '__main__':
    unittest.main()

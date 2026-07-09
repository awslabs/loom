"""Tests for OTEL trace retrieval endpoints and parsing."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.agent import Agent


def _otel_event(trace_id: str, span_id: str, observed_nano: int,
                body: dict | str | None = None, session_id: str = "sess-1",
                scope: str = "strands.telemetry.tracer",
                severity: int = 9) -> dict:
    """Build a mock CloudWatch log event containing an OTEL log record."""
    record = {
        "traceId": trace_id,
        "spanId": span_id,
        "observedTimeUnixNano": observed_nano,
        "timeUnixNano": observed_nano,
        "severityNumber": severity,
        "severityText": "",
        "scope": {"name": scope},
        "body": body if body is not None else {},
        "attributes": {"event.name": scope, "session.id": session_id},
        "resource": {"attributes": {"service.name": "test-agent"}},
        "flags": 1,
    }
    return {"timestamp": observed_nano // 1_000_000, "message": json.dumps(record)}


class TestTracesRouter(unittest.TestCase):
    """Test cases for /api/agents/{id}/sessions/{sid}/traces and /api/agents/{id}/traces/{tid}."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent",
            runtime_id="test-agent",
            name="Test Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            log_group="/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT",
        )
        self.agent.set_available_qualifiers(["DEFAULT"])
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @patch("app.routers.traces.fetch_otel_events")
    def test_get_session_traces_success(self, mock_fetch):
        """Test successful trace retrieval for a session."""
        mock_fetch.return_value = [
            _otel_event("trace-1", "span-a", 1_000_000_000_000_000_000,
                        body={"input": {"messages": []}}, session_id="sess-1"),
            _otel_event("trace-1", "span-a", 1_000_000_500_000_000_000,
                        body={"output": {"messages": []}}, session_id="sess-1"),
            _otel_event("trace-1", "span-b", 1_000_000_200_000_000_000,
                        session_id="sess-1"),
        ]

        resp = self.client.get(
            f"/api/agents/{self.agent.id}/sessions/sess-1/traces"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["traces"]), 1)
        trace = data["traces"][0]
        self.assertEqual(trace["trace_id"], "trace-1")
        self.assertEqual(trace["span_count"], 2)
        self.assertEqual(trace["event_count"], 3)
        self.assertEqual(trace["session_id"], "sess-1")
        self.assertGreater(trace["duration_ms"], 0)

    @patch("app.routers.traces.fetch_otel_events")
    def test_get_session_traces_empty(self, mock_fetch):
        """Test empty trace list when no OTEL events found."""
        mock_fetch.return_value = []

        resp = self.client.get(
            f"/api/agents/{self.agent.id}/sessions/sess-1/traces"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["traces"], [])

    def test_get_session_traces_agent_not_found(self):
        """Test 404 when agent doesn't exist."""
        resp = self.client.get("/api/agents/999/sessions/sess-1/traces")
        self.assertEqual(resp.status_code, 404)

    @patch("app.routers.traces.fetch_otel_events")
    def test_get_trace_detail_success(self, mock_fetch):
        """Test successful trace detail retrieval with spans and events."""
        mock_fetch.return_value = [
            _otel_event("trace-1", "span-a", 1_000_000_000_000_000_000,
                        body={"input": {"messages": [{"role": "user", "content": "hi"}]}},
                        session_id="sess-1"),
            _otel_event("trace-1", "span-a", 1_000_000_500_000_000_000,
                        body={"output": {"messages": [{"role": "assistant", "content": "hello"}]}},
                        session_id="sess-1"),
            _otel_event("trace-1", "span-b", 1_000_000_200_000_000_000,
                        body={"input": {"messages": [{"role": "tool", "content": "data"}]}},
                        session_id="sess-1", scope="strands.tool"),
            # String body (common for log messages)
            _otel_event("trace-1", "span-a", 1_000_000_100_000_000_000,
                        body="Agent initialized successfully",
                        session_id="sess-1"),
        ]

        resp = self.client.get(
            f"/api/agents/{self.agent.id}/traces/trace-1"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["trace_id"], "trace-1")
        self.assertEqual(data["span_count"], 2)
        self.assertEqual(data["event_count"], 4)
        self.assertEqual(data["session_id"], "sess-1")

        # Verify spans are sorted by start time
        spans = data["spans"]
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0]["span_id"], "span-a")
        self.assertEqual(spans[0]["event_count"], 3)
        self.assertEqual(spans[1]["span_id"], "span-b")
        self.assertEqual(spans[1]["event_count"], 1)

        # Verify events within span-a are ordered by observedTimeUnixNano
        events = spans[0]["events"]
        self.assertEqual(len(events), 3)
        self.assertIn("input", events[0]["body"])
        # Second event is a string body
        self.assertEqual(events[1]["body"], "Agent initialized successfully")
        self.assertIn("output", events[2]["body"])

        # Verify each event carries its own scope
        self.assertEqual(events[0]["scope"], "strands.telemetry.tracer")
        self.assertEqual(spans[1]["events"][0]["scope"], "strands.tool")

    @patch("app.routers.traces.fetch_otel_events")
    def test_get_trace_detail_not_found(self, mock_fetch):
        """Test 404 when trace doesn't exist."""
        mock_fetch.return_value = []

        resp = self.client.get(
            f"/api/agents/{self.agent.id}/traces/nonexistent-trace"
        )
        self.assertEqual(resp.status_code, 404)

    def test_get_trace_detail_agent_not_found(self):
        """Test 404 when agent doesn't exist."""
        resp = self.client.get("/api/agents/999/traces/trace-1")
        self.assertEqual(resp.status_code, 404)

    @patch("app.routers.traces.fetch_otel_events")
    def test_get_session_traces_multiple_traces(self, mock_fetch):
        """Test that multiple traces are returned and sorted."""
        mock_fetch.return_value = [
            _otel_event("trace-2", "span-x", 2_000_000_000_000_000_000, session_id="sess-1"),
            _otel_event("trace-1", "span-a", 1_000_000_000_000_000_000, session_id="sess-1"),
        ]

        resp = self.client.get(
            f"/api/agents/{self.agent.id}/sessions/sess-1/traces"
        )
        self.assertEqual(resp.status_code, 200)
        traces = resp.json()["traces"]
        self.assertEqual(len(traces), 2)
        # Sorted by start time descending
        self.assertEqual(traces[0]["trace_id"], "trace-2")
        self.assertEqual(traces[1]["trace_id"], "trace-1")


class TestOtelParsing(unittest.TestCase):
    """Test cases for OTEL log parsing functions."""

    def test_parse_otel_traces_groups_by_trace_id(self):
        """Test that events are correctly grouped by traceId."""
        from app.services.otel import parse_otel_traces

        events = [
            _otel_event("t1", "s1", 100_000_000_000),
            _otel_event("t1", "s2", 200_000_000_000),
            _otel_event("t2", "s3", 300_000_000_000),
        ]
        traces = parse_otel_traces(events)
        self.assertEqual(len(traces), 2)
        t1 = next(t for t in traces if t["trace_id"] == "t1")
        self.assertEqual(t1["span_count"], 2)
        self.assertEqual(t1["event_count"], 2)

    def test_parse_otel_trace_detail_orders_events(self):
        """Test that events within a span are ordered by observedTimeUnixNano."""
        from app.services.otel import parse_otel_trace_detail

        events = [
            _otel_event("t1", "s1", 300_000_000_000, body={"third": True}),
            _otel_event("t1", "s1", 100_000_000_000, body={"first": True}),
            _otel_event("t1", "s1", 200_000_000_000, body={"second": True}),
        ]
        detail = parse_otel_trace_detail(events, "t1")
        self.assertIsNotNone(detail)
        self.assertEqual(len(detail["spans"]), 1)
        bodies = [e["body"] for e in detail["spans"][0]["events"]]
        self.assertIn("first", bodies[0])
        self.assertIn("second", bodies[1])
        self.assertIn("third", bodies[2])

    def test_parse_otel_trace_detail_splits_input_output(self):
        """Test that a body with both input and output is split into two events."""
        from app.services.otel import parse_otel_trace_detail

        events = [
            _otel_event("t1", "s1", 100_000_000_000,
                        body={"output": {"msg": "out"}, "input": {"msg": "in"}}),
        ]
        detail = parse_otel_trace_detail(events, "t1")
        span_events = detail["spans"][0]["events"]
        self.assertEqual(len(span_events), 2)
        self.assertIn("input", span_events[0]["body"])
        self.assertNotIn("output", span_events[0]["body"])
        self.assertIn("output", span_events[1]["body"])
        self.assertNotIn("input", span_events[1]["body"])

    def test_parse_otel_trace_detail_not_found(self):
        """Test that None is returned for non-matching trace_id."""
        from app.services.otel import parse_otel_trace_detail

        events = [_otel_event("t1", "s1", 100_000_000_000)]
        detail = parse_otel_trace_detail(events, "t-nonexistent")
        self.assertIsNone(detail)

    def test_parse_empty_events(self):
        """Test parsing empty event list."""
        from app.services.otel import parse_otel_traces, parse_otel_trace_detail

        self.assertEqual(parse_otel_traces([]), [])
        self.assertIsNone(parse_otel_trace_detail([], "t1"))


if __name__ == "__main__":
    unittest.main()

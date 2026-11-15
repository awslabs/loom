"""Tests for the usage-limit aggregation job — specifically that window
boundaries are respected, and that the cache actually gets populated by a
real refresh cycle, not just by a pure function call."""
import json
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.agent import Agent
from app.models.session import InvocationSession
from app.models.invocation import Invocation
from app.models.usage_limit import UsageLimit
from app.services.usage_limits import _current_usage, _window_start
import app.services.usage_limit_aggregator as agg_module
from app.services.usage_limit_aggregator import _refresh_once


class TestWindowBoundary(unittest.TestCase):
    """_current_usage must exclude invocations from before the window
    started and include everything at or after it — this is the exact
    behavior a daily/weekly/monthly reset, or a rolling window, depends on.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = TestingSessionLocal()

        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent",
            runtime_id="test-agent", name="Test Agent", status="READY",
            region="us-east-1", account_id="123456789012",
            log_group="/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT",
        )
        self.db.add(self.agent)
        self.db.commit()

        self.session = InvocationSession(
            agent_id=self.agent.id, session_id="s1", qualifier="DEFAULT",
            status="pending", created_at=datetime.utcnow(),
            user_id="ivan", groups=json.dumps([]),
        )
        self.db.add(self.session)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def _invocation_at(self, invocation_id, when, tokens=50):
        inv = Invocation(
            session_id="s1", invocation_id=invocation_id, status="complete",
            prompt_text="test", model_id="anthropic.claude-sonnet-4-6",
            input_tokens=tokens, output_tokens=0, created_at=when,
        )
        self.db.add(inv)
        self.db.commit()
        return inv

    def test_invocation_before_window_start_excluded(self):
        limit = UsageLimit(
            name="Ivan Cap", scope=json.dumps({"type": "user", "username": "ivan"}),
            target=json.dumps({"type": "all"}), measure="tokens", threshold=1000,
            window="daily", enforcement="block",
        )
        self.db.add(limit)
        self.db.commit()

        now = datetime.utcnow()
        window_start = _window_start("daily", now)

        # One invocation just before the boundary, one just after.
        self._invocation_at("before", window_start - timedelta(seconds=1), tokens=999)
        self._invocation_at("after", window_start + timedelta(seconds=1), tokens=50)

        usage = _current_usage(self.db, limit, window_start)
        # Only the post-boundary invocation should count — if the pre-boundary
        # one leaked in, usage would be 1049, not 50.
        self.assertEqual(usage, 50)

    def test_rolling_window_excludes_anything_older_than_24h(self):
        limit = UsageLimit(
            name="Ivan Rolling", scope=json.dumps({"type": "user", "username": "ivan"}),
            target=json.dumps({"type": "all"}), measure="tokens", threshold=1000,
            window="rolling", enforcement="block",
        )
        self.db.add(limit)
        self.db.commit()

        now = datetime.utcnow()
        window_start = _window_start("rolling", now)  # now - 24h

        self._invocation_at("too_old", now - timedelta(hours=25), tokens=999)
        self._invocation_at("within_window", now - timedelta(hours=1), tokens=50)

        usage = _current_usage(self.db, limit, window_start)
        self.assertEqual(usage, 50)


class TestAggregatorRefreshRespectsWindow(unittest.TestCase):
    """End-to-end: the actual background job (_refresh_once), not just the
    pure function, must produce a cached value consistent with the window
    boundary — proving the full pipeline, not just one function in isolation.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = TestingSessionLocal()
        # The aggregator opens its own session internally — point it at
        # this same in-memory engine so it sees the fixtures we set up.
        agg_module.SessionLocal = TestingSessionLocal

        self.agent = Agent(
            arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent",
            runtime_id="test-agent", name="Test Agent", status="READY",
            region="us-east-1", account_id="123456789012",
            log_group="/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT",
        )
        self.db.add(self.agent)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_refresh_once_excludes_pre_window_usage(self):
        limit = UsageLimit(
            name="Judy Cap", scope=json.dumps({"type": "user", "username": "judy"}),
            target=json.dumps({"type": "all"}), measure="tokens", threshold=1000,
            window="daily", enforcement="warn",
        )
        self.db.add(limit)
        self.db.commit()

        session = InvocationSession(
            agent_id=self.agent.id, session_id="s2", qualifier="DEFAULT",
            status="pending", created_at=datetime.utcnow(),
            user_id="judy", groups=json.dumps([]),
        )
        self.db.add(session)
        self.db.commit()

        now = datetime.utcnow()
        window_start = _window_start("daily", now)

        yesterday_inv = Invocation(
            session_id="s2", invocation_id="yesterday", status="complete",
            prompt_text="t", model_id="anthropic.claude-sonnet-4-6",
            input_tokens=999, output_tokens=0,
            created_at=window_start - timedelta(hours=1),
        )
        today_inv = Invocation(
            session_id="s2", invocation_id="today", status="complete",
            prompt_text="t", model_id="anthropic.claude-sonnet-4-6",
            input_tokens=30, output_tokens=0,
            created_at=window_start + timedelta(hours=1),
        )
        self.db.add(yesterday_inv)
        self.db.add(today_inv)
        self.db.commit()

        refreshed_count = _refresh_once()
        self.db.refresh(limit)

        self.assertEqual(refreshed_count, 1)
        # Only today's 30 tokens should be in the cache — yesterday's 999
        # must not leak across the window boundary into the cached value.
        self.assertEqual(limit.cached_usage, 30)
        self.assertIsNotNone(limit.cached_usage_updated_at)


if __name__ == "__main__":
    unittest.main()


"""Tests for usage limit evaluation (matching, aggregation, precedence)."""
import json
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.agent import Agent
from app.models.session import InvocationSession
from app.models.invocation import Invocation
from app.models.usage_limit import UsageLimit
from app.services.usage_limits import check_usage_limits
from app.services.model_catalog import get_model_family


class TestCheckUsageLimits(unittest.TestCase):
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
            runtime_id="test-agent",
            name="Test Agent",
            status="READY",
            region="us-east-1",
            account_id="123456789012",
            log_group="/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT",
        )
        self.db.add(self.agent)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def _make_session(self, session_id, user_id, groups=None):
        session = InvocationSession(
            agent_id=self.agent.id,
            session_id=session_id,
            qualifier="DEFAULT",
            status="pending",
            created_at=datetime.now(timezone.utc),
            user_id=user_id,
            groups=json.dumps(groups or []),
        )
        self.db.add(session)
        self.db.commit()
        return session

    def _make_invocation(self, session_id, invocation_id, model_id,
                          input_tokens=0, output_tokens=0, estimated_cost=0.0):
        inv = Invocation(
            session_id=session_id,
            invocation_id=invocation_id,
            status="complete",
            prompt_text="test",
            model_id=model_id,
            model_family=get_model_family(model_id) if model_id else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimated_cost,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(inv)
        self.db.commit()
        return inv

    def test_no_matching_limit_returns_no_enforcement(self):
        decision = check_usage_limits(self.db, "alice", [], "anthropic.claude-sonnet-4-6")
        self.assertIsNone(decision.enforcement)

    def test_exceeded_block_limit_triggers_block(self):
        limit = UsageLimit(
            name="Alice Cap",
            scope=json.dumps({"type": "user", "username": "alice"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=100,
            window="daily",
            enforcement="block",
        )
        self.db.add(limit)
        self.db.commit()
        self._make_session("s1", "alice")
        self._make_invocation("s1", "i1", "anthropic.claude-sonnet-4-6", input_tokens=60, output_tokens=60)

        decision = check_usage_limits(self.db, "alice", [], "anthropic.claude-sonnet-4-6")
        self.assertEqual(decision.enforcement, "block")
        self.assertEqual(decision.current_usage, 120)

    def test_usage_under_threshold_does_not_trigger(self):
        limit = UsageLimit(
            name="Alice Cap",
            scope=json.dumps({"type": "user", "username": "alice"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=1000,
            window="daily",
            enforcement="block",
        )
        self.db.add(limit)
        self.db.commit()
        self._make_session("s1", "alice")
        self._make_invocation("s1", "i1", "anthropic.claude-sonnet-4-6", input_tokens=10, output_tokens=10)

        decision = check_usage_limits(self.db, "alice", [], "anthropic.claude-sonnet-4-6")
        self.assertIsNone(decision.enforcement)

    def test_different_user_not_affected_by_others_usage(self):
        limit = UsageLimit(
            name="Alice Cap",
            scope=json.dumps({"type": "user", "username": "alice"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=10,
            window="daily",
            enforcement="block",
        )
        self.db.add(limit)
        self.db.commit()
        self._make_session("s1", "alice")
        self._make_invocation("s1", "i1", "anthropic.claude-sonnet-4-6", input_tokens=100, output_tokens=100)

        decision = check_usage_limits(self.db, "bob", [], "anthropic.claude-sonnet-4-6")
        self.assertIsNone(decision.enforcement)

    def test_group_scope_matches_via_snapshotted_groups(self):
        limit = UsageLimit(
            name="Marketing Cap",
            scope=json.dumps({"type": "group", "group": "marketing"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=50,
            window="daily",
            enforcement="warn",
        )
        self.db.add(limit)
        self.db.commit()
        self._make_session("s1", "carol", groups=["marketing"])
        self._make_invocation("s1", "i1", "anthropic.claude-sonnet-4-6", input_tokens=40, output_tokens=40)

        decision = check_usage_limits(self.db, "carol", ["marketing"], "anthropic.claude-sonnet-4-6")
        self.assertEqual(decision.enforcement, "warn")
        self.assertEqual(len(decision.warnings), 1)

    def test_model_family_target_matches_across_bedrock_and_litellm_ids(self):
        limit = UsageLimit(
            name="Anthropic Family Cap",
            scope=json.dumps({"type": "user", "username": "dave"}),
            target=json.dumps({"type": "family", "family": "anthropic"}),
            measure="tokens",
            threshold=10,
            window="daily",
            enforcement="block",
        )
        self.db.add(limit)
        self.db.commit()
        self._make_session("s1", "dave")
        self._make_invocation("s1", "i1", "anthropic.claude-sonnet-4-6", input_tokens=20, output_tokens=20)

        decision = check_usage_limits(self.db, "dave", [], "claude-3-opus")
        self.assertEqual(decision.enforcement, "block")

    def test_block_wins_over_warn_when_both_exceeded(self):
        warn_limit = UsageLimit(
            name="Erin Warn",
            scope=json.dumps({"type": "user", "username": "erin"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=10,
            window="daily",
            enforcement="warn",
        )
        block_limit = UsageLimit(
            name="Erin Block",
            scope=json.dumps({"type": "user", "username": "erin"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=10,
            window="daily",
            enforcement="block",
        )
        self.db.add(warn_limit)
        self.db.add(block_limit)
        self.db.commit()
        self._make_session("s1", "erin")
        self._make_invocation("s1", "i1", "anthropic.claude-sonnet-4-6", input_tokens=50, output_tokens=50)

        decision = check_usage_limits(self.db, "erin", [], "anthropic.claude-sonnet-4-6")
        self.assertEqual(decision.enforcement, "block")
        self.assertEqual(len(decision.warnings), 1)

    def test_budget_measure_sums_cost_components(self):
        limit = UsageLimit(
            name="Frank Budget",
            scope=json.dumps({"type": "user", "username": "frank"}),
            target=json.dumps({"type": "all"}),
            measure="budget",
            threshold=1.0,
            window="daily",
            enforcement="block",
        )
        self.db.add(limit)
        self.db.commit()
        self._make_session("s1", "frank")
        self._make_invocation("s1", "i1", "anthropic.claude-sonnet-4-6", estimated_cost=0.6)
        self._make_invocation("s1", "i2", "anthropic.claude-sonnet-4-6", estimated_cost=0.6)

        decision = check_usage_limits(self.db, "frank", [], "anthropic.claude-sonnet-4-6")
        self.assertEqual(decision.enforcement, "block")
        self.assertEqual(decision.current_usage, 1.2)

    def test_group_scope_escapes_like_wildcards(self):
        # Cognito group names can contain underscores, e.g. g-users-a_b.
        # Ensure that SQL LIKE does not treat '_' as a wildcard matching g-users-aXb.
        limit = UsageLimit(
            name="Underscore Group Cap",
            scope=json.dumps({"type": "group", "group": "g-users-a_b"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=50,
            window="daily",
            enforcement="block",
        )
        self.db.add(limit)
        self.db.commit()

        # Session with group containing 'X' instead of '_'
        self._make_session("s_other", "other_user", groups=["g-users-aXb"])
        self._make_invocation("s_other", "i_other", "anthropic.claude-sonnet-4-6", input_tokens=100, output_tokens=100)

        # Check limit for a user in g-users-a_b: their usage should be 0 because g-users-aXb must not match!
        decision = check_usage_limits(self.db, "target_user", ["g-users-a_b"], "anthropic.claude-sonnet-4-6")
        self.assertIsNone(decision.enforcement)

    def test_session_to_dict_does_not_contain_groups(self):
        # Privacy: session owner's group memberships must not leak in session responses.
        session = self._make_session("s_priv", "alice", groups=["g-admins-security", "g-users"])
        data = session.to_dict()
        self.assertNotIn("groups", data)

    def test_block_enforcement_skips_cache_and_computes_live(self):
        # Block limits must bypass cached_usage to prevent parallel overshoot
        limit = UsageLimit(
            name="Block Bypass Cache",
            scope=json.dumps({"type": "user", "username": "alice"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=100,
            window="daily",
            enforcement="block",
            cached_usage=10.0,
            cached_usage_updated_at=datetime.utcnow(),
        )
        self.db.add(limit)
        self.db.commit()

        self._make_session("s_block", "alice")
        self._make_invocation("s_block", "i_block", "anthropic.claude-sonnet-4-6", input_tokens=70, output_tokens=70)

        decision = check_usage_limits(self.db, "alice", [], "anthropic.claude-sonnet-4-6")
        self.assertEqual(decision.enforcement, "block")
        self.assertEqual(decision.current_usage, 140.0)

    def test_warn_enforcement_uses_fresh_cache(self):
        # Warn limits use cached_usage when fresh
        limit = UsageLimit(
            name="Warn Fresh Cache",
            scope=json.dumps({"type": "user", "username": "alice"}),
            target=json.dumps({"type": "all"}),
            measure="tokens",
            threshold=100,
            window="daily",
            enforcement="warn",
            cached_usage=10.0,
            cached_usage_updated_at=datetime.utcnow(),
        )
        self.db.add(limit)
        self.db.commit()

        self._make_session("s_warn", "alice")
        self._make_invocation("s_warn", "i_warn", "anthropic.claude-sonnet-4-6", input_tokens=70, output_tokens=70)

        decision = check_usage_limits(self.db, "alice", [], "anthropic.claude-sonnet-4-6")
        self.assertIsNone(decision.enforcement)
        self.assertEqual(len(decision.warnings), 0)


if __name__ == "__main__":
    unittest.main()

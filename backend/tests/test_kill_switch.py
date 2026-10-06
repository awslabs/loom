"""Tests for the agent kill switch: Stop / Resume through the runtime resource policy, and its guards."""
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.main import app
from app.models.agent import Agent
from app.models.evaluation import EvaluationRun, EvaluationTestCase
from app.models.kill_switch import AgentKillSwitchEvent
from app.models.session import InvocationSession
from app.services import kill_switch as ks

APP_DIR = Path(__file__).resolve().parents[1] / "app"
ACCOUNT = "123456789012"
RUNTIME_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/demo_agent-AbCdEf1234"
OTHER_STATEMENT = {
    "Sid": "AllowPartnerAccount",
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::210987654321:role/Caller"},
    "Action": "bedrock-agentcore:InvokeAgentRuntime",
    "Resource": RUNTIME_ARN,
}


def _client_error(code: str, op: str, request_id: str = "req-err") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": f"{code} message"}, "ResponseMetadata": {"RequestId": request_id}}, op,
    )


class _CallLog(list):
    """Ordered (service, operation, arn) tuples shared by the fakes, to check call order."""


class _FakeControl:
    """Just enough bedrock-agentcore-control: one resource policy per ARN, with optional failures."""

    def __init__(self, log: _CallLog):
        self.policies: dict[str, str] = {}
        self.log = log
        self.get_error: Exception | None = None
        self.put_error: Exception | None = None

    def get_resource_policy(self, resourceArn):
        self.log.append(("control", "get", resourceArn))
        if self.get_error:
            raise self.get_error
        if resourceArn not in self.policies:
            raise _client_error("ResourceNotFoundException", "GetResourcePolicy", "req-nf")
        return {"policy": self.policies[resourceArn], "ResponseMetadata": {"RequestId": "req-get"}}

    def put_resource_policy(self, resourceArn, policy):
        self.log.append(("control", "put", resourceArn))
        if self.put_error:
            raise self.put_error
        json.loads(policy)  # AgentCore rejects anything that is not JSON
        self.policies[resourceArn] = policy
        return {"policy": policy, "ResponseMetadata": {"RequestId": "req-put"}}

    def delete_resource_policy(self, resourceArn):
        self.log.append(("control", "delete", resourceArn))
        if resourceArn not in self.policies:
            raise _client_error("ResourceNotFoundException", "DeleteResourcePolicy", "req-nf")
        del self.policies[resourceArn]
        return {"ResponseMetadata": {"RequestId": "req-delete"}}

    def statements(self, arn: str = RUNTIME_ARN) -> list[dict]:
        if arn not in self.policies:
            return []
        return json.loads(self.policies[arn])["Statement"]

    def writes(self) -> list[tuple]:
        return [c for c in self.log if c[0] == "control" and c[1] in ("put", "delete")]


class _FakeAgentCore:
    """StopRuntimeSession: per-session outcomes, thread-safe enough for the pool."""

    def __init__(self, log: _CallLog, missing: set[str] | None = None, failing: set[str] | None = None):
        self.log = log
        self.missing = missing or set()
        self.failing = failing or set()
        self.stopped: list[tuple[str, str, str]] = []

    def stop_runtime_session(self, agentRuntimeArn, runtimeSessionId, qualifier):
        self.log.append(("agentcore", "stop_session", agentRuntimeArn))
        self.stopped.append((agentRuntimeArn, runtimeSessionId, qualifier))
        if runtimeSessionId in self.missing:
            raise _client_error("ResourceNotFoundException", "StopRuntimeSession", f"req-nf-{runtimeSessionId[:4]}")
        if runtimeSessionId in self.failing:
            raise _client_error("AccessDeniedException", "StopRuntimeSession", f"req-ad-{runtimeSessionId[:4]}")
        return {"ResponseMetadata": {"RequestId": f"req-stop-{runtimeSessionId[:4]}"},
                "runtimeSessionId": runtimeSessionId, "statusCode": 200}


class KillSwitchApiTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                                   poolclass=StaticPool)

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
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.agent = self._agent("demo_agent", RUNTIME_ARN)
        self.log = _CallLog()
        self.control = _FakeControl(self.log)
        self.agentcore = _FakeAgentCore(self.log)
        self._patches = [
            patch("app.services.kill_switch._control_client", side_effect=lambda region: self.control),
            patch("app.services.kill_switch._agentcore_client", side_effect=lambda region: self.agentcore),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    # -- helpers -----------------------------------------------------------

    def _agent(self, name: str, arn: str, group: str | None = None, source: str = "deploy",
               role_arn: str = f"arn:aws:iam::{ACCOUNT}:role/loom-agent-demo") -> Agent:
        agent = Agent(arn=arn, runtime_id=arn.rsplit("/", 1)[-1], name=name, status="READY",
                      region="us-east-1", account_id=ACCOUNT, source=source, execution_role_arn=role_arn)
        agent.set_available_qualifiers(["DEFAULT"])
        if group:
            agent.set_tags({"loom:group": group})
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return agent

    def _session(self, agent: Agent, session_id: str, age: timedelta = timedelta(minutes=5)) -> None:
        self.session.add(InvocationSession(agent_id=agent.id, session_id=session_id, qualifier="DEFAULT",
                                           status="complete", created_at=datetime.utcnow() - age))
        self.session.commit()

    def _as_user(self, groups: list[str], username: str = "operator") -> None:
        user = UserInfo(sub=username, username=username, groups=groups, scopes=derive_scopes(groups))
        app.dependency_overrides[get_current_user] = lambda: user

    def _stop(self, agent: Agent, reason: str = "prompt injection reported"):
        return self.client.post(f"/api/agents/{agent.id}/stop", json={"reason": reason})

    def _resume(self, agent: Agent, reason: str = "fix verified"):
        return self.client.post(f"/api/agents/{agent.id}/resume", json={"reason": reason})

    def _events(self, agent: Agent) -> list[AgentKillSwitchEvent]:
        return (self.session.query(AgentKillSwitchEvent)
                .filter(AgentKillSwitchEvent.agent_id == agent.id)
                .order_by(AgentKillSwitchEvent.id).all())

    def _set_policy(self, *statements: dict, arn: str = RUNTIME_ARN) -> None:
        self.control.policies[arn] = json.dumps({"Version": "2012-10-17", "Statement": list(statements)})

    # -- Stop ----------------------------------------------------------------

    def test_stop_adds_the_deny_stops_recent_sessions_and_records_who_when_why(self):
        self.agent.set_raw_metadata({"lifecycleConfiguration": {"maxLifetime": 28800}})
        self.session.commit()
        self._session(self.agent, "a" * 36)
        self._session(self.agent, "b" * 36)
        self._session(self.agent, "c" * 36, age=timedelta(hours=9))  # older than the runtime's 8 h maxLifetime
        self.agentcore.missing = {"b" * 36}

        response = self._stop(self.agent)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["changed"])
        self.assertEqual(body["status"]["state"], "stopped")
        self.assertTrue(body["status"]["deny_present"])
        self.assertEqual(self.control.statements(), [ks.deny_statement(RUNTIME_ARN)])
        self.assertEqual(sorted(s[1] for s in self.agentcore.stopped), ["a" * 36, "b" * 36])
        self.assertTrue(all(s[0] == RUNTIME_ARN and s[2] == "DEFAULT" for s in self.agentcore.stopped))

        self.session.refresh(self.agent)
        self.assertIsNotNone(self.agent.stopped_at)
        self.assertEqual(self.agent.stopped_by, "local-dev")
        self.assertEqual(self.agent.stop_reason, "prompt injection reported")

        [stop_event] = self._events(self.agent)
        self.assertEqual((stop_event.action, stop_event.policy_change, stop_event.request_id),
                         ("stop", "deny_added", "req-put"))
        self.assertEqual(stop_event.runtime_arn, RUNTIME_ARN)
        results = {s["session_id"]: s["result"] for s in stop_event.get_sessions()}
        self.assertEqual(results, {"a" * 36: "stopped", "b" * 36: "not_running"})

    def test_the_deny_is_written_before_any_session_is_stopped(self):
        self._session(self.agent, "a" * 36)
        self.assertEqual(self._stop(self.agent).status_code, 200)
        order = [c[1] for c in self.log if c[1] in ("put", "stop_session")]
        self.assertEqual(order, ["put", "stop_session"])

    def test_the_deny_statement_covers_every_invoke_action_on_this_runtime_only(self):
        statement = ks.deny_statement(RUNTIME_ARN)
        self.assertEqual((statement["Effect"], statement["Principal"], statement["Resource"]),
                         ("Deny", "*", RUNTIME_ARN))
        self.assertNotIn("Condition", statement)
        self.assertEqual(set(statement["Action"]), {
            "bedrock-agentcore:InvokeAgentRuntime",
            "bedrock-agentcore:InvokeAgentRuntimeForUser",
            "bedrock-agentcore:InvokeAgentRuntimeCommand",
            "bedrock-agentcore:InvokeAgentRuntimeCommandShell",
            "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream",
            "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStreamForUser",
        })
        # Loom must still be able to end sessions on a stopped runtime.
        self.assertNotIn("bedrock-agentcore:StopRuntimeSession", statement["Action"])

    def test_stop_keeps_the_statements_already_on_the_runtime(self):
        self._set_policy(OTHER_STATEMENT)
        self.assertEqual(self._stop(self.agent).status_code, 200)
        self.assertEqual(self.control.statements(), [OTHER_STATEMENT, ks.deny_statement(RUNTIME_ARN)])

    def test_unknown_max_lifetime_falls_back_to_the_api_maximum(self):
        # No lifecycle configuration known: a 9-day-old session may still run
        # (maxLifetime can be up to 14 days); a 15-day-old one cannot.
        self._session(self.agent, "f" * 36, age=timedelta(days=9))
        self._session(self.agent, "g" * 36, age=timedelta(days=15))
        self.assertEqual(self._stop(self.agent).status_code, 200)
        self.assertEqual([s[1] for s in self.agentcore.stopped], ["f" * 36])

    def test_stop_without_a_reason_is_refused_and_changes_nothing(self):
        for reason in ("", "   "):
            response = self._stop(self.agent, reason=reason)
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post(f"/api/agents/{self.agent.id}/stop", json={})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.log, [])
        self.session.refresh(self.agent)
        self.assertIsNone(self.agent.stopped_at)

    def test_stopping_a_stopped_agent_changes_nothing_and_says_so(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        response = self._stop(self.agent, reason="again")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["changed"])
        self.assertIn("already stopped", response.json()["message"])
        self.assertEqual(len(self.control.writes()), 1)
        self.assertEqual(len(self._events(self.agent)), 1)

    def test_when_aws_refuses_the_policy_write_nothing_is_recorded(self):
        self.control.put_error = _client_error("AccessDeniedException", "PutResourcePolicy")
        self._session(self.agent, "a" * 36)
        response = self._stop(self.agent)
        self.assertEqual(response.status_code, 502)
        self.assertIn("AccessDeniedException", response.json()["detail"])
        self.session.refresh(self.agent)
        self.assertIsNone(self.agent.stopped_at)
        self.assertEqual(self._events(self.agent), [])
        self.assertEqual(self.agentcore.stopped, [])

    def test_a_failed_record_undoes_the_deny(self):
        with patch.object(self.session, "commit", side_effect=RuntimeError("db down")):
            response = self._stop(self.agent)
        self.assertEqual(response.status_code, 500)
        self.assertIn("undone", response.json()["detail"])
        self.assertNotIn(RUNTIME_ARN, self.control.policies)

    def test_a_session_that_cannot_be_stopped_does_not_undo_the_stop(self):
        self._session(self.agent, "d" * 36)
        self.agentcore.failing = {"d" * 36}
        response = self._stop(self.agent)
        self.assertEqual(response.status_code, 200)
        self.assertIn("could not be stopped", response.json()["message"])
        [result] = self._events(self.agent)[0].get_sessions()
        self.assertEqual(result["result"], "failed")
        self.assertIn("AccessDeniedException", result["error"])
        self.assertEqual(self.control.statements(), [ks.deny_statement(RUNTIME_ARN)])

    def test_a_statement_with_looms_sid_that_loom_did_not_write_is_left_alone(self):
        foreign = {**ks.deny_statement(RUNTIME_ARN), "Action": "bedrock-agentcore:InvokeAgentRuntime"}
        self._set_policy(foreign)
        for call in (self._stop, self._resume):
            response = call(self.agent)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn("did not write", response.json()["detail"])
        self.assertEqual(self.control.writes(), [])
        self.assertEqual(self.control.statements(), [foreign])
        body = self.client.get(f"/api/agents/{self.agent.id}/kill-switch").json()
        self.assertEqual(body["state"], "unknown")
        self.assertIn("did not write", body["policy_error"])

    def test_stopping_one_agent_never_stops_another_on_the_same_role(self):
        other_arn = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/billing-X"
        other = self._agent("billing_agent", other_arn)  # same execution role as self.agent
        self.assertEqual(self._stop(self.agent).status_code, 200)
        self.session.refresh(other)
        self.assertIsNone(other.stopped_at)
        self.assertNotIn(other_arn, self.control.policies)
        self.assertEqual(self._events(other), [])

    def test_stop_needs_agent_write_and_group_access(self):
        self._as_user(["t-user", "g-users-demo"])
        self.assertEqual(self._stop(self.agent).status_code, 403)
        strategic = self._agent("strategic_two", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/s-2",
                                group="strategics")
        self._as_user(["t-admin", "g-admins-demo"])
        self.assertEqual(self._stop(strategic).status_code, 403)
        self.assertEqual(self.client.get(f"/api/agents/{strategic.id}/kill-switch").status_code, 403)
        self.assertEqual(self.log, [])

    def test_agents_without_a_runtime_arn_are_unavailable(self):
        harness = self._agent("managed", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:harness/h-1",
                              source="harness")
        response = self._stop(harness)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Only AgentCore Runtime agents", response.json()["detail"])
        body = self.client.get(f"/api/agents/{harness.id}/kill-switch").json()
        self.assertEqual(body["state"], "unavailable")
        self.assertEqual(self.log, [])

    def test_the_execution_role_plays_no_part(self):
        # Option-B design: any registered role works, including one outside role/loom-*.
        toolkit = self._agent("toolkit_agent", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/tk-1",
                              role_arn=f"arn:aws:iam::{ACCOUNT}:role/AmazonBedrockAgentCoreSDKRuntime-x")
        self.assertEqual(self._stop(toolkit).status_code, 200)

    # -- Resume --------------------------------------------------------------

    def test_resume_deletes_the_policy_when_the_deny_was_its_only_statement(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        response = self._resume(self.agent)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"]["state"], "running")
        self.assertEqual(self.control.writes()[-1], ("control", "delete", RUNTIME_ARN))
        self.assertNotIn(RUNTIME_ARN, self.control.policies)
        self.session.refresh(self.agent)
        self.assertIsNone(self.agent.stopped_at)
        self.assertEqual([e.action for e in self._events(self.agent)], ["stop", "resume"])
        last = self._events(self.agent)[-1]
        self.assertEqual((last.policy_change, last.request_id), ("deny_removed", "req-delete"))

    def test_resume_restores_the_other_statements_exactly(self):
        self._set_policy(OTHER_STATEMENT)
        before = self.control.policies[RUNTIME_ARN]
        self.assertEqual(self._stop(self.agent).status_code, 200)
        self.assertEqual(self._resume(self.agent).status_code, 200)
        self.assertEqual(json.loads(self.control.policies[RUNTIME_ARN]), json.loads(before))

    def test_resume_without_a_reason_is_refused(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        self.assertEqual(self._resume(self.agent, reason=" ").status_code, 422)
        self.session.refresh(self.agent)
        self.assertIsNotNone(self.agent.stopped_at)

    def test_resuming_a_running_agent_changes_nothing(self):
        response = self._resume(self.agent)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["changed"])
        self.assertEqual(self.control.writes(), [])
        self.assertEqual(self._events(self.agent), [])

    def test_drift_is_reported_and_both_actions_repair_it(self):
        # Stopped in Loom, but someone removed the policy outside Loom.
        self.assertEqual(self._stop(self.agent).status_code, 200)
        self.control.policies.clear()
        status_body = self.client.get(f"/api/agents/{self.agent.id}/kill-switch").json()
        self.assertEqual(status_body["state"], "stop_not_enforced")
        response = self._stop(self.agent, reason="re-apply")
        self.assertTrue(response.json()["changed"])
        self.assertEqual(self.control.statements(), [ks.deny_statement(RUNTIME_ARN)])

        # Deny present, but no stop in Loom: Resume removes it.
        other_arn = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/o-1"
        other = self._agent("other", other_arn)
        self._set_policy(ks.deny_statement(other_arn), arn=other_arn)
        status_body = self.client.get(f"/api/agents/{other.id}/kill-switch").json()
        self.assertEqual(status_body["state"], "stopped_outside_loom")
        self.assertTrue(self._resume(other).json()["changed"])
        self.assertNotIn(other_arn, self.control.policies)

    def test_status_reports_unknown_when_the_policy_cannot_be_read(self):
        self.control.get_error = _client_error("AccessDeniedException", "GetResourcePolicy")
        body = self.client.get(f"/api/agents/{self.agent.id}/kill-switch").json()
        self.assertEqual((body["state"], body["deny_present"]), ("unknown", None))
        self.assertIn("AccessDeniedException", body["policy_error"])
        self.assertEqual(self._stop(self.agent).status_code, 502)

    # -- Guards while stopped ---------------------------------------------

    def test_a_stopped_agent_cannot_be_invoked_or_redeployed(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        response = self.client.post(f"/api/agents/{self.agent.id}/invoke",
                                    json={"prompt": "hello", "qualifier": "DEFAULT"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("prompt injection reported", response.json()["detail"])
        self.assertEqual(self.session.query(InvocationSession).filter(
            InvocationSession.agent_id == self.agent.id).count(), 0)

        response = self.client.post(f"/api/agents/{self.agent.id}/redeploy")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Cannot redeploy", response.json()["detail"])

    def test_a_stopped_agent_cannot_run_an_evaluation_test_case(self):
        # A test-case run invokes the agent for real, so it is refused like /invoke.
        test_case = EvaluationTestCase(agent_id=self.agent.id, name="smoke", prompt="hello")
        test_case.set_evaluator_ids(["Builtin.Helpfulness"])
        self.session.add(test_case)
        self.session.commit()
        self.assertEqual(self._stop(self.agent).status_code, 200)
        with patch("app.routers.evaluations._execute_run") as execute_run:
            response = self.client.post(
                f"/api/agents/{self.agent.id}/evaluations/test-cases/{test_case.id}/run")
        self.assertEqual(response.status_code, 409)
        self.assertIn("prompt injection reported", response.json()["detail"])
        execute_run.assert_not_called()
        self.assertEqual(self.session.query(EvaluationRun).count(), 0)

    def test_the_audit_trail_outlives_the_agent(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        agent_id = self.agent.id
        self.assertEqual(self.client.delete(f"/api/agents/{agent_id}/purge").status_code, 204)
        remaining = self.session.query(AgentKillSwitchEvent).filter(AgentKillSwitchEvent.agent_id == agent_id).all()
        self.assertEqual([e.action for e in remaining], ["stop"])

    def test_agent_responses_carry_the_stopped_state(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        body = self.client.get(f"/api/agents/{self.agent.id}").json()
        self.assertEqual(body["stop_reason"], "prompt injection reported")
        self.assertEqual(body["stopped_by"], "local-dev")
        self.assertTrue(body["stopped_at"].endswith("Z"))


class KillSwitchServiceTests(unittest.TestCase):

    def test_state_combines_loom_record_with_the_live_policy(self):
        self.assertEqual(ks.derive_state(False, False), "running")
        self.assertEqual(ks.derive_state(True, True), "stopped")
        self.assertEqual(ks.derive_state(True, False), "stop_not_enforced")
        self.assertEqual(ks.derive_state(False, True), "stopped_outside_loom")
        self.assertEqual(ks.derive_state(True, None), "unknown")

    def test_a_single_statement_object_is_read_as_a_list(self):
        policy = {"Version": "2012-10-17", "Statement": ks.deny_statement(RUNTIME_ARN)}
        self.assertTrue(ks.has_deny(policy, RUNTIME_ARN))
        self.assertFalse(ks.has_deny(None, RUNTIME_ARN))

    def test_a_runtime_without_a_policy_reads_as_no_policy(self):
        # Verified live: GetResourcePolicy on a runtime that has none succeeds with no "policy" field.
        class _Empty:
            def get_resource_policy(self, resourceArn):
                return {"ResponseMetadata": {"RequestId": "req-empty"}}

        with patch("app.services.kill_switch._control_client", return_value=_Empty()):
            self.assertEqual(ks.get_policy(RUNTIME_ARN, "us-east-1"), (None, "req-empty"))

    def test_a_deny_written_for_another_runtime_is_not_ours(self):
        other = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/other-1"
        with self.assertRaises(ks.ForeignPolicyStatement):
            ks.has_deny({"Statement": [ks.deny_statement(other)]}, RUNTIME_ARN)

    def test_the_kill_switch_never_writes_iam(self):
        # Loom has no IAM write capability (tests/test_authorization_invariants.py);
        # the kill switch must not even build an IAM client.
        source = (APP_DIR / "services" / "kill_switch.py").read_text(encoding="utf-8")
        self.assertNotIn('client("iam"', source)
        self.assertNotIn("client('iam'", source)


if __name__ == "__main__":
    unittest.main()

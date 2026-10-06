"""Tests for the agent kill switch: Stop / Resume, the guards it adds, and its IaC."""
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml
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

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = "123456789012"
POLICY = f"arn:aws:iam::{ACCOUNT}:policy/loom-agent-kill-switch"
ROLE_NAME = "loom-agent-demo"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
RUNTIME_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/demo_agent-AbCdEf1234"


def _client_error(code: str, op: str, request_id: str = "req-err") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": f"{code} message"}, "ResponseMetadata": {"RequestId": request_id}}, op,
    )


class _FakeIam:
    """Just enough IAM: attached managed policies per role, with optional failures."""

    def __init__(self, attached: dict[str, set[str]] | None = None):
        self.attached = {k: set(v) for k, v in (attached or {}).items()}
        self.calls: list[tuple] = []
        self.attach_error: Exception | None = None
        self.detach_error: Exception | None = None
        self.list_error: Exception | None = None

    def get_paginator(self, name):
        assert name == "list_attached_role_policies"
        fake = self

        class _Paginator:
            def paginate(self, RoleName):
                fake.calls.append(("list", RoleName))
                if fake.list_error:
                    raise fake.list_error
                policies = sorted(fake.attached.get(RoleName, set()))
                yield {"AttachedPolicies": [{"PolicyArn": p, "PolicyName": p.rsplit("/", 1)[-1]} for p in policies]}

        return _Paginator()

    def attach_role_policy(self, RoleName, PolicyArn):
        self.calls.append(("attach", RoleName, PolicyArn))
        if self.attach_error:
            raise self.attach_error
        self.attached.setdefault(RoleName, set()).add(PolicyArn)
        return {"ResponseMetadata": {"RequestId": "req-attach"}}

    def detach_role_policy(self, RoleName, PolicyArn):
        self.calls.append(("detach", RoleName, PolicyArn))
        if self.detach_error:
            raise self.detach_error
        if PolicyArn not in self.attached.get(RoleName, set()):
            raise _client_error("NoSuchEntity", "DetachRolePolicy", "req-nse")
        self.attached[RoleName].discard(PolicyArn)
        return {"ResponseMetadata": {"RequestId": "req-detach"}}

    def iam_writes(self) -> list[tuple]:
        return [c for c in self.calls if c[0] in ("attach", "detach")]


class _FakeAgentCore:
    """StopRuntimeSession: per-session outcomes, thread-safe enough for the pool."""

    def __init__(self, missing: set[str] | None = None, failing: set[str] | None = None):
        self.missing = missing or set()
        self.failing = failing or set()
        self.stopped: list[tuple[str, str, str]] = []

    def stop_runtime_session(self, agentRuntimeArn, runtimeSessionId, qualifier):
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
        self.iam = _FakeIam()
        self.agentcore = _FakeAgentCore()
        self._patches = [
            patch.dict(os.environ, {ks.KILL_SWITCH_POLICY_ARN_ENV: POLICY}),
            patch("app.services.kill_switch._iam_client", side_effect=lambda: self.iam),
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

    def _agent(self, name: str, arn: str, role_arn: str | None = ROLE_ARN, group: str | None = None,
               source: str = "deploy") -> Agent:
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

    def _stop(self, agent: Agent, reason: str = "prompt injection reported", ack: bool = False):
        return self.client.post(f"/api/agents/{agent.id}/stop",
                                json={"reason": reason, "acknowledge_shared_role": ack})

    def _resume(self, agent: Agent, reason: str = "fix verified", ack: bool = False):
        return self.client.post(f"/api/agents/{agent.id}/resume",
                                json={"reason": reason, "acknowledge_shared_role": ack})

    def _events(self, agent: Agent) -> list[AgentKillSwitchEvent]:
        return (self.session.query(AgentKillSwitchEvent)
                .filter(AgentKillSwitchEvent.agent_id == agent.id)
                .order_by(AgentKillSwitchEvent.id).all())

    # -- Stop ----------------------------------------------------------------

    def test_stop_attaches_the_deny_stops_recent_sessions_and_records_who_when_why(self):
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
        self.assertTrue(body["status"]["deny_attached"])
        self.assertEqual(self.iam.iam_writes(), [("attach", ROLE_NAME, POLICY)])
        self.assertEqual(sorted(s[1] for s in self.agentcore.stopped), ["a" * 36, "b" * 36])
        self.assertTrue(all(s[0] == RUNTIME_ARN and s[2] == "DEFAULT" for s in self.agentcore.stopped))

        self.session.refresh(self.agent)
        self.assertIsNotNone(self.agent.stopped_at)
        self.assertEqual(self.agent.stopped_by, "local-dev")
        self.assertEqual(self.agent.stop_reason, "prompt injection reported")

        [stop_event] = self._events(self.agent)
        self.assertEqual((stop_event.action, stop_event.iam_change, stop_event.iam_request_id),
                         ("stop", "attached", "req-attach"))
        self.assertEqual(stop_event.role_arn, ROLE_ARN)
        results = {s["session_id"]: s["result"] for s in stop_event.get_sessions()}
        self.assertEqual(results, {"a" * 36: "stopped", "b" * 36: "not_running"})

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
        self.assertEqual(self.iam.calls, [])
        self.session.refresh(self.agent)
        self.assertIsNone(self.agent.stopped_at)

    def test_stopping_a_stopped_agent_changes_nothing_and_says_so(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        response = self._stop(self.agent, reason="again")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["changed"])
        self.assertIn("already stopped", response.json()["message"])
        self.assertEqual(len(self.iam.iam_writes()), 1)
        self.assertEqual(len(self._events(self.agent)), 1)

    def test_when_aws_refuses_the_attach_nothing_is_recorded(self):
        self.iam.attach_error = _client_error("AccessDenied", "AttachRolePolicy")
        response = self._stop(self.agent)
        self.assertEqual(response.status_code, 502)
        self.assertIn("AccessDenied", response.json()["detail"])
        self.session.refresh(self.agent)
        self.assertIsNone(self.agent.stopped_at)
        self.assertEqual(self._events(self.agent), [])

    def test_a_session_that_cannot_be_stopped_does_not_undo_the_stop(self):
        self._session(self.agent, "d" * 36)
        self.agentcore.failing = {"d" * 36}
        response = self._stop(self.agent)
        self.assertEqual(response.status_code, 200)
        self.assertIn("could not be stopped", response.json()["message"])
        [result] = self._events(self.agent)[0].get_sessions()
        self.assertEqual(result["result"], "failed")
        self.assertIn("AccessDeniedException", result["error"])
        self.assertTrue(self.iam.attached[ROLE_NAME] == {POLICY})

    def test_non_runtime_agents_skip_the_session_stop_but_are_still_denied(self):
        harness = self._agent("managed", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:harness/h-1",
                              role_arn=f"arn:aws:iam::{ACCOUNT}:role/loom-harness", source="harness")
        self._session(harness, "e" * 36)
        response = self._stop(harness)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.agentcore.stopped, [])
        [result] = self._events(harness)[0].get_sessions()
        self.assertEqual(result["result"], "skipped")
        self.assertEqual(self.iam.iam_writes(), [("attach", "loom-harness", POLICY)])

    def test_shared_role_needs_acknowledgement_and_then_stops_every_agent_on_it(self):
        other = self._agent("billing_agent", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/billing-X")
        response = self._stop(self.agent)
        self.assertEqual(response.status_code, 409)
        self.assertIn("billing_agent", response.json()["detail"])
        self.assertEqual(self.iam.iam_writes(), [])

        response = self._stop(self.agent, ack=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.session.refresh(other)
        self.assertIsNotNone(other.stopped_at)
        [other_event] = self._events(other)
        self.assertEqual(other_event.get_shared_with(), [self.agent.id])
        self.assertEqual(len(self.iam.iam_writes()), 1)

    def test_role_shared_with_an_agent_outside_the_callers_group_is_refused(self):
        mine = self._agent("demo_one", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/demo-1",
                           role_arn=f"arn:aws:iam::{ACCOUNT}:role/loom-shared", group="demo")
        self._agent("strategic_one", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/strat-1",
                    role_arn=f"arn:aws:iam::{ACCOUNT}:role/loom-shared", group="strategics")
        self._as_user(["t-admin", "g-admins-demo"])
        response = self._stop(mine, ack=True)
        self.assertEqual(response.status_code, 403)
        self.assertIn("outside your group", response.json()["detail"])
        self.assertEqual(self.iam.iam_writes(), [])

    def test_stop_needs_agent_write_and_group_access(self):
        self._as_user(["t-user", "g-users-demo"])
        self.assertEqual(self._stop(self.agent).status_code, 403)
        strategic = self._agent("strategic_two", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/s-2",
                                role_arn=f"arn:aws:iam::{ACCOUNT}:role/loom-s2", group="strategics")
        self._as_user(["t-admin", "g-admins-demo"])
        self.assertEqual(self._stop(strategic).status_code, 403)
        self.assertEqual(self.iam.calls, [])

    def test_not_configured_or_no_role_is_a_clear_409(self):
        with patch.dict(os.environ, {ks.KILL_SWITCH_POLICY_ARN_ENV: ""}):
            response = self._stop(self.agent)
            self.assertEqual(response.status_code, 409)
            self.assertIn(ks.KILL_SWITCH_POLICY_ARN_ENV, response.json()["detail"])
            status_body = self.client.get(f"/api/agents/{self.agent.id}/kill-switch").json()
            self.assertEqual((status_body["configured"], status_body["state"]), (False, "unavailable"))

        roleless = self._agent("roleless", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/r-1", role_arn=None)
        response = self._stop(roleless)
        self.assertEqual(response.status_code, 409)
        self.assertIn("no execution role", response.json()["detail"])
        self.assertEqual(self.iam.calls, [])

    def test_roles_outside_loom_are_refused_because_other_runtimes_may_share_them(self):
        toolkit = self._agent("toolkit_agent", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/tk-1",
                              role_arn=f"arn:aws:iam::{ACCOUNT}:role/AmazonBedrockAgentCoreSDKRuntime-us-east-1-abc")
        response = self._stop(toolkit)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Loom role", response.json()["detail"])
        body = self.client.get(f"/api/agents/{toolkit.id}/kill-switch").json()
        self.assertEqual((body["configured"], body["state"]), (True, "unavailable"))

        pathed = self._agent("pathed", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/p-1",
                             role_arn=f"arn:aws:iam::{ACCOUNT}:role/service-role/loom-pathed")
        self.assertEqual(self._stop(pathed).status_code, 409)
        self.assertEqual(self.iam.calls, [])

    def test_registered_agents_use_the_role_agentcore_reports(self):
        registered = self._agent("registered", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/reg-1",
                                 role_arn=None, source="register")
        registered.set_raw_metadata({"roleArn": f"arn:aws:iam::{ACCOUNT}:role/loom-registered"})
        self.session.commit()
        self.assertEqual(self._stop(registered).status_code, 200)
        self.assertEqual(self.iam.iam_writes(), [("attach", "loom-registered", POLICY)])

    # -- Resume --------------------------------------------------------------

    def test_resume_detaches_the_deny_and_clears_the_record(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        response = self._resume(self.agent)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"]["state"], "running")
        self.assertEqual(self.iam.iam_writes()[-1], ("detach", ROLE_NAME, POLICY))
        self.session.refresh(self.agent)
        self.assertIsNone(self.agent.stopped_at)
        self.assertEqual([e.action for e in self._events(self.agent)], ["stop", "resume"])
        self.assertEqual(self._events(self.agent)[-1].iam_request_id, "req-detach")

    def test_resume_without_a_reason_is_refused(self):
        self.assertEqual(self._stop(self.agent).status_code, 200)
        self.assertEqual(self._resume(self.agent, reason=" ").status_code, 422)
        self.session.refresh(self.agent)
        self.assertIsNotNone(self.agent.stopped_at)

    def test_resuming_a_running_agent_changes_nothing(self):
        response = self._resume(self.agent)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["changed"])
        self.assertEqual(self.iam.iam_writes(), [])
        self.assertEqual(self._events(self.agent), [])

    def test_drift_is_reported_and_both_actions_repair_it(self):
        # Stopped in Loom, but someone detached the policy in IAM.
        self.assertEqual(self._stop(self.agent).status_code, 200)
        self.iam.attached[ROLE_NAME].clear()
        status_body = self.client.get(f"/api/agents/{self.agent.id}/kill-switch").json()
        self.assertEqual(status_body["state"], "stop_not_enforced")
        response = self._stop(self.agent, reason="re-apply")
        self.assertTrue(response.json()["changed"])
        self.assertEqual(self.iam.attached[ROLE_NAME], {POLICY})

        # Attached in IAM, but no stop in Loom: Resume detaches it.
        other = self._agent("other", f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/o-1",
                            role_arn=f"arn:aws:iam::{ACCOUNT}:role/loom-other")
        self.iam.attached["loom-other"] = {POLICY}
        status_body = self.client.get(f"/api/agents/{other.id}/kill-switch").json()
        self.assertEqual(status_body["state"], "stopped_outside_loom")
        self.assertTrue(self._resume(other).json()["changed"])
        self.assertEqual(self.iam.attached["loom-other"], set())

    def test_status_reports_unknown_when_iam_cannot_be_read(self):
        self.iam.list_error = _client_error("AccessDenied", "ListAttachedRolePolicies")
        body = self.client.get(f"/api/agents/{self.agent.id}/kill-switch").json()
        self.assertEqual((body["state"], body["deny_attached"]), ("unknown", None))
        self.assertIn("AccessDenied", body["iam_error"])
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


# ---------------------------------------------------------------------------
# Infrastructure as code: the policy content and the backend's grant
# ---------------------------------------------------------------------------

class _CfnLoader(yaml.SafeLoader):
    """YAML loader that keeps CloudFormation short-form tags as {'!Tag': value}."""


def _cfn_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {f"!{tag_suffix}": value}


_CfnLoader.add_multi_constructor("!", _cfn_tag)


def _load_template(relative: str) -> dict:
    return yaml.load((REPO_ROOT / relative).read_text(encoding="utf-8"), Loader=_CfnLoader)


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


class KillSwitchIacTests(unittest.TestCase):

    def test_the_policy_denies_everything_except_telemetry_writes(self):
        template = _load_template("shared/iac/kill_switch.yaml")
        policy = template["Resources"]["KillSwitchPolicy"]
        self.assertEqual(policy["Type"], "AWS::IAM::ManagedPolicy")
        [statement] = policy["Properties"]["PolicyDocument"]["Statement"]
        self.assertEqual(statement["Effect"], "Deny")
        self.assertNotIn("Action", statement)
        self.assertEqual(statement["Resource"], "*")
        self.assertEqual(len(statement["NotAction"]), len(set(statement["NotAction"])))
        self.assertEqual(set(statement["NotAction"]), set(ks.TELEMETRY_ACTIONS))
        self.assertNotIn("Condition", statement)

    def test_the_backend_may_only_attach_and_detach_that_policy_on_loom_roles(self):
        template = _load_template("backend/iac/ecs.yaml")
        policies = template["Resources"]["TaskRole"]["Properties"]["Policies"]

        conditional = [p["!If"] for p in policies if isinstance(p, dict) and "!If" in p]
        [(condition, kill_switch_policy, otherwise)] = [c for c in conditional if c[0] == "HasKillSwitchPolicy"]
        self.assertEqual(otherwise, {"!Ref": "AWS::NoValue"})
        [statement] = kill_switch_policy["PolicyDocument"]["Statement"]
        self.assertEqual(statement["Effect"], "Allow")
        self.assertEqual(set(statement["Action"]), {"iam:AttachRolePolicy", "iam:DetachRolePolicy"})
        self.assertEqual(statement["Resource"], {"!Sub": "arn:aws:iam::${AWS::AccountId}:role/loom-*"})
        self.assertEqual(statement["Condition"], {"ArnEquals": {"iam:PolicyARN": {"!Ref": "pKillSwitchPolicyArn"}}})

        # No other statement on the task role may attach, detach or write role policies.
        risky = {"iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePolicy", "iam:*", "*"}
        for entry in policies:
            if isinstance(entry, dict) and "!If" in entry:
                continue
            for other in entry["PolicyDocument"]["Statement"]:
                self.assertFalse(risky & set(_as_list(other.get("Action", []))), entry["PolicyName"])

        env = template["Resources"]["TaskDefinition"]["Properties"]["ContainerDefinitions"][0]["Environment"]
        self.assertIn({"Name": "LOOM_KILL_SWITCH_POLICY_ARN", "Value": {"!Ref": "pKillSwitchPolicyArn"}}, env)
        self.assertEqual(template["Parameters"]["pKillSwitchPolicyArn"]["Default"], "")


class KillSwitchServiceTests(unittest.TestCase):

    def test_state_combines_loom_record_with_the_live_role(self):
        self.assertEqual(ks.derive_state(False, False), "running")
        self.assertEqual(ks.derive_state(True, True), "stopped")
        self.assertEqual(ks.derive_state(True, False), "stop_not_enforced")
        self.assertEqual(ks.derive_state(False, True), "stopped_outside_loom")
        self.assertEqual(ks.derive_state(True, None), "unknown")

    def test_role_names_come_from_role_arns_including_paths(self):
        self.assertEqual(ks.role_name("arn:aws:iam::123456789012:role/loom-agent-x"), "loom-agent-x")
        self.assertEqual(ks.role_name("arn:aws:iam::123456789012:role/service-role/loom-y"), "loom-y")
        with self.assertRaises(ks.KillSwitchUnavailable):
            ks.role_name("arn:aws:iam::123456789012:user/alice")

    def test_a_malformed_policy_arn_is_not_configured(self):
        with patch.dict(os.environ, {ks.KILL_SWITCH_POLICY_ARN_ENV: "not-an-arn"}):
            with self.assertRaises(ks.KillSwitchUnavailable):
                ks.policy_arn()


if __name__ == "__main__":
    unittest.main()

"""Tests for the read-only AgentCore Evaluations service and router."""

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies.auth import UserInfo, derive_scopes, get_current_user
from app.main import app
from app.models.agent import Agent
from app.routers.evaluations import _agent_target
from app.services import evaluations as evals

LOG_GROUP = "/aws/bedrock-agentcore/runtimes/test_agent-AbCdEf1234-DEFAULT"
OTHER_GROUP = "/aws/bedrock-agentcore/runtimes/other_agent-ZyXwVu9876-DEFAULT"
SERVICE = "test_agent.DEFAULT"
TARGET = evals.AgentTarget(frozenset({LOG_GROUP}), frozenset({SERVICE}))
CFG_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:online-evaluation-config/cfg-1"
RUN_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:batch-evaluate/run-1"


def _not_found(op: str = "Get") -> ClientError:
    return ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "gone"}}, op)


def _result_event(session_id: str, trace_id: str, evaluator: str, value, label: str = "Good",
                  observed_ns: int = 1_790_000_000_000_000_000, service: str = SERVICE,
                  source_arn: str | None = CFG_ARN) -> dict:
    """A CloudWatch event holding one gen_ai.evaluation.result record, as AgentCore writes it."""
    attrs = {
        "gen_ai.evaluation.name": evaluator,
        "session.id": session_id,
        "gen_ai.evaluation.score.value": value,
        "gen_ai.evaluation.score.label": label,
        "gen_ai.evaluation.explanation": f"{evaluator} reasoning",
        "aws.bedrock_agentcore.evaluation_level": "Trace",
    }
    if source_arn and "batch-evaluate" in source_arn:
        attrs["aws.bedrock_agentcore.evaluation_job.arn"] = source_arn
    elif source_arn:
        attrs["aws.bedrock_agentcore.online_evaluation_config.arn"] = source_arn
    record = {
        "name": "gen_ai.evaluation.result",
        "traceId": trace_id,
        "timeUnixNano": observed_ns - 60_000_000_000,
        "observedTimeUnixNano": observed_ns,
        "service.name": service,
        "attributes": attrs,
    }
    return {"timestamp": observed_ns // 1_000_000, "message": json.dumps(record)}


def _online_config(groups=None, services=None, prefixes=None, config_id="cfg-1", output=None) -> dict:
    source = {"serviceNames": services if services is not None else [SERVICE]}
    if groups is not None:
        source["logGroupNames"] = groups
    if prefixes is not None:
        source["logGroupNamePrefixes"] = prefixes
    return {
        "onlineEvaluationConfigId": config_id,
        "onlineEvaluationConfigArn": f"arn:aws:bedrock-agentcore:us-east-1:123456789012:online-evaluation-config/{config_id}",
        "onlineEvaluationConfigName": "baseline",
        "status": "ACTIVE",
        "executionStatus": "ENABLED",
        "rule": {"samplingConfig": {"samplingPercentage": 10.0}, "sessionConfig": {"sessionTimeoutMinutes": 15}},
        "dataSourceConfig": {"cloudWatchLogs": source},
        "evaluators": [{"evaluatorId": "Builtin.Correctness"}],
        "outputConfig": {"cloudWatchConfig": output if output is not None else {}},
    }


class _FakeLogs:
    """Minimal CloudWatch Logs client: filter_log_events honours time range and pages."""

    def __init__(self, events_by_group: dict[str, list[dict]], page_size: int = 2, missing=()):
        self.events_by_group = events_by_group
        self.page_size = page_size
        self.missing = set(missing)
        self.calls: list[dict] = []

    def filter_log_events(self, **kwargs):
        self.calls.append(kwargs)
        group = kwargs["logGroupName"]
        if group in self.missing:
            raise _not_found("FilterLogEvents")
        events = sorted((e for e in self.events_by_group.get(group, [])
                         if kwargs["startTime"] <= e["timestamp"] < kwargs["endTime"]),
                        key=lambda e: e["timestamp"])
        start = int(kwargs.get("nextToken") or 0)
        page = events[start:start + self.page_size]
        nxt = start + self.page_size
        return {"events": page, **({"nextToken": str(nxt)} if nxt < len(events) else {})}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class TestResultParsing(unittest.TestCase):

    def test_skips_malformed_unrelated_and_non_dict_attribute_records(self):
        events = [
            _result_event("s1", "t1", "Builtin.Correctness", 1.0),
            {"message": "not json"},
            {"message": json.dumps({"name": "some.other.event"})},
            {"message": json.dumps({"name": "gen_ai.evaluation.result", "attributes": "oops"})},
            {"message": json.dumps(["a list"])},
        ]
        records = evals.parse_result_records(events)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual((rec["session_id"], rec["evaluator"], rec["service_name"], rec["source_arn"]),
                         ("s1", "Builtin.Correctness", SERVICE, CFG_ARN))
        self.assertTrue(rec["evaluated_at"].startswith("2026-09-21"))

    def test_score_value_must_be_a_real_number(self):
        records = evals.parse_result_records([
            _result_event("s1", "t1", "A", True),
            _result_event("s1", "t1", "B", "0.9"),
            _result_event("s1", "t1", "C", 3),
        ])
        self.assertEqual([r["value"] for r in records], [None, None, 3.0])

    def test_group_by_trace_merges_evaluators_newest_first(self):
        events = [
            _result_event("s1", "t1", "Builtin.Helpfulness", 0.5, observed_ns=1_790_000_000_000_000_000),
            _result_event("s1", "t1", "Builtin.Correctness", 1.0, observed_ns=1_790_000_000_000_000_000),
            _result_event("s2", "t2", "Builtin.Correctness", None, label="Error", observed_ns=1_790_000_100_000_000_000),
        ]
        grouped = evals.group_by_trace(evals.parse_result_records(events))
        self.assertEqual([g["trace_id"] for g in grouped], ["t2", "t1"])
        self.assertEqual([s["evaluator"] for s in grouped[1]["scores"]],
                         ["Builtin.Correctness", "Builtin.Helpfulness"])


# ---------------------------------------------------------------------------
# Scoping: which sources belong to the agent, and which records
# ---------------------------------------------------------------------------

class TestSourceScope(unittest.TestCase):

    def test_exclusive_source_matches_without_service_filter(self):
        scope = evals.online_config_scope(_online_config(groups=[LOG_GROUP]), TARGET)
        self.assertTrue(scope.matches)
        self.assertIsNone(scope.service_filter)

    def test_shared_source_matches_only_with_the_agents_service_name(self):
        shared = _online_config(groups=[LOG_GROUP, OTHER_GROUP], services=[SERVICE, "other_agent.DEFAULT"])
        scope = evals.online_config_scope(shared, TARGET)
        self.assertTrue(scope.matches)
        self.assertEqual(scope.service_filter, frozenset({SERVICE}))
        not_ours = _online_config(groups=[LOG_GROUP, OTHER_GROUP], services=["other_agent.DEFAULT"])
        self.assertFalse(evals.online_config_scope(not_ours, TARGET).matches)

    def test_prefix_source_is_shared_and_needs_the_service_name(self):
        prefixed = _online_config(prefixes=["/aws/bedrock-agentcore/runtimes/"])
        scope = evals.online_config_scope(prefixed, TARGET)
        self.assertTrue(scope.matches)
        self.assertEqual(scope.service_filter, frozenset({SERVICE}))
        other = _online_config(prefixes=["/aws/bedrock-agentcore/runtimes/"], services=["other_agent.DEFAULT"])
        self.assertFalse(evals.online_config_scope(other, TARGET).matches)

    def test_service_names_only_source_matches(self):
        scope = evals.online_config_scope(_online_config(services=[SERVICE]), TARGET)
        self.assertTrue(scope.matches)
        self.assertEqual(scope.service_filter, frozenset({SERVICE}))

    def test_unrelated_source_does_not_match(self):
        unrelated = _online_config(groups=[OTHER_GROUP], services=["other_agent.DEFAULT"])
        self.assertFalse(evals.online_config_scope(unrelated, TARGET).matches)

    def test_batch_run_scoped_through_its_parent_online_config(self):
        run = {"dataSourceConfig": {"onlineEvaluationConfigSource": {"onlineEvaluationConfigArn": "arn:cfg"}}}
        ours = evals.SourceScope(True, None, frozenset({LOG_GROUP}))
        self.assertTrue(evals.batch_run_scope(run, TARGET, {"arn:cfg": ours}).matches)
        self.assertFalse(evals.batch_run_scope(run, TARGET, {}).matches)

    def test_filter_records_drops_other_agents_and_other_sources(self):
        records = evals.parse_result_records([
            _result_event("mine", "t1", "A", 1.0),
            _result_event("theirs", "t2", "A", 1.0, service="other_agent.DEFAULT"),
            _result_event("other-cfg", "t3", "A", 1.0, source_arn=CFG_ARN.replace("cfg-1", "cfg-2")),
            _result_event("no-arn", "t4", "A", 1.0, source_arn=None),
        ])
        loc = evals.ResultsLocation(frozenset({"/g"}), None, frozenset({SERVICE}), CFG_ARN)
        self.assertEqual([r["session_id"] for r in evals.filter_records(records, loc)], ["mine", "no-arn"])


class TestResultsLocation(unittest.TestCase):

    def test_dedicated_default_group_is_derived_when_not_set(self):
        detail = _online_config(groups=[LOG_GROUP])
        loc = evals.online_results_location(detail, evals.online_config_scope(detail, TARGET))
        self.assertEqual(loc.groups, frozenset({"/aws/bedrock-agentcore/evaluations/results/cfg-1"}))

    def test_source_log_group_destination_reads_the_agents_own_groups(self):
        detail = _online_config(groups=[LOG_GROUP, OTHER_GROUP], services=[SERVICE],
                                output={"resultDestination": "SOURCE_LOG_GROUP"})
        loc = evals.online_results_location(detail, evals.online_config_scope(detail, TARGET))
        self.assertEqual(loc.groups, frozenset({LOG_GROUP}))
        self.assertIsNone(loc.service_filter)  # the agent's own group only holds its results

    def test_batch_run_in_source_group_is_bounded_by_its_run_time(self):
        created = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
        detail = {"batchEvaluationArn": RUN_ARN, "createdAt": created, "updatedAt": created,
                  "dataSourceConfig": {"cloudWatchLogs": {"logGroupNames": [LOG_GROUP]}},
                  "outputConfig": {"cloudWatchConfig": {"resultDestination": "SOURCE_LOG_GROUP"}}}
        loc = evals.batch_results_location(detail, evals.batch_run_scope(detail, TARGET, {}))
        start, end = loc.time_range_ms
        self.assertLess(start, int(created.timestamp() * 1000))
        self.assertGreater(end, int(created.timestamp() * 1000))
        self.assertEqual(loc.source_arn, RUN_ARN)


# ---------------------------------------------------------------------------
# Reading logs
# ---------------------------------------------------------------------------

class TestReadRecent(unittest.TestCase):
    DAY = evals.DAY_MS
    NOW = 100 * evals.DAY_MS

    def _ev(self, ms: int) -> dict:
        return {"timestamp": ms, "message": "{}"}

    def test_keeps_the_newest_events_when_capped(self):
        events = [self._ev(self.NOW - d * self.DAY - 1000) for d in (0, 1, 2)]  # today, -1d, -2d
        logs = _FakeLogs({"/g": events})
        kept, _ = evals._read_recent(logs, ["/g"], self.NOW - 3 * self.DAY, self.NOW, cap=2)
        self.assertEqual([e["timestamp"] for e in kept], sorted(e["timestamp"] for e in events)[-2:])

    def test_older_window_overflow_trims_the_oldest(self):
        today = self._ev(self.NOW - 1000)
        yesterday = [self._ev(self.NOW - self.DAY - 2000), self._ev(self.NOW - self.DAY - 1000)]
        kept, truncated = evals._read_recent(_FakeLogs({"/g": [today, *yesterday]}), ["/g"],
                                             self.NOW - 3 * self.DAY, self.NOW, cap=2)
        self.assertEqual([e["timestamp"] for e in kept], [yesterday[1]["timestamp"], today["timestamp"]])
        self.assertTrue(truncated)

    def test_keeps_the_newest_within_one_crowded_window(self):
        events = [self._ev(self.NOW - 5000 + i) for i in range(5)]
        kept, truncated = evals._read_recent(_FakeLogs({"/g": events}), ["/g"], self.NOW - self.DAY, self.NOW, cap=2)
        self.assertEqual([e["timestamp"] for e in kept], [self.NOW - 4997, self.NOW - 4996])
        self.assertTrue(truncated)

    def test_passes_the_result_filter_pattern(self):
        logs = _FakeLogs({"/g": [self._ev(self.NOW - 10)]})
        evals._read_recent(logs, ["/g"], self.NOW - self.DAY, self.NOW)
        self.assertEqual(logs.calls[0]["filterPattern"], evals.RESULT_FILTER_PATTERN)

    def test_missing_log_group_is_empty_not_an_error(self):
        kept, truncated = evals._read_recent(_FakeLogs({}, missing={"/gone"}), ["/gone"],
                                             self.NOW - self.DAY, self.NOW)
        self.assertEqual((kept, truncated), ([], False))

    def test_page_budget_stops_the_scan(self):
        events = [self._ev(self.NOW - 1000 + i) for i in range(50)]
        with patch.object(evals, "MAX_PAGES", 3):
            kept, truncated = evals._read_recent(_FakeLogs({"/g": events}, page_size=2), ["/g"],
                                                 self.NOW - self.DAY, self.NOW)
        self.assertTrue(truncated)
        self.assertLessEqual(len(kept), 6)


class TestReadStreamAndNewest(unittest.TestCase):

    def test_stream_stops_when_the_token_repeats(self):
        logs = MagicMock()
        logs.get_log_events.side_effect = [
            {"events": [{"timestamp": 1}], "nextForwardToken": "f/1"},
            {"events": [{"timestamp": 2}], "nextForwardToken": "f/2"},
            {"events": [], "nextForwardToken": "f/2"},
        ]
        events, truncated = evals._read_stream(logs, "/g", "s")
        self.assertEqual([e["timestamp"] for e in events], [1, 2])
        self.assertFalse(truncated)

    def test_missing_stream_is_empty(self):
        logs = MagicMock()
        logs.get_log_events.side_effect = _not_found("GetLogEvents")
        self.assertEqual(evals._read_stream(logs, "/g", "s"), ([], False))

    def test_newest_event_uses_the_last_event_not_the_stale_stream_stamp(self):
        logs = MagicMock()
        logs.describe_log_streams.return_value = {"logStreams": [{"logStreamName": "s", "lastEventTimestamp": 10}]}
        logs.get_log_events.return_value = {"events": [{"timestamp": 42}]}
        self.assertEqual(evals._newest_event_ms(logs, "/g"), 42)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery(unittest.TestCase):

    def _session(self, configs, runs):
        control, data, logs = MagicMock(), MagicMock(), MagicMock()
        control.list_online_evaluation_configs.return_value = {
            "onlineEvaluationConfigs": [{"onlineEvaluationConfigId": c["onlineEvaluationConfigId"]} for c in configs]}
        control.get_online_evaluation_config.side_effect = lambda onlineEvaluationConfigId: next(
            c for c in configs if c["onlineEvaluationConfigId"] == onlineEvaluationConfigId)
        data.list_batch_evaluations.return_value = {"batchEvaluations": [
            {"batchEvaluationId": r["batchEvaluationId"], "createdAt": datetime(2026, 9, 24, tzinfo=timezone.utc)}
            for r in runs]}

        def get_run(batchEvaluationId):
            run = next(r for r in runs if r["batchEvaluationId"] == batchEvaluationId)
            if run.get("_gone"):
                raise _not_found("GetBatchEvaluation")
            return run
        data.get_batch_evaluation.side_effect = get_run
        logs.describe_log_streams.return_value = {"logStreams": []}
        session = MagicMock()
        session.client.side_effect = {"bedrock-agentcore-control": control, "bedrock-agentcore": data,
                                      "logs": logs}.__getitem__
        return session

    def test_lists_only_matching_sources_and_skips_vanished_runs(self):
        configs = [_online_config(groups=[LOG_GROUP]), _online_config(groups=[OTHER_GROUP],
                                                                      services=["other_agent.DEFAULT"],
                                                                      config_id="cfg-2")]
        runs = [{"batchEvaluationId": "run-ok", "status": "COMPLETED",
                 "dataSourceConfig": {"cloudWatchLogs": {"logGroupNames": [LOG_GROUP]}}},
                {"batchEvaluationId": "run-gone", "_gone": True}]
        with patch("app.services.evaluations.boto3.Session", return_value=self._session(configs, runs)):
            sources = evals.discover_sources(TARGET, "us-east-1")
        self.assertEqual([c["id"] for c in sources["online"]], ["cfg-1"])
        self.assertEqual([b["id"] for b in sources["batch"]], ["run-ok"])

    def test_other_aws_errors_propagate(self):
        session = self._session([_online_config(groups=[LOG_GROUP])], [])
        denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Get")
        session.client("bedrock-agentcore-control").get_online_evaluation_config.side_effect = denied
        with patch("app.services.evaluations.boto3.Session", return_value=session):
            with self.assertRaises(ClientError):
                evals.discover_sources(TARGET, "us-east-1")


# ---------------------------------------------------------------------------
# Evaluated exchange
# ---------------------------------------------------------------------------

class TestExchangeExtraction(unittest.TestCase):

    @staticmethod
    def _otel(body: dict, ts: int = 0) -> dict:
        return {"timestamp": ts, "message": json.dumps({"body": body})}

    @staticmethod
    def _user(text: str) -> dict:
        return {"input": {"messages": [{"role": "user", "content": {"content": json.dumps([{"text": text}])}}]}}

    def test_extracts_last_user_prompt_and_last_assistant_answer(self):
        events = [
            self._otel({"input": {"messages": [
                {"role": "system", "content": {"content": json.dumps([{"text": "You are helpful."}])}}]}}, 1),
            self._otel(self._user("Earlier turn (history)"), 2),
            self._otel(self._user("How much is a kWh?"), 3),
            self._otel({"input": {"messages": [{"role": "user", "content": {"content": json.dumps(
                [{"toolResult": {"content": [{"text": "tool output"}]}}])}}]}}, 4),
            self._otel({"message": {"role": "assistant", "content": [{"text": "Draft answer"}]}}, 5),
            self._otel({"message": {"role": "assistant", "content": [{"text": "Final answer"}]}}, 6),
        ]
        self.assertEqual(evals.extract_exchange(events),
                         {"prompt": "How much is a kWh?", "answer": "Final answer"})

    def test_out_of_order_events_are_sorted_by_time(self):
        events = [
            self._otel({"message": {"role": "assistant", "content": [{"text": "Final"}]}}, 9),
            self._otel({"message": {"role": "assistant", "content": [{"text": "Draft"}]}}, 5),
        ]
        self.assertEqual(evals.extract_exchange(events)["answer"], "Final")

    def test_plain_string_content_and_unknown_shapes(self):
        plain = [self._otel({"input": {"messages": [{"role": "user", "content": {"content": "plain words"}}]}})]
        self.assertEqual(evals.extract_exchange(plain)["prompt"], "plain words")
        self.assertEqual(evals.extract_exchange([{"message": json.dumps({"body": "plain text log"})}]),
                         {"prompt": None, "answer": None})


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class TestEvaluationsRouter(unittest.TestCase):

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
        self.agent = Agent(arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test_agent-AbCdEf1234",
                           runtime_id="test_agent-AbCdEf1234", name="Test Agent", status="READY",
                           region="us-east-1", account_id="123456789012", log_group=LOG_GROUP)
        self.agent.set_available_qualifiers(["DEFAULT"])
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _as_user(self, groups: list[str]) -> None:
        user = UserInfo(sub="u", username="u", groups=groups, scopes=derive_scopes(groups))
        app.dependency_overrides[get_current_user] = lambda: user

    def test_agent_target_derives_log_groups_and_service_names(self):
        self.agent.set_available_qualifiers(["DEFAULT", "prod"])
        target = _agent_target(self.agent)
        self.assertEqual(target.service_names, frozenset({"test_agent.DEFAULT", "test_agent.prod"}))
        self.assertIn("/aws/bedrock-agentcore/runtimes/test_agent-AbCdEf1234-prod", target.log_groups)

    @patch("app.routers.evaluations.evals.discover_sources")
    def test_overview_passes_the_agent_target(self, mock_discover):
        mock_discover.return_value = {"online": [], "batch": []}
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"online": [], "batch": []})
        self.assertEqual(mock_discover.call_args.args[0], TARGET)

    def test_overview_unknown_agent_is_404(self):
        self.assertEqual(self.client.get("/api/agents/9999/evaluations").status_code, 404)

    @patch("app.routers.evaluations.evals.discover_sources")
    def test_overview_aws_failure_is_502(self, mock_discover):
        mock_discover.side_effect = ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "x"}}, "List")
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations")
        self.assertEqual(resp.status_code, 502)
        self.assertIn("ExpiredTokenException", resp.json()["detail"])

    @patch("app.routers.evaluations.evals.discover_sources")
    def test_user_outside_the_agents_group_is_refused(self, mock_discover):
        self.agent.tags = json.dumps({"loom:group": "strategics"})
        self.session.commit()
        self._as_user(["t-user", "g-users-demo"])
        for path in ("evaluations", "evaluations/results?source_type=online&source_id=cfg-1",
                     "evaluations/traces/6aafd89d0c3d93ed486af0510926c6c1/exchange"):
            self.assertEqual(self.client.get(f"/api/agents/{self.agent.id}/{path}").status_code, 403, path)
        mock_discover.assert_not_called()

    @patch("app.routers.evaluations.evals.read_results")
    @patch("app.routers.evaluations.evals.resolve_results_location")
    def test_results_are_grouped_per_trace(self, mock_resolve, mock_read):
        mock_resolve.return_value = evals.ResultsLocation(frozenset({"/g"}), None, None, None)
        mock_read.return_value = (evals.parse_result_records([_result_event("s1", "t1", "A", 1.0)]), True)
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/results",
                               params={"source_type": "online", "source_id": "cfg-1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"][0]["session_id"], "s1")
        self.assertTrue(resp.json()["truncated"])

    @patch("app.routers.evaluations.evals.read_results")
    @patch("app.routers.evaluations.evals.resolve_results_location")
    def test_another_agents_source_is_404_without_reading_logs(self, mock_resolve, mock_read):
        mock_resolve.return_value = None
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/results",
                               params={"source_type": "online", "source_id": "someone-else"})
        self.assertEqual(resp.status_code, 404)
        mock_read.assert_not_called()

    @patch("app.routers.evaluations.evals.resolve_results_location")
    def test_aws_validation_error_on_source_is_404(self, mock_resolve):
        mock_resolve.side_effect = ClientError({"Error": {"Code": "ValidationException", "Message": "bad"}}, "Get")
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/results",
                               params={"source_type": "batch", "source_id": "run-1"})
        self.assertEqual(resp.status_code, 404)

    @patch("app.routers.evaluations.evals.resolve_results_location")
    def test_rejects_bad_query_values_before_any_aws_call(self, mock_resolve):
        cases = [
            {"source_type": "logs", "source_id": "cfg-1"},
            {"source_type": "online", "source_id": "../../etc"},
            {"source_type": "online", "source_id": "a b"},
            {"source_type": "online", "source_id": "x" * 129},
            {"source_type": "online", "source_id": "cfg-1", "days": 0},
            {"source_type": "online", "source_id": "cfg-1", "days": 31},
        ]
        for params in cases:
            resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/results", params=params)
            self.assertEqual(resp.status_code, 422, params)
        mock_resolve.assert_not_called()

    @patch("app.routers.evaluations.fetch_otel_events")
    def test_exchange_rejects_non_hex_trace_id(self, mock_fetch):
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/traces/abc%22%20OR/exchange")
        self.assertEqual(resp.status_code, 422)
        mock_fetch.assert_not_called()

    @patch("app.routers.evaluations.fetch_otel_events")
    def test_exchange_returns_prompt_and_answer(self, mock_fetch):
        mock_fetch.return_value = [
            {"message": json.dumps({"body": {"input": {"messages": [
                {"role": "user", "content": {"content": json.dumps([{"text": "Hi"}])}}]}}})},
            {"message": json.dumps({"body": {"message": {"role": "assistant", "content": [{"text": "Hello"}]}}})},
        ]
        trace_id = "6aafd89d0c3d93ed486af0510926c6c1"
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/traces/{trace_id}/exchange")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"prompt": "Hi", "answer": "Hello"})
        self.assertEqual(mock_fetch.call_args.kwargs["filter_pattern"], f'"{trace_id}"')

    @patch("app.routers.evaluations.fetch_otel_events")
    def test_exchange_for_unknown_trace_is_empty(self, mock_fetch):
        mock_fetch.return_value = []
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/traces/{'a' * 32}/exchange")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"prompt": None, "answer": None})


if __name__ == "__main__":
    unittest.main()

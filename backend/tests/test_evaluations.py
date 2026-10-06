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
from app.models.evaluation import EvaluationTestCase, EvaluationRun
from app.models.invocation import Invocation
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


class TestFetchSessionSpans(unittest.TestCase):
    """On-demand evaluation needs the actual span bodies, downloaded via a
    Logs Insights query scoped to the session — not just a presence check."""

    def _query_result(self, spans: list[dict]) -> dict:
        return {
            "status": "Complete",
            "results": [
                [{"field": "@timestamp", "value": "t"}, {"field": "@message", "value": json.dumps(s)}]
                for s in spans
            ],
        }

    @patch("boto3.client")
    def test_parses_message_field_from_each_result_row(self, mock_boto_client):
        logs = MagicMock()
        mock_boto_client.return_value = logs
        logs.start_query.return_value = {"queryId": "q1"}
        span = {"name": "invoke_agent Strands Agents", "attributes": {"session.id": "s1"}}
        logs.get_query_results.return_value = self._query_result([span])
        result = evals.fetch_session_spans("/g", "s1", "us-east-1")
        self.assertEqual(result, [span])
        self.assertIn("s1", logs.start_query.call_args.kwargs["queryString"])

    @patch("boto3.client")
    def test_missing_log_group_is_empty_not_an_error(self, mock_boto_client):
        logs = MagicMock()
        mock_boto_client.return_value = logs
        logs.start_query.side_effect = _not_found("StartQuery")
        self.assertEqual(evals.fetch_session_spans("/g", "s1", "us-east-1"), [])

    @patch("boto3.client")
    def test_query_still_running_after_poll_budget_is_empty(self, mock_boto_client):
        logs = MagicMock()
        mock_boto_client.return_value = logs
        logs.start_query.return_value = {"queryId": "q1"}
        logs.get_query_results.return_value = {"status": "Running"}
        with patch("app.services.evaluations.time.sleep"):
            self.assertEqual(evals.fetch_session_spans("/g", "s1", "us-east-1"), [])


def _span(name: str, scope: str = "strands.telemetry.tracer") -> dict:
    return {"name": name, "scope": {"name": scope}}


class TestWaitForSessionSpans(unittest.TestCase):
    """Caller-controlled replacement for batch evaluation's internal (and
    apparently too-short) span lookup — retries with mild backoff, and only
    accepts a result once two consecutive polls see the same span count AND
    at least one span carries a scope AgentCore's evaluators can read (spans
    land incrementally and out of evaluator-relevant order, so a stable
    non-empty result can still be an unevaluatable one)."""

    @patch("app.services.evaluations.time.sleep")
    @patch("app.services.evaluations.fetch_session_spans")
    def test_waits_for_the_count_to_stop_growing_before_returning(self, mock_fetch, mock_sleep):
        # First poll sees only the top-level span; second poll sees the full
        # trace (now stable); result must be the stable (3-span) one, not
        # the first non-empty (1-span) one.
        full = [_span("a"), _span("b"), _span("c")]
        mock_fetch.side_effect = [[_span("invoke_agent")], full, full]
        result = evals.wait_for_session_spans("/g", "s1", "us-east-1", timeout_s=5, interval_s=0.01)
        self.assertEqual(len(result), 3)
        self.assertEqual(mock_fetch.call_count, 3)

    @patch("app.services.evaluations.time.sleep")
    @patch("app.services.evaluations.fetch_session_spans")
    def test_keeps_waiting_while_only_unsupported_scopes_have_landed(self, mock_fetch, mock_sleep):
        # The HTTP/AWS-SDK spans flush first and can sit at a stable count for
        # a poll or two before the framework spans Evaluate actually reads
        # arrive. Returning there is what produced AgentCore's "no spans with
        # supported scope" ValidationException, so a stable-but-unevaluatable
        # set must not be accepted.
        early = [_span("POST /invocations", scope="opentelemetry.instrumentation.starlette")]
        ready = early + [_span("invoke_agent Strands Agents")]
        mock_fetch.side_effect = [early, early, ready, ready]
        result = evals.wait_for_session_spans("/g", "s1", "us-east-1", timeout_s=5, interval_s=0.01)
        self.assertTrue(evals._has_evaluatable_span(result))
        self.assertEqual(len(result), 2)

    @patch("app.services.evaluations.time.sleep")
    @patch("app.services.evaluations.fetch_session_spans")
    def test_retries_until_timeout_then_gives_up(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = []
        result = evals.wait_for_session_spans("/g", "s1", "us-east-1", timeout_s=0.03, interval_s=0.01)
        self.assertEqual(result, [])
        self.assertGreater(mock_fetch.call_count, 1)

    @patch("app.services.evaluations.time.sleep")
    @patch("app.services.evaluations.fetch_session_spans")
    def test_returns_whatever_it_has_if_still_growing_at_timeout(self, mock_fetch, mock_sleep):
        # Spans never stabilize within the window — return the last (partial)
        # result instead of throwing it away, since on-demand evaluation can
        # still score with a partial trace for some evaluators.
        mock_fetch.side_effect = lambda *a, **kw: [_span("x")] * (mock_fetch.call_count)
        result = evals.wait_for_session_spans("/g", "s1", "us-east-1", timeout_s=0.03, interval_s=0.01)
        self.assertTrue(result)


class TestRunOnDemandEvaluation(unittest.TestCase):
    """Evaluate takes exactly one evaluatorId per call, unlike
    StartBatchEvaluation's list — so this calls it once per evaluator."""

    @patch("boto3.client")
    def test_calls_evaluate_once_per_evaluator_with_the_spans(self, mock_boto_client):
        client = MagicMock()
        mock_boto_client.return_value = client
        client.evaluate.side_effect = [
            {"evaluationResults": [{"evaluatorId": "Builtin.Helpfulness", "value": 0.9, "label": "Great", "explanation": "..."}]},
            {"evaluationResults": [{"evaluatorId": "Builtin.Correctness", "value": 0.8, "label": "Good", "explanation": "..."}]},
        ]
        spans = [{"name": "invoke_agent"}]
        scores, errors = evals.run_on_demand_evaluation(
            ["Builtin.Helpfulness", "Builtin.Correctness"], spans, "us-east-1",
        )
        self.assertEqual(client.evaluate.call_count, 2)
        self.assertEqual(client.evaluate.call_args_list[0].kwargs["evaluatorId"], "Builtin.Helpfulness")
        self.assertEqual(client.evaluate.call_args_list[0].kwargs["evaluationInput"], {"sessionSpans": spans})
        self.assertEqual(len(scores), 2)
        self.assertEqual(errors, [])

    @patch("boto3.client")
    def test_multiple_results_for_the_same_evaluator_are_averaged_into_one_score(self, mock_boto_client):
        """A trajectory/tool-use evaluator can return one evaluationResult per
        tool call rather than one for the whole session — those must collapse
        into a single score row, not be mistaken for extra evaluators."""
        client = MagicMock()
        mock_boto_client.return_value = client
        client.evaluate.return_value = {"evaluationResults": [
            {"evaluatorId": "Builtin.ToolSelectionAccuracy", "value": 1.0, "label": "Good", "explanation": "call 1"},
            {"evaluatorId": "Builtin.ToolSelectionAccuracy", "value": 0.0, "label": "Bad", "explanation": "call 2"},
        ]}
        scores, errors = evals.run_on_demand_evaluation(["Builtin.ToolSelectionAccuracy"], [{}], "us-east-1")
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0]["evaluator"], "Builtin.ToolSelectionAccuracy")
        self.assertEqual(scores[0]["value"], 0.5)
        self.assertEqual(errors, [])

    @patch("boto3.client")
    def test_per_result_error_message_goes_to_errors_not_scores(self, mock_boto_client):
        client = MagicMock()
        mock_boto_client.return_value = client
        client.evaluate.return_value = {"evaluationResults": [
            {"evaluatorId": "Builtin.Helpfulness", "errorMessage": "model timeout", "errorCode": "Timeout"},
        ]}
        scores, errors = evals.run_on_demand_evaluation(["Builtin.Helpfulness"], [{}], "us-east-1")
        self.assertEqual(scores, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("model timeout", errors[0])

    @patch("boto3.client")
    def test_one_evaluator_failing_does_not_stop_the_others(self, mock_boto_client):
        client = MagicMock()
        mock_boto_client.return_value = client
        client.evaluate.side_effect = [
            _not_found("Evaluate"),
            {"evaluationResults": [{"evaluatorId": "Builtin.Correctness", "value": 0.8}]},
        ]
        scores, errors = evals.run_on_demand_evaluation(
            ["Builtin.Helpfulness", "Builtin.Correctness"], [{}], "us-east-1",
        )
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0]["evaluator"], "Builtin.Correctness")
        self.assertEqual(len(errors), 1)


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


class TestEvaluationTestCases(unittest.TestCase):
    """Tests for saved test cases and running them (create -> invoke -> StartBatchEvaluation)."""

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
        self._as_admin()

        # _execute_run opens its own DB session (SessionLocal()) rather than
        # using the get_db dependency override above — without this, its
        # background task would hit the real app database instead of this
        # test's in-memory one (and silently operate on whatever agent
        # happens to share this test's agent id there).
        self.session_local_patcher = patch("app.routers.evaluations.SessionLocal", self.TestingSessionLocal)
        self.session_local_patcher.start()
        self.addCleanup(self.session_local_patcher.stop)

        # _execute_run (which /run and /rescore hand off to BackgroundTasks)
        # waits for spans itself; short-circuit it everywhere in this class to
        # "the spans landed immediately", so individual tests only need to
        # care about this when testing the wait itself. BackgroundTasks run
        # synchronously (and in-process) under TestClient, so by the time
        # self.client.post(...) returns, this has already run to completion —
        # tests check the final state via last-run, not the /run response
        # body (which is always PENDING, since it's built before the
        # background task starts).
        self.wait_patcher = patch("app.routers.evaluations.evals.wait_for_session_spans", return_value=[{"name": "invoke_agent"}])
        self.wait_patcher.start()
        self.addCleanup(self.wait_patcher.stop)

        # Default: one evaluator scores 0.9 — PASS. Tests that care about a
        # specific score, failure, or ERROR outcome override this per-test.
        eval_patcher = patch(
            "app.routers.evaluations.evals.run_on_demand_evaluation",
            return_value=([{"evaluator": "Builtin.Helpfulness", "value": 0.9, "label": "Great", "explanation": "ok", "level": None}], []),
        )
        eval_patcher.start()
        self.addCleanup(eval_patcher.stop)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def _as_admin(self) -> None:
        user = UserInfo(sub="u", username="u", groups=["t-admin", "g-admins-super"],
                        scopes=derive_scopes(["t-admin", "g-admins-super"]))
        app.dependency_overrides[get_current_user] = lambda: user

    def _as_read_only_user(self) -> None:
        user = UserInfo(sub="u2", username="u2", groups=["t-user", "g-users-demo"],
                        scopes=derive_scopes(["t-user", "g-users-demo"]))
        app.dependency_overrides[get_current_user] = lambda: user

    def _create_test_case(self, **overrides) -> dict:
        body = {
            "name": "Greets politely",
            "prompt": "Say hello",
            "evaluator_ids": ["Builtin.Helpfulness"],
        }
        body.update(overrides)
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases", json=body)
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    @patch("app.routers.evaluations.evals.list_evaluators")
    def test_list_evaluators(self, mock_list):
        mock_list.return_value = [{"id": "Builtin.Helpfulness", "name": "Helpfulness", "description": "d", "type": "Builtin", "group": "Response quality"}]
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/evaluators")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["id"], "Builtin.Helpfulness")

    def test_create_and_list_test_case(self):
        created = self._create_test_case()
        self.assertEqual(created["name"], "Greets politely")
        self.assertEqual(created["evaluator_ids"], ["Builtin.Helpfulness"])
        self.assertIsNone(created["last_batch_evaluation_id"])

        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_create_requires_at_least_one_evaluator(self):
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases", json={
            "name": "x", "prompt": "y", "evaluator_ids": [],
        })
        self.assertEqual(resp.status_code, 422)

    def test_update_test_case(self):
        created = self._create_test_case()
        resp = self.client.put(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}",
            json={"name": "Renamed", "prompt": "New prompt", "evaluator_ids": ["Builtin.Correctness"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Renamed")
        self.assertEqual(resp.json()["evaluator_ids"], ["Builtin.Correctness"])

    def test_update_unknown_test_case_is_404(self):
        resp = self.client.put(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/9999",
            json={"name": "x", "prompt": "y", "evaluator_ids": ["Builtin.Correctness"]},
        )
        self.assertEqual(resp.status_code, 404)

    def test_delete_test_case(self):
        created = self._create_test_case()
        resp = self.client.delete(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases").json(), [])

    def test_read_only_user_cannot_create_or_run(self):
        created = self._create_test_case()
        self._as_read_only_user()
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases", json={
            "name": "x", "prompt": "y", "evaluator_ids": ["Builtin.Correctness"],
        })
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        self.assertEqual(resp.status_code, 403)

    @patch("app.routers.evaluations.invoke_agent")
    def test_run_invokes_agent_then_evaluates_the_session(self, mock_invoke):
        mock_invoke.return_value = iter([
            {"type": "text", "content": "Hel"},
            {"type": "text", "content": "lo!"},
            {"type": "structured", "content": {"ignored": True}},
        ])
        created = self._create_test_case(expected_response="A friendly greeting")

        # /run returns almost immediately — the actual work happens in a
        # BackgroundTask, which TestClient runs synchronously before handing
        # back the response, so the DB already reflects the final state by
        # the time this call returns even though the response body itself
        # was built beforehand and is always PENDING/no agent_response.
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "PENDING")
        self.assertIsNone(body["agent_response"])

        # Invoked with this test case's own prompt against the agent's runtime.
        self.assertEqual(mock_invoke.call_args.kwargs["prompt"], "Say hello")
        self.assertEqual(mock_invoke.call_args.kwargs["arn"], self.agent.arn)

        # Spans were scored (setUp's run_on_demand_evaluation mock) and that
        # result is readable back for this test case.
        last_run = self.client.get(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/last-run"
        ).json()
        self.assertEqual(last_run["status"], "COMPLETED")
        self.assertTrue(last_run["scores"])

        # The agent's response was persisted as a real invocation.
        invocation = self.session.query(Invocation).filter(Invocation.session_id == last_run["session_id"]).first()
        self.assertEqual(invocation.response_text, "Hello!")

        # The test case remembers its latest run for the UI to link to.
        updated = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases").json()[0]
        self.assertIsNotNone(updated["last_batch_evaluation_id"])
        self.assertIsNotNone(updated["last_run_at"])

    @patch("app.routers.evaluations.invoke_agent")
    def test_run_invoke_failure_ends_the_run_as_error(self, mock_invoke):
        # The agent is invoked in the background now, so a failure there
        # can't 502 the (already-sent) /run response — it just means the run
        # ends up ERROR, readable back via last-run.
        mock_invoke.side_effect = Exception("runtime unreachable")
        created = self._create_test_case()
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        self.assertEqual(resp.status_code, 200, resp.text)
        last_run = self.client.get(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/last-run"
        ).json()
        self.assertEqual(last_run["status"], "ERROR")
        self.assertIn("runtime unreachable", last_run["errors"][0])

    @patch("app.routers.evaluations.invoke_agent")
    def test_run_with_no_scores_from_any_evaluator_is_error_not_a_502(self, mock_invoke):
        # On-demand evaluation never raises up to the endpoint for a scoring
        # failure — a per-evaluator error (or every evaluator failing) just
        # means the run has no scores. There's no AWS call left in /run that
        # can itself 502 the way StartBatchEvaluation could.
        mock_invoke.return_value = iter([])
        with patch("app.routers.evaluations.evals.run_on_demand_evaluation", return_value=([], ["No spans were found"])):
            created = self._create_test_case()
            resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        self.assertEqual(resp.status_code, 200, resp.text)
        last_run = self.client.get(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/last-run"
        ).json()
        self.assertEqual(last_run["status"], "ERROR")

    def test_run_unknown_test_case_is_404(self):
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/9999/run")
        self.assertEqual(resp.status_code, 404)

    def test_create_defaults_pass_threshold(self):
        created = self._create_test_case()
        self.assertEqual(created["pass_threshold"], 0.7)

    def test_create_defaults_model_id_to_none(self):
        created = self._create_test_case()
        self.assertIsNone(created["model_id"])

    def test_create_with_model_override(self):
        created = self._create_test_case(model_id="anthropic.claude-3-5-sonnet")
        self.assertEqual(created["model_id"], "anthropic.claude-3-5-sonnet")

    @patch("app.routers.evaluations.invoke_agent")
    def test_run_passes_model_override_to_invoke(self, mock_invoke):
        mock_invoke.return_value = iter([])
        created = self._create_test_case(model_id="anthropic.claude-3-5-sonnet")
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_invoke.call_args.kwargs["runtime_model_id"], "anthropic.claude-3-5-sonnet")

    def test_create_with_custom_pass_threshold(self):
        created = self._create_test_case(pass_threshold=0.9)
        self.assertEqual(created["pass_threshold"], 0.9)

    @patch("app.routers.evaluations.invoke_agent")
    def test_run_without_authorizer_passes_no_access_token(self, mock_invoke):
        mock_invoke.return_value = iter([])
        created = self._create_test_case()
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(mock_invoke.call_args.kwargs["access_token"])

    @patch("app.routers.evaluations.invoke_agent")
    def test_run_with_authorizer_forwards_caller_bearer_token(self, mock_invoke):
        self.agent.set_authorizer_config({"type": "cognito", "pool_id": "us-east-1_test"})
        self.session.commit()
        mock_invoke.return_value = iter([])
        created = self._create_test_case()
        resp = self.client.post(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run",
            headers={"Authorization": "Bearer my-test-token"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_invoke.call_args.kwargs["access_token"], "my-test-token")

    @patch("app.routers.evaluations.get_cognito_token")
    @patch("app.routers.evaluations.invoke_agent")
    def test_run_with_authorizer_falls_back_to_agent_m2m_credentials(self, mock_invoke, mock_token):
        self.agent.set_authorizer_config({"type": "cognito", "pool_id": "us-east-1_test"})
        self.session.commit()
        from app.models.config_entry import ConfigEntry
        self.session.add(ConfigEntry(agent_id=self.agent.id, key="COGNITO_CLIENT_ID", value="client-123"))
        self.session.add(ConfigEntry(agent_id=self.agent.id, key="COGNITO_CLIENT_SECRET_ARN", value="arn:aws:secretsmanager:us-east-1:123456789012:secret:x"))
        self.session.commit()
        mock_token.return_value = {"access_token": "m2m-token"}
        mock_invoke.return_value = iter([])
        created = self._create_test_case()

        with patch("app.routers.evaluations.get_secret", return_value="shh"):
            resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_invoke.call_args.kwargs["access_token"], "m2m-token")

    @patch("app.routers.evaluations.invoke_agent")
    def test_rescore_reuses_session_without_invoking_agent(self, mock_invoke):
        created = self._create_test_case()
        first = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        self.assertEqual(first.status_code, 200, first.text)
        first_run_id = first.json()["batch_evaluation_id"]
        mock_invoke.reset_mock()

        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/rescore")

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotEqual(resp.json()["batch_evaluation_id"], first_run_id)  # a new EvaluationRun row
        mock_invoke.assert_not_called()  # no re-invocation — same session rescored

        listed = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases").json()
        updated = next(tc for tc in listed if tc["id"] == created["id"])
        self.assertEqual(updated["last_batch_evaluation_id"], resp.json()["batch_evaluation_id"])

    def test_rescore_without_prior_run_is_400(self):
        created = self._create_test_case()
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/rescore")
        self.assertEqual(resp.status_code, 400)

    def test_pass_threshold_out_of_range_is_422(self):
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases", json={
            "name": "x", "prompt": "y", "evaluator_ids": ["Builtin.Correctness"], "pass_threshold": 1.5,
        })
        self.assertEqual(resp.status_code, 422)

    def test_last_run_with_no_run_yet_is_empty(self):
        created = self._create_test_case()
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/last-run")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": None, "scores": [], "errors": [], "session_id": None})

    @patch("app.routers.evaluations.invoke_agent")
    def test_last_run_returns_status_and_scores(self, mock_invoke):
        mock_invoke.return_value = iter([])
        with patch(
            "app.routers.evaluations.evals.run_on_demand_evaluation",
            return_value=([{"evaluator": "Builtin.Helpfulness", "value": 0.9, "label": "Good", "explanation": "e", "level": None}], []),
        ):
            created = self._create_test_case()
            self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")

        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/last-run")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "COMPLETED")
        self.assertEqual(resp.json()["scores"][0]["evaluator"], "Builtin.Helpfulness")
        self.assertTrue(resp.json()["session_id"])

    @patch("app.routers.evaluations.invoke_agent")
    def test_run_ends_as_error_when_spans_never_show_up(self, mock_invoke):
        mock_invoke.return_value = iter([])
        with patch("app.routers.evaluations.evals.wait_for_session_spans", return_value=[]) as mock_wait:
            created = self._create_test_case()
            resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "PENDING")  # response is built before the background task runs
        mock_wait.assert_called_once()
        last_run = self.client.get(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/last-run"
        ).json()
        self.assertEqual(last_run["status"], "ERROR")
        self.assertIn("No trace spans", last_run["errors"][0])

    def test_last_run_unknown_test_case_is_404(self):
        resp = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases/9999/last-run")
        self.assertEqual(resp.status_code, 404)


class TestExecuteRun(unittest.TestCase):
    """_execute_run is the BackgroundTask /run and /rescore hand everything
    off to — it opens its own DB session (SessionLocal), so these patch that
    to the test's in-memory engine rather than going through the FastAPI
    dependency override the HTTP-level tests use."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        self.session = self.TestingSessionLocal()
        self.agent = Agent(arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test_agent-AbCdEf1234",
                           runtime_id="test_agent-AbCdEf1234", name="Test Agent", status="READY",
                           region="us-east-1", account_id="123456789012", log_group=LOG_GROUP)
        self.agent.set_available_qualifiers(["DEFAULT"])
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.agent)
        self.tc = EvaluationTestCase(agent_id=self.agent.id, name="t", prompt="p")
        self.tc.set_evaluator_ids(["Builtin.Helpfulness"])
        self.session.add(self.tc)
        self.session.commit()
        self.session.refresh(self.tc)
        self.run = EvaluationRun(test_case_id=self.tc.id, session_id="s1", status="PENDING")
        self.session.add(self.run)
        self.session.commit()
        self.session.refresh(self.run)

        self.session_local_patcher = patch("app.routers.evaluations.SessionLocal", self.TestingSessionLocal)
        self.session_local_patcher.start()

    def tearDown(self):
        self.session_local_patcher.stop()
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @patch("app.routers.evaluations.evals.run_on_demand_evaluation")
    @patch("app.routers.evaluations.evals.wait_for_session_spans")
    def test_moves_through_phases_and_completes(self, mock_wait, mock_evaluate):
        mock_wait.return_value = [{"name": "invoke_agent"}]
        mock_evaluate.return_value = ([{"evaluator": "Builtin.Helpfulness", "value": 0.9, "label": None, "explanation": None, "level": None}], [])
        from app.routers.evaluations import _execute_run
        # prompt=None skips invocation, as a rescore would.
        _execute_run(self.run.id, self.tc.id, self.agent.id, "s1", None, None, None, None)
        mock_wait.assert_called_once()
        self.session.expire_all()
        updated = self.session.query(EvaluationRun).filter_by(id=self.run.id).first()
        self.assertEqual(updated.status, "COMPLETED")
        self.assertEqual(updated.get_results()[0]["evaluator"], "Builtin.Helpfulness")

    @patch("app.routers.evaluations.evals.wait_for_session_spans")
    def test_no_spans_ends_as_error(self, mock_wait):
        mock_wait.return_value = []
        from app.routers.evaluations import _execute_run
        _execute_run(self.run.id, self.tc.id, self.agent.id, "s1", None, None, None, None)
        self.session.expire_all()
        updated = self.session.query(EvaluationRun).filter_by(id=self.run.id).first()
        self.assertEqual(updated.status, "ERROR")
        self.assertTrue(updated.get_errors())

    @patch("app.routers.evaluations.invoke_agent")
    def test_invoke_failure_ends_as_error_without_waiting_for_spans(self, mock_invoke):
        mock_invoke.side_effect = Exception("runtime unreachable")
        from app.routers.evaluations import _execute_run
        _execute_run(self.run.id, self.tc.id, self.agent.id, "s1", "say hi", None, None, "u")
        self.session.expire_all()
        updated = self.session.query(EvaluationRun).filter_by(id=self.run.id).first()
        self.assertEqual(updated.status, "ERROR")
        self.assertIn("runtime unreachable", updated.get_errors()[0])

    def test_missing_run_returns_quietly(self):
        from app.routers.evaluations import _execute_run
        _execute_run(999999, self.tc.id, self.agent.id, "s1", None, None, None, None)  # must not raise


class TestFinishEvaluationRun(unittest.TestCase):
    """Status logic: COMPLETED needs at least one real score; a per-evaluator
    error alone (with no scores at all) is ERROR."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        self.session = self.TestingSessionLocal()
        agent = Agent(arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test_agent-AbCdEf1234",
                     runtime_id="test_agent-AbCdEf1234", name="Test Agent", status="READY",
                     region="us-east-1", account_id="123456789012", log_group=LOG_GROUP)
        agent.set_available_qualifiers(["DEFAULT"])
        self.session.add(agent)
        self.session.commit()
        self.tc = EvaluationTestCase(agent_id=agent.id, name="t", prompt="p")
        self.tc.set_evaluator_ids(["Builtin.Helpfulness"])
        self.session.add(self.tc)
        self.session.commit()
        self.run = EvaluationRun(test_case_id=self.tc.id, session_id="s1", status="PENDING")
        self.session.add(self.run)
        self.session.commit()

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @patch("app.routers.evaluations.evals.run_on_demand_evaluation")
    def test_one_score_is_completed_but_keeps_the_other_evaluators_errors(self, mock_evaluate):
        mock_evaluate.return_value = ([{"evaluator": "Builtin.Helpfulness", "value": 0.9, "label": None, "explanation": None, "level": None}], ["Builtin.Correctness: timeout"])
        from app.routers.evaluations import _finish_evaluation_run
        _finish_evaluation_run(self.session, self.run, self.tc, [{"name": "invoke_agent"}], "us-east-1")
        self.assertEqual(self.run.status, "COMPLETED")
        # Kept, not discarded — a run that scored with one evaluator but
        # silently failed on others used to look like a clean result.
        self.assertEqual(self.run.get_errors(), ["Builtin.Correctness: timeout"])

    @patch("app.routers.evaluations.evals.run_on_demand_evaluation")
    def test_zero_scores_is_error(self, mock_evaluate):
        mock_evaluate.return_value = ([], ["No spans were found"])
        from app.routers.evaluations import _finish_evaluation_run
        _finish_evaluation_run(self.session, self.run, self.tc, [{"name": "invoke_agent"}], "us-east-1")
        self.assertEqual(self.run.status, "ERROR")
        self.assertEqual(self.run.get_errors(), ["No spans were found"])


class TestEvaluatorGroups(unittest.TestCase):
    """Tests for the evaluator category grouping used by the picker UI."""

    def test_every_real_evaluator_id_maps_to_a_named_group(self):
        all_ids = [eid for _, ids in evals.EVALUATOR_GROUPS for eid in ids]
        self.assertEqual(len(all_ids), len(set(all_ids)), "an evaluator ID appears in more than one group")
        self.assertIn("Builtin.Helpfulness", all_ids)
        self.assertIn("ThirdParty.DeepEval.Bias", all_ids)

    @patch("app.services.evaluations._paginate")
    @patch("boto3.client")
    def test_list_evaluators_tags_group_and_falls_back_to_other(self, mock_boto_client, mock_paginate):
        mock_paginate.return_value = [
            {"evaluatorId": "Builtin.Helpfulness", "evaluatorName": "Helpfulness", "status": "ACTIVE", "evaluatorType": "Builtin"},
            {"evaluatorId": "Custom.my-eval", "evaluatorName": None, "status": "ACTIVE", "evaluatorType": "Custom"},
            {"evaluatorId": "Builtin.Disabled", "status": "DISABLED"},
        ]
        result = evals.list_evaluators("us-east-1")
        self.assertEqual(len(result), 2)  # the DISABLED one is excluded
        self.assertEqual(result[0]["group"], "Response quality")
        self.assertEqual(result[1]["group"], "Other")
        self.assertEqual(result[1]["name"], "my-eval")  # falls back to the short ID when evaluatorName is absent

    @patch("app.services.evaluations._paginate")
    @patch("boto3.client")
    def test_list_evaluators_excludes_third_party(self, mock_boto_client, mock_paginate):
        mock_paginate.return_value = [
            {"evaluatorId": "Builtin.Helpfulness", "evaluatorName": "Helpfulness", "status": "ACTIVE", "evaluatorType": "Builtin"},
            {"evaluatorId": "ThirdParty.DeepEval.Bias", "evaluatorName": "Bias", "status": "ACTIVE", "evaluatorType": "ThirdParty"},
            {"evaluatorId": "Custom.my-eval", "evaluatorName": None, "status": "ACTIVE", "evaluatorType": "Custom"},
        ]
        result = evals.list_evaluators("us-east-1")
        ids = [e["id"] for e in result]
        self.assertIn("Builtin.Helpfulness", ids)
        self.assertIn("Custom.my-eval", ids)
        self.assertNotIn("ThirdParty.DeepEval.Bias", ids)


if __name__ == "__main__":
    unittest.main()

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
ADMIN = UserInfo(sub="u", username="u", groups=["t-admin", "g-admins-super"],
                 scopes=derive_scopes(["t-admin", "g-admins-super"]))
# A scoped admin with agent:write, but outside the test agent's loom:group.
OTHER_GROUP_ADMIN = UserInfo(sub="o", username="o", groups=["t-admin", "g-admins-demo"],
                             scopes=derive_scopes(["t-admin", "g-admins-demo"]))


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
    """The readiness check both evaluation modes wait on — retries with mild backoff, and only
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
        self.assertTrue(evals.has_evaluatable_span(result))
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

def _batch_detail(job_id: str, status: str = "COMPLETED", error_details=None) -> dict:
    detail = {
        "batchEvaluationId": job_id,
        "batchEvaluationArn": f"arn:aws:bedrock-agentcore:us-east-1:123456789012:batch-evaluate/{job_id}",
        "status": status,
        "outputConfig": {"cloudWatchConfig": {
            "logGroupName": "/aws/bedrock-agentcore/evaluations/batch-evaluations/results/default",
            "logStreamName": f"run-{job_id}",
        }},
    }
    if error_details:
        detail["errorDetails"] = error_details
    return detail


def _score_record(evaluator: str, value: float, label: str = "Good", session: str = "s1") -> dict:
    return {"session_id": session, "evaluator": evaluator, "value": value, "label": label,
            "explanation": f"{evaluator} reasoning", "error_type": None, "error_message": None}


def _error_record(message: str, error_type: str = "JobProcessorCustomerException", session: str = "s1") -> dict:
    return {"session_id": session, "evaluator": None, "value": None, "label": None, "explanation": None,
            "error_type": error_type, "error_message": message}


NOT_FOUND_YET = ("No spans were found for the session. Verify sessionId and that spans exist in "
                 "CloudWatch Logs within the configured time range. sessionId=s1")
NO_AGENT_SPANS_YET = ("No evaluable agent spans found for the session. Verify the agent emits spans "
                      "from a supported instrumentation scope.")


class TestRunBatchEvaluation(unittest.TestCase):
    """Batch mode: one StartBatchEvaluation job scores several sessions,
    results are split back out per session, and only the sessions the job
    couldn't see yet go into a second job."""

    def _client(self, *details: dict) -> MagicMock:
        client = MagicMock()
        client.start_batch_evaluation.side_effect = [
            {"batchEvaluationId": d["batchEvaluationId"]} for d in details
        ]
        client.get_batch_evaluation.side_effect = list(details)
        return client

    def _run(self, client: MagicMock, records_per_job: list, sessions=None, **kwargs):
        sessions = sessions or [evals.BatchSession("s1")]
        with patch("boto3.client", return_value=client), \
             patch("app.services.evaluations.time.sleep") as sleep, \
             patch("app.services.evaluations.read_results", side_effect=[(r, False) for r in records_per_job]):
            outcomes = evals.run_batch_evaluation(
                ["Builtin.Correctness", "Builtin.Helpfulness"], sessions, "test_agent", LOG_GROUP,
                "us-east-1", "loom_a1_r2_abc123", **kwargs,
            )
        return outcomes, sleep

    def test_one_job_scores_every_session_and_splits_results_per_session(self):
        client = self._client(_batch_detail("job-1"))
        outcomes, _ = self._run(client, [[
            _score_record("Builtin.Helpfulness", 0.83, "Very Helpful", session="s1"),
            _score_record("Builtin.Helpfulness", 0.5, session="s1"),  # second trace, same evaluator
            _score_record("Builtin.Correctness", 1.0, "Perfectly Correct", session="s1"),
            _score_record("Builtin.Helpfulness", 0.67, session="s2"),
            _score_record("Builtin.Correctness", 0.0, "Incorrect", session="s2"),
        ]], sessions=[evals.BatchSession("s1", "first case", {"loom_test_case_id": "7"}),
                      evals.BatchSession("s2")])
        self.assertEqual(client.start_batch_evaluation.call_count, 1)
        kwargs = client.start_batch_evaluation.call_args.kwargs
        self.assertEqual(kwargs["batchEvaluationName"], "loom_a1_r2_abc123_a1")
        self.assertEqual(kwargs["evaluators"], [{"evaluatorId": "Builtin.Correctness"}, {"evaluatorId": "Builtin.Helpfulness"}])
        self.assertEqual(kwargs["dataSourceConfig"], {"cloudWatchLogs": {
            "serviceNames": ["test_agent"],
            "logGroupNames": [LOG_GROUP],
            "filterConfig": {"sessionIds": ["s1", "s2"]},
        }})
        # Only sessions with something to label get a metadata entry.
        self.assertEqual(kwargs["evaluationMetadata"], {"sessionMetadata": [
            {"sessionId": "s1", "testScenarioId": "first case", "metadata": {"loom_test_case_id": "7"}},
        ]})
        s1 = {sc["evaluator"]: sc for sc in outcomes["s1"].scores}
        self.assertAlmostEqual(s1["Builtin.Helpfulness"]["value"], (0.83 + 0.5) / 2)
        self.assertEqual(s1["Builtin.Correctness"]["label"], "Perfectly Correct")
        s2 = {sc["evaluator"]: sc for sc in outcomes["s2"].scores}
        self.assertEqual(s2["Builtin.Correctness"]["value"], 0.0)
        self.assertEqual({o.job_id for o in outcomes.values()}, {"job-1"})
        self.assertEqual([o.errors for o in outcomes.values()], [[], []])

    def test_no_metadata_is_sent_when_no_session_has_any(self):
        client = self._client(_batch_detail("job-1"))
        self._run(client, [[_score_record("Builtin.Helpfulness", 0.83)]])
        self.assertNotIn("evaluationMetadata", client.start_batch_evaluation.call_args.kwargs)

    def test_only_sessions_not_visible_yet_go_into_a_second_job(self):
        client = self._client(_batch_detail("job-1", "COMPLETED_WITH_ERRORS"), _batch_detail("job-2"))
        outcomes, sleep = self._run(client, [
            [_score_record("Builtin.Helpfulness", 0.83, session="s1"), _error_record(NOT_FOUND_YET, session="s2")],
            [_score_record("Builtin.Helpfulness", 0.5, session="s2")],
        ], sessions=[evals.BatchSession("s1"), evals.BatchSession("s2")], retry_delay_s=60.0)
        self.assertEqual(client.start_batch_evaluation.call_count, 2)
        second = client.start_batch_evaluation.call_args_list[1].kwargs
        self.assertEqual(second["batchEvaluationName"], "loom_a1_r2_abc123_a2")
        self.assertEqual(second["dataSourceConfig"]["cloudWatchLogs"]["filterConfig"], {"sessionIds": ["s2"]})
        sleep.assert_any_call(60.0)
        self.assertEqual((outcomes["s1"].job_id, outcomes["s2"].job_id), ("job-1", "job-2"))
        # The retried session used both jobs; cleanup needs to know about the first one too.
        self.assertEqual((outcomes["s1"].job_ids, outcomes["s2"].job_ids), (("job-1",), ("job-1", "job-2")))
        self.assertEqual(outcomes["s2"].scores[0]["value"], 0.5)
        self.assertEqual(outcomes["s2"].errors, [])

    def test_still_not_visible_after_the_retry_reports_the_session_error(self):
        client = self._client(_batch_detail("job-1", "FAILED"), _batch_detail("job-2", "FAILED"))
        outcomes, _ = self._run(client, [[_error_record(NOT_FOUND_YET)], [_error_record(NO_AGENT_SPANS_YET)]])
        self.assertEqual(client.start_batch_evaluation.call_count, 2)
        self.assertEqual(outcomes["s1"].scores, [])
        self.assertEqual(len(outcomes["s1"].errors), 1)
        self.assertIn("No evaluable agent spans found", outcomes["s1"].errors[0])

    def test_other_session_errors_are_not_retried(self):
        client = self._client(_batch_detail("job-1", "FAILED"))
        outcomes, _ = self._run(client, [[_error_record("Evaluator failed", "InternalError")]])
        self.assertEqual(client.start_batch_evaluation.call_count, 1)
        self.assertEqual(outcomes["s1"], evals.SessionOutcome([], ["InternalError: Evaluator failed"], "job-1", ("job-1",)))

    def test_partial_results_keep_scores_and_errors_without_retrying(self):
        client = self._client(_batch_detail("job-1", "COMPLETED_WITH_ERRORS"))
        outcomes, _ = self._run(client, [[
            _score_record("Builtin.Helpfulness", 0.83),
            _error_record("Correctness failed", "EvaluatorError"),
        ]])
        self.assertEqual(client.start_batch_evaluation.call_count, 1)
        self.assertEqual([sc["evaluator"] for sc in outcomes["s1"].scores], ["Builtin.Helpfulness"])
        self.assertEqual(outcomes["s1"].errors, ["EvaluatorError: Correctness failed"])

    def test_job_with_no_result_records_falls_back_to_its_error_details(self):
        client = self._client(_batch_detail("job-1", "FAILED", ["Something went wrong."]))
        outcomes, _ = self._run(client, [[]] * 6)
        self.assertEqual(outcomes["s1"].errors, ["Something went wrong."])

    def test_session_missing_from_a_job_with_other_results_gets_its_own_error(self):
        client = self._client(_batch_detail("job-1"))
        outcomes, _ = self._run(client, [[_score_record("Builtin.Helpfulness", 0.83, session="s1")]],
                                sessions=[evals.BatchSession("s1"), evals.BatchSession("s2")])
        self.assertEqual(outcomes["s2"].scores, [])
        self.assertIn("no result for this session", outcomes["s2"].errors[0])

    def test_job_that_never_finishes_fails_every_session_in_it(self):
        client = MagicMock()
        client.start_batch_evaluation.return_value = {"batchEvaluationId": "job-1"}
        client.get_batch_evaluation.return_value = _batch_detail("job-1", "IN_PROGRESS")
        with patch("boto3.client", return_value=client), \
             patch("app.services.evaluations.time.sleep"), \
             patch("app.services.evaluations.time.time", side_effect=[0.0, 0.0, 1000.0]):
            outcomes = evals.run_batch_evaluation(
                ["Builtin.Helpfulness"], [evals.BatchSession("s1"), evals.BatchSession("s2")],
                "test_agent", LOG_GROUP, "us-east-1", "loom_x", job_timeout_s=900.0,
            )
        for sid in ("s1", "s2"):
            self.assertEqual((outcomes[sid].scores, outcomes[sid].job_id), ([], "job-1"))
            self.assertIn("still IN_PROGRESS", outcomes[sid].errors[0])

    def test_start_failure_is_an_error_not_an_exception(self):
        client = MagicMock()
        client.start_batch_evaluation.side_effect = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "bad"}}, "StartBatchEvaluation")
        with patch("boto3.client", return_value=client), patch("app.services.evaluations.time.sleep"):
            outcomes = evals.run_batch_evaluation(
                ["Builtin.Helpfulness"], [evals.BatchSession("s1")], "test_agent", LOG_GROUP, "us-east-1", "loom_x")
        self.assertIsNone(outcomes["s1"].job_id)
        self.assertIn("StartBatchEvaluation failed", outcomes["s1"].errors[0])


class TestDeleteBatchJobs(unittest.TestCase):
    """Cascading a Loom deletion into AWS: the job, then its results stream."""

    def _clients(self, statuses: dict[str, list[str]]):
        client = MagicMock()
        detail_calls: dict[str, int] = {}

        def get(batchEvaluationId):
            if batchEvaluationId not in statuses:
                raise _not_found("GetBatchEvaluation")
            seq = statuses[batchEvaluationId]
            i = min(detail_calls.get(batchEvaluationId, 0), len(seq) - 1)
            detail_calls[batchEvaluationId] = i + 1
            return _batch_detail(batchEvaluationId, seq[i])

        client.get_batch_evaluation.side_effect = get
        logs = MagicMock()
        return client, logs

    def _delete(self, client, logs, job_ids):
        with patch("boto3.client", side_effect=lambda service, **_: logs if service == "logs" else client), \
             patch("app.services.evaluations.time.sleep"):
            return evals.delete_batch_jobs(job_ids, "us-east-1")

    def test_finished_job_is_deleted_with_its_results_stream(self):
        client, logs = self._clients({"loom_a1_r2_x_a1-0123456789": ["COMPLETED"]})
        failures = self._delete(client, logs, ["loom_a1_r2_x_a1-0123456789"])
        self.assertEqual(failures, [])
        client.stop_batch_evaluation.assert_not_called()
        client.delete_batch_evaluation.assert_called_once_with(batchEvaluationId="loom_a1_r2_x_a1-0123456789")
        logs.delete_log_stream.assert_called_once_with(
            logGroupName=evals.BATCH_RESULTS_LOG_GROUP, logStreamName="run-loom_a1_r2_x_a1-0123456789")

    def test_running_job_is_stopped_then_deleted(self):
        # AWS refuses to delete a job that is still IN_PROGRESS.
        client, logs = self._clients({"loom_job-1": ["IN_PROGRESS", "STOPPING", "STOPPED"]})
        failures = self._delete(client, logs, ["loom_job-1"])
        self.assertEqual(failures, [])
        client.stop_batch_evaluation.assert_called_once_with(batchEvaluationId="loom_job-1")
        client.delete_batch_evaluation.assert_called_once_with(batchEvaluationId="loom_job-1")

    def test_job_already_gone_is_not_a_failure(self):
        client, logs = self._clients({})
        self.assertEqual(self._delete(client, logs, ["loom_gone-1"]), [])
        client.delete_batch_evaluation.assert_not_called()
        logs.delete_log_stream.assert_called_once()  # its stream may still be there

    def test_only_loom_jobs_are_ever_touched(self):
        client, logs = self._clients({"someone_elses-1": ["COMPLETED"]})
        self.assertEqual(self._delete(client, logs, ["someone_elses-1", "", None]), [])
        client.get_batch_evaluation.assert_not_called()
        client.delete_batch_evaluation.assert_not_called()
        logs.delete_log_stream.assert_not_called()

    def test_refused_delete_is_reported_and_the_rest_still_go(self):
        client, logs = self._clients({"loom_a-1": ["COMPLETED"], "loom_b-1": ["COMPLETED"]})
        client.delete_batch_evaluation.side_effect = [
            ClientError({"Error": {"Code": "ConflictException", "Message": "busy"}}, "DeleteBatchEvaluation"),
            {"status": "DELETING"},
        ]
        failures = self._delete(client, logs, ["loom_a-1", "loom_b-1"])
        self.assertEqual(len(failures), 1)
        self.assertIn("loom_a-1", failures[0])
        logs.delete_log_stream.assert_called_once_with(
            logGroupName=evals.BATCH_RESULTS_LOG_GROUP, logStreamName="run-loom_b-1")

    def test_results_written_somewhere_else_are_left_alone(self):
        client, logs = self._clients({"loom_c-1": ["COMPLETED"]})
        detail = _batch_detail("loom_c-1")
        detail["outputConfig"]["cloudWatchConfig"]["logGroupName"] = "/custom/results"
        client.get_batch_evaluation.side_effect = None
        client.get_batch_evaluation.return_value = detail
        self.assertEqual(self._delete(client, logs, ["loom_c-1"]), [])
        client.delete_batch_evaluation.assert_called_once()
        logs.delete_log_stream.assert_not_called()


class TestStoppingRuns(unittest.TestCase):
    """A user can stop a run; the waits notice on their next poll."""

    def test_span_wait_returns_without_polling_once_stopped(self):
        with patch("app.services.evaluations.fetch_session_spans") as mock_fetch:
            spans = evals.wait_for_session_spans("/g", "s1", "us-east-1", timeout_s=60, should_stop=lambda: True)
        self.assertEqual(spans, [])
        mock_fetch.assert_not_called()

    def test_job_wait_stops_the_job_once_then_waits_for_it_to_settle(self):
        client = MagicMock()
        client.get_batch_evaluation.side_effect = [
            _batch_detail("job-1", "IN_PROGRESS"), _batch_detail("job-1", "STOPPING"), _batch_detail("job-1", "STOPPED")]
        with patch("app.services.evaluations.time.sleep"):
            detail = evals._wait_for_job(client, "job-1", 900, 1, should_stop=lambda: True)
        self.assertEqual(detail["status"], "STOPPED")
        client.stop_batch_evaluation.assert_called_once_with(batchEvaluationId="job-1")

    def test_nothing_is_started_when_every_session_is_already_stopped(self):
        client = MagicMock()
        with patch("boto3.client", return_value=client), patch("app.services.evaluations.time.sleep"):
            outcomes = evals.run_batch_evaluation(
                ["Builtin.Helpfulness"], [evals.BatchSession("s1")], "svc", LOG_GROUP, "us-east-1", "loom_x",
                should_stop=lambda ids: True)
        client.start_batch_evaluation.assert_not_called()
        self.assertEqual(outcomes["s1"].scores, [])
        self.assertIn("Stopped", outcomes["s1"].errors[0])

    def test_started_jobs_are_reported_and_a_stopped_session_is_not_retried(self):
        client = MagicMock()
        client.start_batch_evaluation.return_value = {"batchEvaluationId": "job-1"}
        client.get_batch_evaluation.return_value = _batch_detail("job-1", "FAILED")
        started = []
        with patch("boto3.client", return_value=client), patch("app.services.evaluations.time.sleep"), \
             patch("app.services.evaluations.read_results", return_value=([_error_record(NOT_FOUND_YET)], False)):
            evals.run_batch_evaluation(
                ["Builtin.Helpfulness"], [evals.BatchSession("s1")], "svc", LOG_GROUP, "us-east-1", "loom_x",
                on_job_started=lambda job_id, ids: started.append((job_id, ids)),
                # Stopped after the job started: the not-visible-yet retry is skipped.
                should_stop=lambda ids: bool(started))
        self.assertEqual(started, [("job-1", ["s1"])])
        self.assertEqual(client.start_batch_evaluation.call_count, 1)

    def test_only_sessions_still_wanted_go_into_the_retry(self):
        client = MagicMock()
        client.start_batch_evaluation.side_effect = [{"batchEvaluationId": "job-1"}, {"batchEvaluationId": "job-2"}]
        client.get_batch_evaluation.side_effect = [_batch_detail("job-1", "FAILED"), _batch_detail("job-2")]
        started = []
        with patch("boto3.client", return_value=client), patch("app.services.evaluations.time.sleep"), \
             patch("app.services.evaluations.read_results", side_effect=[
                 ([_error_record(NOT_FOUND_YET, session="s1"), _error_record(NOT_FOUND_YET, session="s2")], False),
                 ([_score_record("Builtin.Helpfulness", 0.83, session="s1")], False)]):
            evals.run_batch_evaluation(
                ["Builtin.Helpfulness"], [evals.BatchSession("s1"), evals.BatchSession("s2")], "svc", LOG_GROUP,
                "us-east-1", "loom_x", on_job_started=lambda job_id, ids: started.append(job_id),
                # s2's run is stopped once the first job has started.
                should_stop=lambda ids: bool(started) and ids == ["s2"])
        second = client.start_batch_evaluation.call_args_list[1].kwargs
        self.assertEqual(second["dataSourceConfig"]["cloudWatchLogs"]["filterConfig"], {"sessionIds": ["s1"]})

    def test_stop_batch_jobs_only_touches_loom_jobs_and_ignores_finished_ones(self):
        client = MagicMock()
        client.stop_batch_evaluation.side_effect = [
            ClientError({"Error": {"Code": "ConflictException", "Message": "already done"}}, "StopBatchEvaluation"),
            {"status": "STOPPING"},
        ]
        with patch("boto3.client", return_value=client):
            failures = evals.stop_batch_jobs(["loom_done-1", "someone_elses-1", "loom_running-1"], "us-east-1")
        self.assertEqual(failures, [])
        self.assertEqual([c.kwargs["batchEvaluationId"] for c in client.stop_batch_evaluation.call_args_list],
                         ["loom_done-1", "loom_running-1"])


class TestSessionServiceName(unittest.TestCase):

    def test_reads_service_name_from_an_evaluatable_span(self):
        spans = [
            {"scope": {"name": "opentelemetry.instrumentation.starlette"},
             "resource": {"attributes": {"service.name": "wrong"}}},
            {"scope": {"name": "strands.telemetry.tracer"},
             "resource": {"attributes": {"service.name": "demo_elicitation"}}},
        ]
        self.assertEqual(evals.session_service_name(spans), "demo_elicitation")

    def test_none_without_an_evaluatable_span(self):
        self.assertIsNone(evals.session_service_name([{"scope": {"name": "x"}, "resource": {}}]))


class TestBatchErrorRecordParsing(unittest.TestCase):

    def test_session_error_records_carry_their_error_type_and_message(self):
        event = {"timestamp": 1, "message": json.dumps({
            "name": "gen_ai.evaluation.result",
            "attributes": {"session.id": "s1", "error.type": "JobProcessorCustomerException",
                           "error.message": NOT_FOUND_YET, "error": 1},
        })}
        [record] = evals.parse_result_records([event])
        self.assertEqual(record["error_type"], "JobProcessorCustomerException")
        self.assertEqual(record["error_message"], NOT_FOUND_YET)
        self.assertIsNone(record["value"])


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
        self.wait_patcher = patch("app.routers.evaluations.evals.wait_for_session_spans", return_value=[_span("invoke_agent")])
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
        # Most tests here exercise the on-demand pipeline; batch tests ask for
        # batch explicitly. The default itself is covered by its own test.
        body = {
            "name": "Greets politely",
            "prompt": "Say hello",
            "evaluator_ids": ["Builtin.Helpfulness"],
            "evaluation_mode": "on_demand",
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
        self.assertEqual(resp.json(), {"status": None, "scores": [], "errors": [], "session_id": None,
                                       "evaluation_mode": None, "batch_job_id": None})

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


    def test_create_defaults_evaluation_mode_to_batch(self):
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases", json={
            "name": "n", "prompt": "p", "evaluator_ids": ["Builtin.Helpfulness"],
        })
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()["evaluation_mode"], "batch")

    def test_create_and_update_evaluation_mode(self):
        created = self._create_test_case(evaluation_mode="batch")
        self.assertEqual(created["evaluation_mode"], "batch")
        resp = self.client.put(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}",
            json={"name": "n", "prompt": "p", "evaluator_ids": ["Builtin.Helpfulness"], "evaluation_mode": "on_demand"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["evaluation_mode"], "on_demand")

    def test_unknown_evaluation_mode_is_422(self):
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases", json={
            "name": "n", "prompt": "p", "evaluator_ids": ["Builtin.Helpfulness"], "evaluation_mode": "online",
        })
        self.assertEqual(resp.status_code, 422)

    def test_batch_mode_allows_at_most_ten_evaluators(self):
        eleven = [f"Builtin.E{i}" for i in range(11)]
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases", json={
            "name": "n", "prompt": "p", "evaluator_ids": eleven, "evaluation_mode": "batch",
        })
        self.assertEqual(resp.status_code, 422)
        self.assertIn("at most 10 evaluators", resp.text)
        # On-demand calls Evaluate once per evaluator, so it has no such limit.
        self._create_test_case(evaluator_ids=eleven)

    def _batch_outcomes(self, evaluator_ids, sessions, *_args, **_kwargs):
        """Stand-in for evals.run_batch_evaluation: every session scores 0.83
        on every evaluator in the job, recorded so tests can see the grouping."""
        self.batch_jobs.append((tuple(evaluator_ids), [s.session_id for s in sessions], sessions))
        job_id = f"job-{len(self.batch_jobs)}"
        return {s.session_id: evals.SessionOutcome(
            [{"evaluator": e, "value": 0.83, "label": "Very Helpful", "explanation": "ok", "level": None}
             for e in evaluator_ids], [], job_id) for s in sessions}

    def _agent_spans(self, *_args, **_kwargs) -> list:
        return [{"scope": {"name": "strands.telemetry.tracer"},
                 "resource": {"attributes": {"service.name": "test_agent"}}}]

    def _patch_batch_pipeline(self):
        self.batch_jobs = []
        # The in-memory test database is one shared connection; run Run all's
        # and each batch group's work one item at a time so threads don't
        # interleave on it.
        for name in ("_RUN_ALL_WORKERS", "_BATCH_WORKERS"):
            workers = patch(f"app.routers.evaluations.{name}", 1)
            workers.start()
            self.addCleanup(workers.stop)
        self.wait_patcher.stop()
        self.addCleanup(self.wait_patcher.start)
        for target, kwargs in (
            ("app.routers.evaluations.evals.wait_for_session_spans", {"side_effect": self._agent_spans}),
            ("app.routers.evaluations.evals.run_batch_evaluation", {"side_effect": self._batch_outcomes}),
            ("app.routers.evaluations.invoke_agent", {"side_effect": lambda **_: iter([{"type": "text", "content": "Hi"}])}),
            ("app.routers.evaluations.boto3.client", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_run_in_batch_mode_scores_with_a_batch_job(self):
        self._patch_batch_pipeline()
        with patch("app.routers.evaluations.evals.run_on_demand_evaluation") as mock_on_demand:
            created = self._create_test_case(evaluation_mode="batch")
            self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/run")
        mock_on_demand.assert_not_called()
        last_run = self.client.get(
            f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}/last-run").json()
        self.assertEqual(last_run["status"], "COMPLETED")
        self.assertEqual(last_run["evaluation_mode"], "batch")
        self.assertEqual(last_run["batch_job_id"], "job-1")
        [(evaluator_ids, session_ids, sessions)] = self.batch_jobs
        self.assertEqual(evaluator_ids, ("Builtin.Helpfulness",))
        self.assertEqual(session_ids, [last_run["session_id"]])
        self.assertEqual(sessions[0].scenario_id, "Greets politely")  # labelled with the test case
        self.assertEqual(sessions[0].metadata, {"loom_test_case_id": str(created["id"])})

    def test_run_all_groups_batch_test_cases_by_evaluator_set(self):
        self._patch_batch_pipeline()
        base = f"/api/agents/{self.agent.id}/evaluations/test-cases"
        same_a = self._create_test_case(name="a", evaluation_mode="batch",
                                        evaluator_ids=["Builtin.Correctness", "Builtin.Helpfulness"])
        same_b = self._create_test_case(name="b", evaluation_mode="batch",
                                        evaluator_ids=["Builtin.Helpfulness", "Builtin.Correctness"])  # same set, other order
        other = self._create_test_case(name="c", evaluation_mode="batch", evaluator_ids=["Builtin.ToolSelectionAccuracy"])
        on_demand = self._create_test_case(name="d")
        with patch("app.routers.evaluations.evals.run_on_demand_evaluation",
                   return_value=([{"evaluator": "Builtin.Helpfulness", "value": 0.9, "label": None,
                                   "explanation": None, "level": None}], [])) as mock_on_demand:
            resp = self.client.post(f"{base}/run-all")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["batch_jobs"], 2)
        self.assertEqual({r["test_case_id"]: r["evaluation_mode"] for r in body["runs"]}, {
            same_a["id"]: "batch", same_b["id"]: "batch", other["id"]: "batch", on_demand["id"]: "on_demand"})

        jobs = {evaluator_ids: session_ids for evaluator_ids, session_ids, _ in self.batch_jobs}
        self.assertEqual(set(jobs), {("Builtin.Correctness", "Builtin.Helpfulness"), ("Builtin.ToolSelectionAccuracy",)})
        self.assertEqual(len(jobs[("Builtin.Correctness", "Builtin.Helpfulness")]), 2)
        self.assertEqual(len(jobs[("Builtin.ToolSelectionAccuracy",)]), 1)
        mock_on_demand.assert_called_once()

        runs = {tc["id"]: self.client.get(f"{base}/{tc['id']}/last-run").json()
                for tc in (same_a, same_b, other, on_demand)}
        self.assertTrue(all(r["status"] == "COMPLETED" for r in runs.values()))
        self.assertEqual(runs[same_a["id"]]["batch_job_id"], runs[same_b["id"]]["batch_job_id"])
        self.assertNotEqual(runs[same_a["id"]]["batch_job_id"], runs[other["id"]]["batch_job_id"])
        self.assertIsNone(runs[on_demand["id"]]["batch_job_id"])
        self.assertEqual(jobs[("Builtin.Correctness", "Builtin.Helpfulness")],
                         [runs[same_a["id"]]["session_id"], runs[same_b["id"]]["session_id"]])

    def test_run_all_scores_the_ready_sessions_without_the_ones_that_never_became_visible(self):
        self._patch_batch_pipeline()
        base = f"/api/agents/{self.agent.id}/evaluations/test-cases"
        ready = self._create_test_case(name="ready", evaluation_mode="batch")
        slow = self._create_test_case(name="slow", evaluation_mode="batch")
        failing = self._create_test_case(name="failing", evaluation_mode="batch")
        prompts = {"ready": "p-ready", "slow": "p-slow", "failing": "p-failing"}
        for tc in (ready, slow, failing):
            self.client.put(f"{base}/{tc['id']}", json={"name": tc["name"], "prompt": prompts[tc["name"]],
                                                       "evaluator_ids": ["Builtin.Helpfulness"], "evaluation_mode": "batch"})
        slow_session = {}

        def invoke(**kwargs):
            if kwargs["prompt"] == "p-failing":
                raise RuntimeError("runtime unavailable")
            if kwargs["prompt"] == "p-slow":
                slow_session["id"] = kwargs["session_id"]
            return iter([{"type": "text", "content": "Hi"}])

        def spans(_log_group, session_id, *_args, **_kwargs):
            if session_id == slow_session.get("id"):
                return [{"scope": {"name": "opentelemetry.instrumentation.starlette"}}]
            return self._agent_spans()

        with patch("app.routers.evaluations.invoke_agent", side_effect=invoke), \
             patch("app.routers.evaluations.evals.wait_for_session_spans", side_effect=spans):
            self.client.post(f"{base}/run-all")

        runs = {tc["name"]: self.client.get(f"{base}/{tc['id']}/last-run").json() for tc in (ready, slow, failing)}
        self.assertEqual(runs["ready"]["status"], "COMPLETED")
        self.assertEqual(runs["slow"]["status"], "ERROR")
        self.assertIn("weren't queryable in CloudWatch", runs["slow"]["errors"][0])
        self.assertEqual(runs["failing"]["status"], "ERROR")
        self.assertIn("Failed to invoke agent", runs["failing"]["errors"][0])
        [(_, session_ids, _)] = self.batch_jobs
        self.assertEqual(session_ids, [runs["ready"]["session_id"]])

    def test_run_all_needs_write_access_and_a_runtime(self):
        self._as_read_only_user()
        self.assertEqual(self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/run-all").status_code, 403)
        self._as_admin()
        self.agent.arn = ""  # no deployed runtime to invoke
        self.session.commit()
        self.assertEqual(self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/run-all").status_code, 400)

    @patch("app.routers.evaluations.evals.run_on_demand_evaluation",
           return_value=([{"evaluator": "Builtin.Helpfulness", "value": 0.9, "label": None,
                           "explanation": None, "level": None}], []))
    def test_each_run_keeps_the_mode_it_was_scored_with(self, _mock_on_demand):
        self._patch_batch_pipeline()
        created = self._create_test_case(evaluation_mode="batch")
        base = f"/api/agents/{self.agent.id}/evaluations/test-cases/{created['id']}"
        self.client.post(f"{base}/run")
        self.client.put(base, json={"name": "n", "prompt": "p", "evaluator_ids": ["Builtin.Helpfulness"],
                                    "evaluation_mode": "on_demand"})
        self.client.post(f"{base}/rescore")
        runs = self.client.get(f"{base}/runs").json()
        self.assertEqual([r["evaluation_mode"] for r in runs], ["on_demand", "batch"])  # newest first

    def _batch_run(self, tc_id: int, job_ids: list[str]) -> EvaluationRun:
        run = EvaluationRun(test_case_id=tc_id, session_id=str(len(job_ids)) + "-s", status="COMPLETED",
                            evaluation_mode="batch", batch_job_id=job_ids[-1])
        run.set_batch_job_ids(job_ids)
        self.session.add(run)
        self.session.commit()
        return run

    @patch("app.routers.evaluations.evals.delete_batch_jobs")
    def test_deleting_a_test_case_deletes_its_batch_jobs_but_not_shared_ones(self, mock_delete):
        a = self._create_test_case(name="a", evaluation_mode="batch")
        b = self._create_test_case(name="b", evaluation_mode="batch")
        self._batch_run(a["id"], ["loom_a_retry_a1-1", "loom_a_retry_a2-1"])  # retried: two jobs
        self._batch_run(a["id"], ["loom_shared_a1-1"])  # a Run all job a shares with b
        self._batch_run(b["id"], ["loom_shared_a1-1"])
        resp = self.client.delete(f"/api/agents/{self.agent.id}/evaluations/test-cases/{a['id']}")
        self.assertEqual(resp.status_code, 204)
        mock_delete.assert_called_once_with(["loom_a_retry_a1-1", "loom_a_retry_a2-1"], "us-east-1")

        # Once the last test case using the shared job goes, so does the job.
        mock_delete.reset_mock()
        self.client.delete(f"/api/agents/{self.agent.id}/evaluations/test-cases/{b['id']}")
        mock_delete.assert_called_once_with(["loom_shared_a1-1"], "us-east-1")

    def test_deleting_the_agent_deletes_all_its_batch_jobs(self):
        from app.routers.agents import _delete_agent_background
        a = self._create_test_case(name="a", evaluation_mode="batch")
        b = self._create_test_case(name="b", evaluation_mode="batch")
        self._batch_run(a["id"], ["loom_a_a1-1", "loom_a_a2-1"])
        self._batch_run(b["id"], ["loom_shared_a1-1"])
        self._batch_run(a["id"], ["loom_shared_a1-1"])
        with patch("app.routers.agents.SessionLocal", self.TestingSessionLocal), \
             patch("app.routers.agents.get_runtime", side_effect=Exception("gone")), \
             patch("app.services.evaluations.delete_batch_jobs") as mock_delete:
            _delete_agent_background(self.agent.id, self.agent.runtime_id, "us-east-1")
        mock_delete.assert_called_once_with(["loom_a_a1-1", "loom_a_a2-1", "loom_shared_a1-1"], "us-east-1")

    @patch("app.routers.evaluations.evals.delete_batch_jobs")
    def test_deleting_an_on_demand_test_case_touches_nothing_in_aws(self, mock_delete):
        tc = self._create_test_case()
        self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/run")
        self.client.delete(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}")
        mock_delete.assert_not_called()

    def test_a_test_case_deleted_mid_run_does_not_break_its_group_and_its_job_is_deleted(self):
        self._patch_batch_pipeline()
        base = f"/api/agents/{self.agent.id}/evaluations/test-cases"
        keep = self._create_test_case(name="keep", evaluation_mode="batch")
        shares = self._create_test_case(name="shares", evaluation_mode="batch")  # same evaluators as keep
        alone = self._create_test_case(name="alone", evaluation_mode="batch",
                                       evaluator_ids=["Builtin.ToolSelectionAccuracy"])
        doomed = {shares["id"], alone["id"]}

        def jobs_then_delete(evaluator_ids, sessions, *args, **kwargs):
            outcomes = self._batch_outcomes(evaluator_ids, sessions, *args, **kwargs)
            # Both test cases are deleted while their jobs run.
            self.session.query(EvaluationTestCase).filter(EvaluationTestCase.id.in_(doomed)).delete(
                synchronize_session=False)
            self.session.commit()
            return {sid: o._replace(job_ids=(o.job_id,)) for sid, o in outcomes.items()}

        with patch("app.routers.evaluations.evals.run_batch_evaluation", side_effect=jobs_then_delete), \
             patch("app.routers.evaluations.evals.delete_batch_jobs") as mock_delete:
            self.client.post(f"{base}/run-all")

        kept = self.client.get(f"{base}/{keep['id']}/last-run").json()
        self.assertEqual(kept["status"], "COMPLETED")
        # The job "keep" shares stays; the one only "alone" used is deleted.
        alone_job = next(f"job-{i + 1}" for i, (ev, _, _) in enumerate(self.batch_jobs)
                         if ev == ("Builtin.ToolSelectionAccuracy",))
        mock_delete.assert_called_once_with([alone_job], "us-east-1")
        self.assertNotEqual(kept["batch_job_id"], alone_job)

    def _running_run(self, tc_id: int, mode: str = "batch", job_ids=None) -> EvaluationRun:
        run = EvaluationRun(test_case_id=tc_id, session_id=f"s-{tc_id}-{len(job_ids or [])}",
                            status="EVALUATING", evaluation_mode=mode)
        if job_ids:
            run.batch_job_id = job_ids[-1]
            run.set_batch_job_ids(job_ids)
        self.session.add(run)
        self.session.commit()
        return run

    @patch("app.routers.evaluations.evals.stop_batch_jobs")
    def test_stopping_a_run_marks_it_stopped_and_stops_its_own_job(self, mock_stop):
        tc = self._create_test_case(evaluation_mode="batch")
        run = self._running_run(tc["id"], job_ids=["loom_only_mine-1"])
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/runs/{run.id}/stop")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "STOPPED")
        self.assertEqual(resp.json()["errors"], ["Stopped by u."])
        mock_stop.assert_called_once_with(["loom_only_mine-1"], "us-east-1")

    @patch("app.routers.evaluations.evals.stop_batch_jobs")
    def test_a_job_other_runs_still_need_keeps_running(self, mock_stop):
        a = self._create_test_case(name="a", evaluation_mode="batch")
        b = self._create_test_case(name="b", evaluation_mode="batch")
        run_a = self._running_run(a["id"], job_ids=["loom_shared-1"])
        self._running_run(b["id"], job_ids=["loom_shared-1"])
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{a['id']}/runs/{run_a.id}/stop")
        self.assertEqual(resp.status_code, 200)
        mock_stop.assert_not_called()

    def test_a_finished_run_cannot_be_stopped(self):
        tc = self._create_test_case()
        self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/run")
        run_id = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases").json()[0]["last_batch_evaluation_id"]
        resp = self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/runs/{run_id}/stop")
        self.assertEqual(resp.status_code, 409)

    def test_stopping_needs_write_access_and_a_real_run(self):
        tc = self._create_test_case()
        run = self._running_run(tc["id"], mode="on_demand")
        base = f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/runs"
        self.assertEqual(self.client.post(f"{base}/999999/stop").status_code, 404)
        self._as_read_only_user()
        self.assertEqual(self.client.post(f"{base}/{run.id}/stop").status_code, 403)

    def test_an_on_demand_run_stopped_while_waiting_is_never_scored(self):
        tc = self._create_test_case()
        stops = {}

        def spans_then_stop(_lg, session_id, *_a, should_stop=None, **_k):
            # The user stops the run while its spans are being waited on.
            run = self.session.query(EvaluationRun).filter_by(session_id=session_id).first()
            stops["checked_before"] = should_stop()
            run.status = "STOPPED"
            run.set_errors(["Stopped by u."])
            self.session.commit()
            stops["checked_after"] = should_stop()
            return [_span("invoke_agent")]

        self.wait_patcher.stop()
        with patch("app.routers.evaluations.evals.wait_for_session_spans", side_effect=spans_then_stop), \
             patch("app.routers.evaluations.evals.run_on_demand_evaluation") as mock_evaluate, \
             patch("app.routers.evaluations.invoke_agent", return_value=iter([{"type": "text", "content": "Hi"}])):
            self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/run")
        self.wait_patcher.start()
        self.assertEqual(stops, {"checked_before": False, "checked_after": True})
        mock_evaluate.assert_not_called()
        last = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/last-run").json()
        self.assertEqual((last["status"], last["errors"]), ("STOPPED", ["Stopped by u."]))

    def test_an_on_demand_run_stopped_while_being_scored_keeps_its_stop(self):
        tc = self._create_test_case()

        def evaluate_then_stop(_evaluator_ids, spans, _region):
            run = self.session.query(EvaluationRun).filter_by(status="EVALUATING").first()
            run.status = "STOPPED"
            run.set_errors(["Stopped by u."])
            self.session.commit()
            return [{"evaluator": "Builtin.Helpfulness", "value": 0.9, "label": None, "explanation": None,
                     "level": None}], []

        with patch("app.routers.evaluations.evals.run_on_demand_evaluation", side_effect=evaluate_then_stop), \
             patch("app.routers.evaluations.invoke_agent", return_value=iter([{"type": "text", "content": "Hi"}])):
            self.client.post(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/run")
        last = self.client.get(f"/api/agents/{self.agent.id}/evaluations/test-cases/{tc['id']}/last-run").json()
        self.assertEqual((last["status"], last["scores"]), ("STOPPED", []))

    def test_a_batch_run_stopped_while_waiting_leaves_its_group_and_the_rest_are_scored(self):
        self._patch_batch_pipeline()
        base = f"/api/agents/{self.agent.id}/evaluations/test-cases"
        keep = self._create_test_case(name="keep", evaluation_mode="batch")
        stop = self._create_test_case(name="stop", evaluation_mode="batch")
        stop_prompt = "please stop me"
        self.client.put(f"{base}/{stop['id']}", json={"name": "stop", "prompt": stop_prompt,
                                                      "evaluator_ids": ["Builtin.Helpfulness"], "evaluation_mode": "batch"})
        stop_session = {}

        def invoke(**kwargs):
            if kwargs["prompt"] == stop_prompt:
                stop_session["id"] = kwargs["session_id"]
            return iter([{"type": "text", "content": "Hi"}])

        def spans(_lg, session_id, *_a, **_k):
            if session_id == stop_session.get("id"):
                run = self.session.query(EvaluationRun).filter_by(session_id=session_id).first()
                run.status = "STOPPED"
                self.session.commit()
            return self._agent_spans()

        with patch("app.routers.evaluations.invoke_agent", side_effect=invoke), \
             patch("app.routers.evaluations.evals.wait_for_session_spans", side_effect=spans):
            self.client.post(f"{base}/run-all")
        runs = {tc["name"]: self.client.get(f"{base}/{tc['id']}/last-run").json() for tc in (keep, stop)}
        self.assertEqual(runs["keep"]["status"], "COMPLETED")
        self.assertEqual(runs["stop"]["status"], "STOPPED")
        [(_, session_ids, _)] = self.batch_jobs
        self.assertEqual(session_ids, [runs["keep"]["session_id"]])

    def test_a_job_started_for_a_stopped_run_is_still_recorded_for_cleanup(self):
        from app.routers.evaluations import _record_started_job, _runs_stopped
        tc = self._create_test_case(evaluation_mode="batch")
        run = self._running_run(tc["id"])
        with patch("app.routers.evaluations.SessionLocal", self.TestingSessionLocal):
            self.assertFalse(_runs_stopped([run.id]))
            _record_started_job("loom_new_a1-1", [run.id])
            self.session.query(EvaluationRun).filter_by(id=run.id).update({"status": "STOPPED"})
            self.session.commit()
            self.assertTrue(_runs_stopped([run.id]))
        self.session.expire_all()
        refreshed = self.session.query(EvaluationRun).filter_by(id=run.id).first()
        self.assertEqual(refreshed.get_batch_job_ids(), ["loom_new_a1-1"])

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
        self.tc = EvaluationTestCase(agent_id=self.agent.id, name="t", prompt="p", evaluation_mode="on_demand")
        self.tc.set_evaluator_ids(["Builtin.Helpfulness"])
        self.session.add(self.tc)
        self.session.commit()
        self.session.refresh(self.tc)
        self.run = EvaluationRun(test_case_id=self.tc.id, session_id="s1", status="PENDING",
                                 evaluation_mode="on_demand")
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
        mock_wait.return_value = [_span("invoke_agent")]
        mock_evaluate.return_value = ([{"evaluator": "Builtin.Helpfulness", "value": 0.9, "label": None, "explanation": None, "level": None}], [])
        from app.routers.evaluations import _execute_run
        # prompt=None skips invocation, as a rescore would.
        _execute_run(self.run.id, self.tc.id, self.agent.id, "s1", None, None, None, ADMIN)
        mock_wait.assert_called_once()
        self.session.expire_all()
        updated = self.session.query(EvaluationRun).filter_by(id=self.run.id).first()
        self.assertEqual(updated.status, "COMPLETED")
        self.assertEqual(updated.get_results()[0]["evaluator"], "Builtin.Helpfulness")

    @patch("app.routers.evaluations.evals.wait_for_session_spans")
    def test_no_spans_ends_as_error(self, mock_wait):
        mock_wait.return_value = []
        from app.routers.evaluations import _execute_run
        _execute_run(self.run.id, self.tc.id, self.agent.id, "s1", None, None, None, ADMIN)
        self.session.expire_all()
        updated = self.session.query(EvaluationRun).filter_by(id=self.run.id).first()
        self.assertEqual(updated.status, "ERROR")
        self.assertTrue(updated.get_errors())

    @patch("app.routers.evaluations.evals.run_batch_evaluation")
    @patch("app.routers.evaluations.evals.run_on_demand_evaluation")
    @patch("app.routers.evaluations.evals.wait_for_session_spans")
    def test_only_infrastructure_spans_after_the_wait_is_an_error_without_scoring(
            self, mock_wait, mock_on_demand, mock_batch):
        # The wait timed out with spans present but none an evaluator can read
        # (Logs Insights hadn't caught up on the agent spans yet).
        mock_wait.return_value = [_span("POST /invocations", scope="opentelemetry.instrumentation.starlette")]
        from app.routers.evaluations import _execute_run
        for mode in ("on_demand", "batch"):
            run = EvaluationRun(test_case_id=self.tc.id, session_id="s1", status="PENDING", evaluation_mode=mode)
            self.session.add(run)
            self.session.commit()
            _execute_run(run.id, self.tc.id, self.agent.id, "s1", None, None, None, ADMIN)
            self.session.expire_all()
            updated = self.session.query(EvaluationRun).filter_by(id=run.id).first()
            self.assertEqual(updated.status, "ERROR", mode)
            self.assertIn("weren't queryable in CloudWatch", updated.get_errors()[0])
        mock_on_demand.assert_not_called()
        mock_batch.assert_not_called()

    @patch("app.routers.evaluations.invoke_agent")
    def test_invoke_failure_ends_as_error_without_waiting_for_spans(self, mock_invoke):
        mock_invoke.side_effect = Exception("runtime unreachable")
        from app.routers.evaluations import _execute_run
        _execute_run(self.run.id, self.tc.id, self.agent.id, "s1", "say hi", None, None, ADMIN)
        self.session.expire_all()
        updated = self.session.query(EvaluationRun).filter_by(id=self.run.id).first()
        self.assertEqual(updated.status, "ERROR")
        self.assertIn("runtime unreachable", updated.get_errors()[0])

    @patch("app.routers.evaluations.evals.run_on_demand_evaluation")
    @patch("app.routers.evaluations.evals.wait_for_session_spans")
    def test_caller_outside_the_agents_group_is_refused_when_the_run_starts(self, mock_wait, mock_evaluate):
        # The route checks the caller, but the run starts later; it checks again.
        from app.routers.evaluations import _execute_run
        self.agent.tags = json.dumps({"loom:group": "strategics"})  # not the caller's group
        self.session.commit()
        _execute_run(self.run.id, self.tc.id, self.agent.id, "s1", None, None, None, OTHER_GROUP_ADMIN)
        self.session.expire_all()
        updated = self.session.query(EvaluationRun).filter_by(id=self.run.id).first()
        self.assertEqual(updated.status, "ERROR")
        self.assertIn("Not scored", updated.get_errors()[0])
        mock_wait.assert_not_called()
        mock_evaluate.assert_not_called()

    @patch("app.routers.evaluations.evals.run_batch_evaluation")
    @patch("app.routers.evaluations.evals.wait_for_session_spans")
    @patch("app.routers.evaluations.invoke_agent")
    def test_batch_runs_refuse_a_caller_outside_the_agents_group(self, mock_invoke, mock_wait, mock_batch):
        from app.routers.evaluations import _execute_batch_runs
        self.agent.tags = json.dumps({"loom:group": "strategics"})  # not the caller's group
        self.run.evaluation_mode = "batch"
        self.session.commit()
        _execute_batch_runs([(self.run.id, "say hi")], self.agent.id, None, OTHER_GROUP_ADMIN)
        self.session.expire_all()
        updated = self.session.query(EvaluationRun).filter_by(id=self.run.id).first()
        self.assertEqual(updated.status, "ERROR")
        self.assertIn("Not scored", updated.get_errors()[0])
        mock_invoke.assert_not_called()
        mock_wait.assert_not_called()
        mock_batch.assert_not_called()

    def test_missing_run_returns_quietly(self):
        from app.routers.evaluations import _execute_run
        _execute_run(999999, self.tc.id, self.agent.id, "s1", None, None, None, ADMIN)  # must not raise


class TestExecuteRunAll(unittest.TestCase):
    """Run all queues one background task, and FastAPI runs a request's
    background tasks one after another — so the on-demand runs and the batch
    group have to run concurrently inside it, or a suite takes the sum of
    every run's wait instead of the longest one."""

    @patch("app.routers.evaluations.boto3.client")
    def test_on_demand_runs_and_the_batch_group_run_at_the_same_time(self, _client):
        import threading
        from app.routers import evaluations as router
        # Three parties: two on-demand runs and one batch group. Each blocks
        # until all three are running; run one at a time, they would time out.
        barrier = threading.Barrier(3, timeout=5)
        ran: list[str] = []

        def on_demand(run_id, *_args):
            barrier.wait()
            ran.append(f"run-{run_id}")

        def batch_group(items, *_args):
            barrier.wait()
            ran.append(f"batch-{len(items)}")

        with patch.object(router, "_execute_run", side_effect=on_demand), \
             patch.object(router, "_execute_batch_runs", side_effect=batch_group):
            router._execute_run_all(
                [(1, 1, 1, "s1", "p", None, None, None), (2, 2, 1, "s2", "p", None, None, None)],
                [(3, "p"), (4, "p")], 1, "us-east-1", None, None,
            )
        self.assertEqual(sorted(ran), ["batch-2", "run-1", "run-2"])

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

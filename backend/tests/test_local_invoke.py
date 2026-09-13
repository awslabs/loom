"""Tests for the local LiteLLM invoke path and educational demo agent seed."""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies.auth import ALL_SCOPES, UserInfo, get_current_user
from app.main import app
from app.models.agent import Agent
from app.services.local_agents import (
    LOCAL_ORIENTADOR_ARN,
    LOCAL_ORIENTADOR_NAME,
    seed_local_demo_agents,
)
from app.services.local_invoke import (
    build_chat_messages,
    extract_completion_text,
    parse_openai_sse_line,
    resolve_local_model_id,
)


class TestLocalInvokeHelpers(unittest.TestCase):
    def test_parse_openai_sse_delta(self) -> None:
        line = 'data: {"choices":[{"delta":{"content":"Olá"}}]}'
        self.assertEqual(parse_openai_sse_line(line), "Olá")

    def test_parse_openai_sse_done_and_noise(self) -> None:
        self.assertIsNone(parse_openai_sse_line("data: [DONE]"))
        self.assertIsNone(parse_openai_sse_line(""))
        self.assertIsNone(parse_openai_sse_line(": keepalive"))

    def test_extract_completion_text_from_message(self) -> None:
        payload = {"choices": [{"message": {"content": "Matrícula de 20 a 28 de julho."}}]}
        self.assertEqual(
            extract_completion_text(payload),
            "Matrícula de 20 a 28 de julho.",
        )

    def test_build_messages_includes_system_prompt(self) -> None:
        agent = Agent(
            arn=LOCAL_ORIENTADOR_ARN,
            runtime_id="orientador-academico",
            name=LOCAL_ORIENTADOR_NAME,
            status="READY",
            region="local",
            account_id="local",
            source="local",
        )
        agent.config_entries = []
        from app.models.config_entry import ConfigEntry

        agent.config_entries = [
            ConfigEntry(
                agent_id=1,
                key="AGENT_CONFIG_JSON",
                value=json.dumps({
                    "model_id": "orientador-academico",
                    "system_prompt": "Você é o orientador.",
                }),
            )
        ]
        messages = build_chat_messages(agent, "Quando começa a matrícula?")
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("orientador", messages[0]["content"])
        self.assertEqual(messages[1], {"role": "user", "content": "Quando começa a matrícula?"})

    def test_resolve_runtime_model_override(self) -> None:
        agent = Agent(
            arn=LOCAL_ORIENTADOR_ARN,
            runtime_id="orientador-academico",
            name=LOCAL_ORIENTADOR_NAME,
            status="READY",
            region="local",
            account_id="local",
            source="local",
        )
        agent.config_entries = []
        self.assertEqual(resolve_local_model_id(agent, "cursor-local"), "cursor-local")


class TestLocalDemoAgentSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(bind=self.engine)

    def test_seed_is_idempotent(self) -> None:
        seed_local_demo_agents(self.engine)
        seed_local_demo_agents(self.engine)
        Session = sessionmaker(bind=self.engine)
        session = Session()
        try:
            rows = session.query(Agent).filter(Agent.arn == LOCAL_ORIENTADOR_ARN).all()
            self.assertEqual(len(rows), 1)
            agent = rows[0]
            self.assertEqual(agent.source, "local")
            self.assertEqual(agent.name, LOCAL_ORIENTADOR_NAME)
            self.assertEqual(agent.status, "READY")
            config = json.loads(agent.config_entries[0].value)
            self.assertEqual(config["provider"], "litellm")
            self.assertEqual(config["model_id"], "orientador-academico")
            self.assertEqual(
                agent.get_allowed_model_ids(),
                ["orientador-academico", "mock-echo", "cursor-local"],
            )
            self.assertIn("Universidade Horizonte", config["system_prompt"])
            agent.set_allowed_model_ids(["orientador-academico"])
            session.commit()
        finally:
            session.close()

        seed_local_demo_agents(self.engine)
        session = Session()
        try:
            agent = session.query(Agent).filter(Agent.arn == LOCAL_ORIENTADOR_ARN).one()
            self.assertEqual(
                agent.get_allowed_model_ids(),
                ["orientador-academico", "mock-echo", "cursor-local"],
            )
        finally:
            session.close()


class TestLocalInvokeEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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

    def setUp(self) -> None:
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            sub="local",
            username="local-dev",
            groups=["t-admin", "g-admins-super"],
            scopes=ALL_SCOPES.copy(),
            idp_type="local",
        )
        self.client = TestClient(app)
        seed_local_demo_agents(self.engine)
        self.agent = self.session.query(Agent).filter(Agent.arn == LOCAL_ORIENTADOR_ARN).one()

    def tearDown(self) -> None:
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        app.dependency_overrides.clear()

    def test_local_invoke_streams_litellm_chunks(self) -> None:
        async def fake_stream(**kwargs):
            yield "Olá, sou o Orientador Acadêmico"

        with patch(
            "app.services.local_invoke.get_litellm_proxy_config",
            return_value=("http://litellm:4000", "sk-test"),
        ), patch(
            "app.services.local_invoke.stream_litellm_text",
            new=fake_stream,
        ):
            response = self.client.post(
                f"/api/agents/{self.agent.id}/invoke",
                json={"prompt": "Quando começa a matrícula?", "qualifier": "DEFAULT"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: session_start", response.text)
        self.assertIn("event: chunk", response.text)
        self.assertIn("Orientador Acadêmico", response.text)
        self.assertIn("event: session_end", response.text)

    def test_local_invoke_errors_when_proxy_missing(self) -> None:
        with patch(
            "app.services.local_invoke.get_litellm_proxy_config",
            return_value=None,
        ):
            response = self.client.post(
                f"/api/agents/{self.agent.id}/invoke",
                json={"prompt": "ajuda", "qualifier": "DEFAULT"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", response.text)
        self.assertIn("LiteLLM proxy is not configured", response.text)

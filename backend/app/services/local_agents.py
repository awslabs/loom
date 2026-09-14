"""Seed a local-only demo agent for the compose stack.

Agents with source='local' are not AgentCore runtimes. Invoke is handled by
the backend talking to the LiteLLM proxy (see local_invoke). Idempotent: an
existing row with the same ARN is left untouched so an operator edit survives
backend restarts.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session, sessionmaker

from app.models.agent import Agent
from app.models.config_entry import ConfigEntry

logger = logging.getLogger(__name__)

LOCAL_ORIENTADOR_ARN = "arn:local:loom:local:local:runtime/orientador-academico"
LOCAL_ORIENTADOR_RUNTIME_ID = "orientador-academico"
LOCAL_ORIENTADOR_NAME = "Orientador Acadêmico"
LOCAL_ORIENTADOR_MODEL_ID = "orientador-academico"
LOCAL_ORIENTADOR_ALLOWED_MODELS = ["orientador-academico", "mock-echo", "cursor-local"]

LOCAL_ORIENTADOR_DESCRIPTION = (
    "Agente fictício da Coordenação de Graduação da Universidade Horizonte. "
    "Atende dúvidas de matrícula, calendário letivo, trancamento e "
    "aproveitamento de estudos. Somente desenvolvimento local — a resposta "
    "sai pelo proxy LiteLLM, não pelo AgentCore."
)

LOCAL_ORIENTADOR_SYSTEM_PROMPT = """Você é o Orientador Acadêmico da Universidade Horizonte, uma instituição de ensino superior fictícia usada só em desenvolvimento local.

Papel: atendimento da Coordenação de Graduação e da Secretaria Acadêmica.

Regras:
- Responda em português do Brasil, com tom cordial e institucional.
- Não invente sistemas reais de governo nem de outras universidades.
- Quando faltar um dado, oriente o aluno a procurar a Secretaria Acadêmica (sala A-102, 9h às 17h, dias úteis).
- Calendário letivo 2026.2: matrícula de 20 a 28 de julho; aulas de 3 de agosto a 11 de dezembro; provas finais de 14 a 18 de dezembro.
- Trancamento de componente: Portal do Aluno até a 4ª semana letiva; depois disso, requerimento na Coordenação com justificativa.
- Aproveitamento de estudos: requer ementa e histórico da instituição de origem; prazo de 15 dias úteis após o início do período.
- Você não emite documentos oficiais, não altera notas e não confirma pagamento de mensalidade.
"""


def seed_local_demo_agents(eng) -> None:
    """Insert the educational local agent when it is not already present."""
    session = sessionmaker(bind=eng)()
    try:
        _ensure_orientador_academico(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_orientador_academico(session: Session) -> None:
    existing = session.query(Agent).filter(Agent.arn == LOCAL_ORIENTADOR_ARN).first()
    if existing:
        if existing.get_allowed_model_ids() != list(LOCAL_ORIENTADOR_ALLOWED_MODELS):
            existing.set_allowed_model_ids(list(LOCAL_ORIENTADOR_ALLOWED_MODELS))
            logger.info("Updated allowed models for local demo agent id=%s", existing.id)
        for entry in existing.config_entries:
            if entry.key != "AGENT_CONFIG_JSON" or not entry.value:
                continue
            try:
                config = json.loads(entry.value)
            except (json.JSONDecodeError, TypeError):
                break
            if config.get("model_id") != LOCAL_ORIENTADOR_MODEL_ID:
                config["model_id"] = LOCAL_ORIENTADOR_MODEL_ID
                entry.value = json.dumps(config)
                logger.info("Reset local demo agent model_id to %s", LOCAL_ORIENTADOR_MODEL_ID)
            break
        return

    agent = Agent(
        arn=LOCAL_ORIENTADOR_ARN,
        runtime_id=LOCAL_ORIENTADOR_RUNTIME_ID,
        name=LOCAL_ORIENTADOR_NAME,
        description=LOCAL_ORIENTADOR_DESCRIPTION,
        status="READY",
        region="local",
        account_id="local",
        source="local",
        deployment_status="deployed",
        protocol="HTTP",
        network_mode="PUBLIC",
    )
    agent.set_available_qualifiers(["DEFAULT"])
    agent.set_allowed_model_ids(list(LOCAL_ORIENTADOR_ALLOWED_MODELS))
    agent.set_tags({
        "loom:application": "educacao",
        "loom:owner": "local-seed",
    })
    session.add(agent)
    session.flush()

    config_json = json.dumps({
        "model_id": LOCAL_ORIENTADOR_MODEL_ID,
        "provider": "litellm",
        "base_url": "",
        "system_prompt": LOCAL_ORIENTADOR_SYSTEM_PROMPT,
    })
    session.add(ConfigEntry(
        agent_id=agent.id,
        key="AGENT_CONFIG_JSON",
        value=config_json,
        is_secret=False,
        source="env_var",
    ))
    logger.info("Seeded local educational agent '%s'", LOCAL_ORIENTADOR_NAME)

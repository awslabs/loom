"""ORM models for Loom backend."""
from app.models.agent import Agent
from app.models.session import InvocationSession
from app.models.invocation import Invocation
from app.models.config_entry import ConfigEntry
from app.models.credential_provider import CredentialProvider
from app.models.integration import Integration
from app.models.managed_role import ManagedRole
from app.models.authorizer_config import AuthorizerConfig
from app.models.authorizer_credential import AuthorizerCredential
from app.models.memory import Memory
from app.models.tag_policy import TagPolicy
from app.models.tag_profile import TagProfile
from app.models.mcp import McpServer, McpTool, McpServerAccess
from app.models.site_setting import SiteSetting
from app.models.audit import AuditLogin, AuditAction, AuditPageView
from app.models.approval_policy import ApprovalPolicy
from app.models.approval_log import ApprovalLog
from app.models.vpc_config import VpcConfig
from app.models.evaluation import EvaluationTestCase, EvaluationRun
# a2a and identity_provider were missing here. They worked at runtime only
# because a router imports them, so `import app.models` left their tables out
# of the metadata and any standalone script that relied on it saw no such
# table. Same latent bug that was fixed for evaluation.py.
from app.models.a2a import A2aAgent, A2aAgentSkill, A2aAgentAccess
from app.models.identity_provider import IdentityProvider

__all__ = [
    "Agent", "InvocationSession", "Invocation", "ConfigEntry",
    "CredentialProvider", "Integration",
    "ManagedRole", "AuthorizerConfig",
    "AuthorizerCredential", "Memory", "TagPolicy", "TagProfile",
    "McpServer", "McpTool", "McpServerAccess", "SiteSetting",
    "AuditLogin", "AuditAction", "AuditPageView",
    "ApprovalPolicy", "ApprovalLog", "VpcConfig",
    "EvaluationTestCase", "EvaluationRun",
    "A2aAgent", "A2aAgentSkill", "A2aAgentAccess", "IdentityProvider",
]

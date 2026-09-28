from app.db import SessionLocal, init_db
from app.models.agent import Agent
from app.models.session import InvocationSession
from app.models.invocation import Invocation
from app.models.usage_limit import UsageLimit
from app.services.usage_limits import check_usage_limits
import uuid, json
from datetime import datetime, timezone

init_db()
db = SessionLocal()

agent = Agent(
    arn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent",
    runtime_id="test-agent-" + str(uuid.uuid4())[:8],
    name="Test Agent",
    status="READY",
    region="us-east-1",
    account_id="123456789012",
    log_group="/aws/bedrock-agentcore/runtimes/test-agent-DEFAULT",
)
db.add(agent)
db.commit()

limit = UsageLimit(
    name="Alice Token Cap",
    scope=json.dumps({"type": "user", "username": "alice"}),
    target=json.dumps({"type": "all"}),
    measure="tokens",
    threshold=100,
    window="daily",
    enforcement="block",
)
db.add(limit)
db.commit()

session = InvocationSession(
    agent_id=agent.id,
    session_id="usage-test-session",
    qualifier="DEFAULT",
    status="pending",
    created_at=datetime.now(timezone.utc),
    user_id="alice",
    groups=json.dumps([]),
)
db.add(session)
db.commit()

# Two invocations totalling 120 tokens -> should exceed the 100 threshold
for i in range(2):
    inv = Invocation(
        session_id="usage-test-session",
        invocation_id=f"usage-test-inv-{i}",
        status="complete",
        prompt_text="test",
        model_id="anthropic.claude-sonnet-4-6",
        input_tokens=30,
        output_tokens=30,
        created_at=datetime.now(timezone.utc),
    )
    db.add(inv)
db.commit()

decision = check_usage_limits(db, "alice", [], "anthropic.claude-sonnet-4-6")
print("enforcement:", decision.enforcement)
print("limit_name:", decision.limit_name)
print("current_usage:", decision.current_usage)
print("threshold:", decision.threshold)

# Different user, same model, no matching limit -> should be a no-op decision
decision2 = check_usage_limits(db, "bob", [], "anthropic.claude-sonnet-4-6")
print("bob enforcement:", decision2.enforcement)

# Cleanup
db.query(Invocation).filter(Invocation.session_id == "usage-test-session").delete()
db.query(InvocationSession).filter(InvocationSession.session_id == "usage-test-session").delete()
db.query(UsageLimit).filter(UsageLimit.id == limit.id).delete()
db.query(Agent).filter(Agent.id == agent.id).delete()
db.commit()

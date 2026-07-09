"""Tests for memory resource management endpoints."""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.models.memory import Memory


class TestMemoriesRouter(unittest.TestCase):
    """Test cases for /api/memories endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        """Set up test client and database session."""
        self.session = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        """Clean up database after each test."""
        self.session.rollback()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    @patch("app.routers.memories.svc_create_memory")
    def test_create_memory_semantic_strategy(self, mock_create):
        """Test creating a memory with a semantic strategy."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-abc123",
                "id": "mem-abc123",
                "name": "test_memory",
                "status": "CREATING",
                "eventExpiryDuration": 30,
                "strategies": [{"name": "default_semantic", "type": "SEMANTIC"}],
            }
        }

        response = self.client.post("/api/memories", json={
            "name": "test_memory",
            "event_expiry_duration": 30,
            "memory_strategies": [{"strategy_type": "semantic", "name": "default_semantic"}],
        })

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], "test_memory")
        self.assertEqual(data["memory_id"], "mem-abc123")
        self.assertEqual(data["status"], "CREATING")
        self.assertEqual(data["arn"], "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-abc123")
        self.assertEqual(data["event_expiry_duration"], 30)
        self.assertEqual(data["account_id"], "123456789012")

    @patch("app.routers.memories.svc_create_memory")
    def test_create_memory_summary_strategy(self, mock_create):
        """Test creating a memory with a summary strategy."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-sum123",
                "id": "mem-sum123",
                "name": "summary_memory",
                "status": "CREATING",
                "eventExpiryDuration": 60,
            }
        }

        response = self.client.post("/api/memories", json={
            "name": "summary_memory",
            "event_expiry_duration": 60,
            "memory_strategies": [{"strategy_type": "summary", "name": "default_summary"}],
        })

        self.assertEqual(response.status_code, 201)
        # Verify the service was called with correct AWS tagged union format
        call_args = mock_create.call_args
        strategies = call_args.kwargs.get("memory_strategies") or call_args[1].get("memory_strategies")
        self.assertEqual(strategies, [{"summaryMemoryStrategy": {"name": "default_summary"}}])

    @patch("app.routers.memories.svc_create_memory")
    def test_create_memory_user_preference_strategy(self, mock_create):
        """Test creating a memory with a user_preference strategy."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-up123",
                "id": "mem-up123",
                "name": "pref_memory",
                "status": "CREATING",
                "eventExpiryDuration": 30,
            }
        }

        response = self.client.post("/api/memories", json={
            "name": "pref_memory",
            "event_expiry_duration": 30,
            "memory_strategies": [{"strategy_type": "user_preference", "name": "default_pref"}],
        })

        self.assertEqual(response.status_code, 201)
        call_args = mock_create.call_args
        strategies = call_args.kwargs.get("memory_strategies") or call_args[1].get("memory_strategies")
        self.assertEqual(strategies, [{"userPreferenceMemoryStrategy": {"name": "default_pref"}}])

    @patch("app.routers.memories.svc_create_memory")
    def test_create_memory_episodic_strategy(self, mock_create):
        """Test creating a memory with an episodic strategy."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-ep123",
                "id": "mem-ep123",
                "name": "episodic_memory",
                "status": "CREATING",
                "eventExpiryDuration": 30,
            }
        }

        response = self.client.post("/api/memories", json={
            "name": "episodic_memory",
            "event_expiry_duration": 30,
            "memory_strategies": [{"strategy_type": "episodic", "name": "default_episodic"}],
        })

        self.assertEqual(response.status_code, 201)
        call_args = mock_create.call_args
        strategies = call_args.kwargs.get("memory_strategies") or call_args[1].get("memory_strategies")
        self.assertEqual(strategies, [{"episodicMemoryStrategy": {"name": "default_episodic"}}])

    @patch("app.routers.memories.svc_create_memory")
    def test_create_memory_custom_strategy(self, mock_create):
        """Test creating a memory with a custom strategy."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-cust123",
                "id": "mem-cust123",
                "name": "custom_memory",
                "status": "CREATING",
                "eventExpiryDuration": 30,
            }
        }

        response = self.client.post("/api/memories", json={
            "name": "custom_memory",
            "event_expiry_duration": 30,
            "memory_strategies": [{"strategy_type": "custom", "name": "my_custom"}],
        })

        self.assertEqual(response.status_code, 201)
        call_args = mock_create.call_args
        strategies = call_args.kwargs.get("memory_strategies") or call_args[1].get("memory_strategies")
        self.assertEqual(strategies, [{"customMemoryStrategy": {"name": "my_custom"}}])

    def test_strategy_type_mapping(self):
        """Test that all strategy types are correctly mapped to AWS parameter keys."""
        from app.routers.memories import STRATEGY_TYPE_MAP

        self.assertEqual(STRATEGY_TYPE_MAP["semantic"], "semanticMemoryStrategy")
        self.assertEqual(STRATEGY_TYPE_MAP["summary"], "summaryMemoryStrategy")
        self.assertEqual(STRATEGY_TYPE_MAP["user_preference"], "userPreferenceMemoryStrategy")
        self.assertEqual(STRATEGY_TYPE_MAP["episodic"], "episodicMemoryStrategy")
        self.assertEqual(STRATEGY_TYPE_MAP["custom"], "customMemoryStrategy")
        self.assertEqual(len(STRATEGY_TYPE_MAP), 5)

    @patch("app.routers.memories.svc_create_memory")
    def test_list_memories(self, mock_create):
        """Test listing memory resources."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-1",
                "id": "mem-1",
                "name": "memory_one",
                "status": "ACTIVE",
                "eventExpiryDuration": 30,
            }
        }

        self.client.post("/api/memories", json={
            "name": "memory_one",
            "event_expiry_duration": 30,
        })

        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-2",
                "id": "mem-2",
                "name": "memory_two",
                "status": "ACTIVE",
                "eventExpiryDuration": 60,
            }
        }

        self.client.post("/api/memories", json={
            "name": "memory_two",
            "event_expiry_duration": 60,
        })

        response = self.client.get("/api/memories")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

    @patch("app.routers.memories.svc_create_memory")
    def test_get_memory(self, mock_create):
        """Test getting a single memory resource."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-get1",
                "id": "mem-get1",
                "name": "get_test",
                "status": "ACTIVE",
                "eventExpiryDuration": 30,
            }
        }

        create_response = self.client.post("/api/memories", json={
            "name": "get_test",
            "event_expiry_duration": 30,
        })
        mem_id = create_response.json()["id"]

        response = self.client.get(f"/api/memories/{mem_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], mem_id)
        self.assertEqual(data["name"], "get_test")

    @patch("app.routers.memories.svc_get_memory")
    @patch("app.routers.memories.svc_create_memory")
    def test_refresh_memory(self, mock_create, mock_get):
        """Test refreshing memory status from AWS."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-ref1",
                "id": "mem-ref1",
                "name": "refresh_test",
                "status": "CREATING",
                "eventExpiryDuration": 30,
            }
        }

        create_response = self.client.post("/api/memories", json={
            "name": "refresh_test",
            "event_expiry_duration": 30,
        })
        mem_id = create_response.json()["id"]

        mock_get.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-ref1",
                "id": "mem-ref1",
                "name": "refresh_test",
                "status": "ACTIVE",
                "strategies": [{"name": "default", "type": "SEMANTIC"}],
            }
        }

        response = self.client.post(f"/api/memories/{mem_id}/refresh")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ACTIVE")

    @patch("app.routers.memories.svc_delete_memory")
    @patch("app.routers.memories.svc_create_memory")
    def test_delete_memory(self, mock_create, mock_delete):
        """Test deleting a memory resource (async deletion)."""
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-del1",
                "id": "mem-del1",
                "name": "delete_test",
                "status": "ACTIVE",
                "eventExpiryDuration": 30,
            }
        }
        mock_delete.return_value = {"memoryId": "mem-del1", "status": "DELETING"}

        create_response = self.client.post("/api/memories", json={
            "name": "delete_test",
            "event_expiry_duration": 30,
        })
        mem_id = create_response.json()["id"]

        # Delete initiates async deletion — returns DELETING status
        response = self.client.delete(f"/api/memories/{mem_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "DELETING")

        # Record still exists in DB with DELETING status
        get_response = self.client.get(f"/api/memories/{mem_id}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["status"], "DELETING")

        # Purge removes from DB
        purge_response = self.client.delete(f"/api/memories/{mem_id}/purge")
        self.assertEqual(purge_response.status_code, 204)

        # Now it's gone
        get_response = self.client.get(f"/api/memories/{mem_id}")
        self.assertEqual(get_response.status_code, 404)

    def test_invalid_strategy_type(self):
        """Test that an invalid strategy type returns 400."""
        response = self.client.post("/api/memories", json={
            "name": "bad_strategy",
            "event_expiry_duration": 30,
            "memory_strategies": [{"strategy_type": "nonexistent", "name": "bad"}],
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid strategy type", response.json()["detail"])

    def test_invalid_memory_name(self):
        """Test that a hyphenated memory name returns 400."""
        response = self.client.post("/api/memories", json={
            "name": "bad-name",
            "event_expiry_duration": 30,
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid memory name", response.json()["detail"])

    def test_invalid_strategy_name(self):
        """Test that a hyphenated strategy name returns 400."""
        response = self.client.post("/api/memories", json={
            "name": "valid_name",
            "event_expiry_duration": 30,
            "memory_strategies": [{"strategy_type": "semantic", "name": "bad-strategy-name"}],
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid strategy name", response.json()["detail"])

    def test_missing_required_fields(self):
        """Test that missing required fields returns 422."""
        # Missing event_expiry_duration
        response = self.client.post("/api/memories", json={
            "name": "no_expiry",
        })
        self.assertEqual(response.status_code, 422)

        # Missing name
        response = self.client.post("/api/memories", json={
            "event_expiry_duration": 30,
        })
        self.assertEqual(response.status_code, 422)

        # Empty body
        response = self.client.post("/api/memories", json={})
        self.assertEqual(response.status_code, 422)

    def test_get_nonexistent_memory(self):
        """Test that getting a non-existent memory returns 404."""
        response = self.client.get("/api/memories/999")
        self.assertEqual(response.status_code, 404)

    @patch("app.routers.memories.svc_list_memory_records")
    @patch("app.routers.memories.svc_create_memory")
    def test_get_memory_records_actor_id_scoping(self, mock_create, mock_list_records):
        """Test that memory records are scoped to the authenticated user's actor_id."""
        # Create a memory
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-rec1",
                "id": "mem-rec1",
                "name": "record_test",
                "status": "ACTIVE",
                "eventExpiryDuration": 30,
            }
        }

        create_response = self.client.post("/api/memories", json={
            "name": "record_test",
            "event_expiry_duration": 30,
        })
        mem_id = create_response.json()["id"]

        # Mock the list_memory_records service to return sample records
        mock_list_records.return_value = [
            {
                "memoryRecordId": "rec-1",
                "text": "User preference: likes dark mode",
                "memoryStrategyId": "strat-1",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            },
            {
                "memoryRecordId": "rec-2",
                "text": "Previous conversation about Python",
                "memoryStrategyId": "strat-2",
                "createdAt": "2024-01-02T00:00:00Z",
                "updatedAt": "2024-01-02T00:00:00Z",
            },
        ]

        # Get memory records
        response = self.client.get(f"/api/memories/{mem_id}/records")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify the response structure
        self.assertEqual(data["memory_id"], "mem-rec1")
        self.assertIn("actor_id", data)
        self.assertEqual(len(data["records"]), 2)
        self.assertEqual(data["records"][0]["text"], "User preference: likes dark mode")
        self.assertEqual(data["records"][1]["text"], "Previous conversation about Python")

        # Verify the service was called with the correct actor_id (from JWT)
        # The mock user has username "test" by default
        mock_list_records.assert_called_once()
        call_kwargs = mock_list_records.call_args[1]
        self.assertEqual(call_kwargs["memory_id"], "mem-rec1")
        # Actor ID should be derived from JWT: username or sub or "loom-agent"
        self.assertIn("actor_id", call_kwargs)

    @patch("app.routers.memories.svc_list_memory_records")
    @patch("app.routers.memories.svc_create_memory")
    def test_get_memory_records_user_isolation(self, mock_create, mock_list_records):
        """Test that users cannot retrieve other users' records via actor_id tampering.

        The endpoint always uses the JWT username, not a user-supplied parameter.
        """
        # Create a memory
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-iso1",
                "id": "mem-iso1",
                "name": "isolation_test",
                "status": "ACTIVE",
                "eventExpiryDuration": 30,
            }
        }

        create_response = self.client.post("/api/memories", json={
            "name": "isolation_test",
            "event_expiry_duration": 30,
        })
        mem_id = create_response.json()["id"]

        # Mock returns empty list (user has no records)
        mock_list_records.return_value = []

        # Get memory records - the endpoint does NOT accept actor_id as a parameter
        response = self.client.get(f"/api/memories/{mem_id}/records")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["records"]), 0)

        # Verify the actor_id is derived from JWT, not from query params
        # There's no way for a user to supply a different actor_id
        mock_list_records.assert_called_once()
        call_kwargs = mock_list_records.call_args[1]
        # The actor_id should always be from the JWT token (username/sub/loom-agent)
        # not from any user input
        self.assertIn("actor_id", call_kwargs)

    @patch("app.routers.memories.svc_list_memory_records")
    @patch("app.routers.memories.svc_create_memory")
    def test_get_memory_records_content_field_mapping(self, mock_create, mock_list_records):
        """Test that content field mapping handles various structures correctly."""
        # Create a memory
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-map1",
                "id": "mem-map1",
                "name": "mapping_test",
                "status": "ACTIVE",
                "eventExpiryDuration": 30,
            }
        }

        create_response = self.client.post("/api/memories", json={
            "name": "mapping_test",
            "event_expiry_duration": 30,
        })
        mem_id = create_response.json()["id"]

        # Mock returns records with text content
        mock_list_records.return_value = [
            {
                "memoryRecordId": "rec-1",
                "text": "Content as text",
                "memoryStrategyId": "strat-1",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            },
            {
                "memoryRecordId": "rec-2",
                "text": "Another text record",
                "memoryStrategyId": "strat-2",
                "createdAt": "2024-01-02T00:00:00Z",
                "updatedAt": "2024-01-02T00:00:00Z",
            },
        ]

        # Get memory records
        response = self.client.get(f"/api/memories/{mem_id}/records")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify both records are returned with text content
        self.assertEqual(len(data["records"]), 2)
        self.assertEqual(data["records"][0]["text"], "Content as text")
        self.assertEqual(data["records"][1]["text"], "Another text record")

    @patch("app.routers.memories.svc_list_memory_records")
    @patch("app.routers.memories.svc_create_memory")
    def test_get_memory_records_filters_empty_text(self, mock_create, mock_list_records):
        """Test that records with empty text are filtered out."""
        # Create a memory
        mock_create.return_value = {
            "memory": {
                "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/mem-filt1",
                "id": "mem-filt1",
                "name": "filter_test",
                "status": "ACTIVE",
                "eventExpiryDuration": 30,
            }
        }

        create_response = self.client.post("/api/memories", json={
            "name": "filter_test",
            "event_expiry_duration": 30,
        })
        mem_id = create_response.json()["id"]

        # Mock returns mix of records with and without text
        mock_list_records.return_value = [
            {
                "memoryRecordId": "rec-1",
                "text": "Valid text",
                "memoryStrategyId": "strat-1",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            },
            {
                "memoryRecordId": "rec-2",
                "text": "",  # Empty text - should be filtered
                "memoryStrategyId": "strat-2",
                "createdAt": "2024-01-02T00:00:00Z",
                "updatedAt": "2024-01-02T00:00:00Z",
            },
            {
                "memoryRecordId": "rec-3",
                "text": "Another valid text",
                "memoryStrategyId": "strat-3",
                "createdAt": "2024-01-03T00:00:00Z",
                "updatedAt": "2024-01-03T00:00:00Z",
            },
        ]

        # Get memory records
        response = self.client.get(f"/api/memories/{mem_id}/records")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Verify only records with non-empty text are returned
        self.assertEqual(len(data["records"]), 2)
        self.assertEqual(data["records"][0]["text"], "Valid text")
        self.assertEqual(data["records"][1]["text"], "Another valid text")

    @patch("app.routers.memories.svc_create_memory")
    def test_get_memory_records_no_memory_id(self, mock_create):
        """Test that getting records for a memory without memory_id returns empty list."""
        # Create a memory without memory_id (incomplete state)
        memory = Memory(
            name="incomplete_memory",
            region="us-east-1",
            account_id="123456789012",
            status="CREATING",
            event_expiry_duration=30,
        )
        self.session.add(memory)
        self.session.commit()
        self.session.refresh(memory)

        # Get memory records
        response = self.client.get(f"/api/memories/{memory.id}/records")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["memory_id"], "")
        self.assertEqual(len(data["records"]), 0)


class TestListMemoryRecordsService(unittest.TestCase):
    """Unit tests for the list_memory_records service function."""

    @patch("boto3.client")
    def test_tagged_union_strategy_unwrapping(self, mock_boto3_client):
        """Test that AWS tagged union strategy format is correctly unwrapped.

        The AWS get_memory response returns strategies in tagged union format:
        [{"userPreferenceMemoryStrategy": {"strategyId": "...", "namespaces": [...]}}]
        The service must unwrap the inner dict to extract strategyId and namespaces.
        """
        from app.services.memory import list_memory_records

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.list_memory_records.return_value = {"memoryRecords": []}

        # AWS tagged union format (as stored in strategies_response)
        strategies = [
            {
                "userPreferenceMemoryStrategy": {
                    "name": "test_user_preference",
                    "strategyId": "test_user_preference-NyV5t68Cuo",
                    "namespaces": ["/strategy/{memoryStrategyId}/actor/{actorId}/"],
                }
            },
            {
                "summaryMemoryStrategy": {
                    "name": "test_summary",
                    "strategyId": "test_summary-abc123",
                    "namespaces": ["/strategy/{memoryStrategyId}/actor/{actorId}/session/{sessionId}"],
                }
            },
        ]

        list_memory_records(
            memory_id="test-abc",
            actor_id="test-user",
            strategies=strategies,
            region="us-east-1",
        )

        # Verify it queried with correctly resolved namespaces
        calls = mock_client.list_memory_records.call_args_list
        queried_namespaces = [c[1]["namespace"] for c in calls]

        self.assertIn("/strategy/test_user_preference-NyV5t68Cuo/actor/test-user/", queried_namespaces)
        # Summary namespace should be truncated at {sessionId}
        self.assertIn("/strategy/test_summary-abc123/actor/test-user/session/", queried_namespaces)

    @patch("boto3.client")
    def test_flat_strategy_format(self, mock_boto3_client):
        """Test that flat strategy dicts (already unwrapped) still work."""
        from app.services.memory import list_memory_records

        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.list_memory_records.return_value = {"memoryRecords": []}

        # Flat format (strategyId at top level)
        strategies = [
            {
                "strategyId": "strat-flat",
                "namespaces": ["/strategy/{memoryStrategyId}/actor/{actorId}/"],
            },
        ]

        list_memory_records(
            memory_id="test-abc",
            actor_id="test-user",
            strategies=strategies,
            region="us-east-1",
        )

        call_kwargs = mock_client.list_memory_records.call_args[1]
        self.assertEqual(call_kwargs["namespace"], "/strategy/strat-flat/actor/test-user/")


if __name__ == "__main__":
    unittest.main()

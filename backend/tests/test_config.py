"""Integration tests for /api/config/llm endpoints.

Uses FastAPI TestClient with mocked Neo4j and LLM internals.
All three endpoints are covered: GET /llm, POST /llm, POST /llm/test.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")

SID = "eeeeeeee-0000-0000-0000-000000000005"

_mock_db = MagicMock()
_mock_db.get_graph.return_value = MagicMock(nodes=[], edges=[])


@pytest.fixture(scope="module")
def client():
    with patch("neo4j_client.get_db", return_value=_mock_db), \
         patch("neo4j_client.Neo4jClient.__init__", return_value=None), \
         patch("neo4j_client._instance", _mock_db):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture(scope="module")
def token(client):
    resp = client.post("/api/auth/session", json={"role": "clinician", "session_id": SID})
    assert resp.status_code == 200
    return resp.json()["token"]


# ── GET /api/config/llm ───────────────────────────────────────────────────────

class TestGetLLMConfig:
    def test_returns_200_with_expected_fields(self, client, token):
        resp = client.get("/api/config/llm", headers={"X-Session-Token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "model" in data
        assert "api_key_set" in data

    def test_api_key_value_not_in_response(self, client, token):
        resp = client.get("/api/config/llm", headers={"X-Session-Token": token})
        data = resp.json()
        assert "api_key" not in data

    def test_api_key_set_is_bool(self, client, token):
        resp = client.get("/api/config/llm", headers={"X-Session-Token": token})
        assert isinstance(resp.json()["api_key_set"], bool)

    def test_no_token_returns_401(self, client):
        resp = client.get("/api/config/llm")
        assert resp.status_code == 401


# ── POST /api/config/llm ──────────────────────────────────────────────────────

class TestUpdateLLMConfig:
    def test_valid_provider_returns_200(self, client, token):
        info = {"provider": "groq", "model": "llama-3.3-70b-versatile", "api_key_set": True}
        with patch("routers.config.reconfigure"), \
             patch("routers.config.get_provider_info", return_value=info):
            resp = client.post(
                "/api/config/llm",
                json={"provider": "groq", "api_key": "gsk_test", "model": "", "base_url": ""},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 200
        assert resp.json()["provider"] == "groq"

    def test_all_six_providers_accepted(self, client, token):
        providers = ["openai", "groq", "mistral", "anthropic", "ollama", "openai_compatible"]
        for p in providers:
            info = {"provider": p, "model": "some-model", "api_key_set": False}
            with patch("routers.config.reconfigure"), \
                 patch("routers.config.get_provider_info", return_value=info):
                resp = client.post(
                    "/api/config/llm",
                    json={"provider": p, "api_key": "key",
                          "model": "m", "base_url": "http://x/v1"},
                    headers={"X-Session-Token": token},
                )
            assert resp.status_code == 200, f"provider={p} should be accepted"

    def test_unknown_provider_returns_422(self, client, token):
        resp = client.post(
            "/api/config/llm",
            json={"provider": "totally_fake", "api_key": "x"},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422
        assert "totally_fake" in resp.json()["detail"]

    def test_openai_compatible_without_base_url_returns_422(self, client, token):
        with patch("routers.config.reconfigure",
                   side_effect=RuntimeError("provider=openai_compatible requires base_url")):
            resp = client.post(
                "/api/config/llm",
                json={"provider": "openai_compatible", "api_key": "k",
                      "model": "gpt-4o", "base_url": ""},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 422
        assert "base_url" in resp.json()["detail"].lower()

    def test_no_token_returns_401(self, client):
        resp = client.post("/api/config/llm", json={"provider": "openai"})
        assert resp.status_code == 401

    def test_missing_provider_field_returns_422(self, client, token):
        resp = client.post(
            "/api/config/llm",
            json={"api_key": "sk-test"},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_unexpected_error_returns_500_without_stack_trace(self, client, token):
        with patch("routers.config.reconfigure",
                   side_effect=Exception("internal db failure")):
            resp = client.post(
                "/api/config/llm",
                json={"provider": "openai", "api_key": "sk-x"},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 500
        # Must NOT leak internal exception details
        detail = resp.json().get("detail", "")
        assert "internal db failure" not in detail


# ── POST /api/config/llm/test ─────────────────────────────────────────────────

class TestTestLLMConfig:
    def test_successful_call_returns_ok_true(self, client, token):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        with patch("routers.config.sync_client") as mock_sync, \
             patch("routers.config.get_model", return_value="gpt-4o"):
            mock_sync.chat.completions.create.return_value = mock_resp
            resp = client.post(
                "/api/config/llm/test",
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["latency_ms"], int)
        assert data["latency_ms"] >= 0

    def test_llm_error_returns_ok_false(self, client, token):
        with patch("routers.config.sync_client") as mock_sync, \
             patch("routers.config.get_model", return_value="gpt-4o"):
            mock_sync.chat.completions.create.side_effect = Exception("Connection refused")
            resp = client.post(
                "/api/config/llm/test",
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 200  # test endpoint never 500s; error is in payload
        data = resp.json()
        assert data["ok"] is False
        assert "error" in data
        assert "Connection refused" in data["error"]

    def test_no_token_returns_401(self, client):
        resp = client.post("/api/config/llm/test")
        assert resp.status_code == 401

    def test_latency_ms_present_on_failure(self, client, token):
        with patch("routers.config.sync_client") as mock_sync, \
             patch("routers.config.get_model", return_value="gpt-4o"):
            mock_sync.chat.completions.create.side_effect = TimeoutError("timed out")
            resp = client.post(
                "/api/config/llm/test",
                headers={"X-Session-Token": token},
            )
        data = resp.json()
        assert "latency_ms" in data

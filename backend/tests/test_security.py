"""Integration-style security tests using FastAPI TestClient.

Covers:
- Auth middleware: 401 on missing token, 403 on session_id mismatch
- Body session_id bypass prevention (chat + intake endpoints)
- Input validation: request bodies exceeding max_length → 422
- PATCH/DELETE /claim ownership enforcement
"""
import os
import json
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")

from fastapi.testclient import TestClient

# Patch Neo4j + LLM before importing the app so they don't connect
_mock_db = MagicMock()
_mock_db.list_sessions.return_value = []
_mock_db.get_all_claims_for_session.return_value = []
_mock_db.get_context_for_query.return_value = {}
_mock_db.store_claims.return_value = []
_mock_db.get_claim_by_id.return_value = None


@pytest.fixture(scope="module")
def client():
    with patch("neo4j_client.get_db", return_value=_mock_db), \
         patch("neo4j_client.Neo4jClient.__init__", return_value=None), \
         patch("neo4j_client._instance", _mock_db):
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture(scope="module")
def token(client):
    """Obtain a valid session token bound to a known session_id."""
    resp = client.post("/api/auth/session", json={"role": "clinician", "session_id": "aaaaaaaa-0000-0000-0000-000000000001"})
    assert resp.status_code == 200
    return resp.json()["token"]


@pytest.fixture(scope="module")
def other_token(client):
    """Token bound to a DIFFERENT session_id."""
    resp = client.post("/api/auth/session", json={"role": "clinician", "session_id": "bbbbbbbb-0000-0000-0000-000000000002"})
    assert resp.status_code == 200
    return resp.json()["token"]


OWN_SID   = "aaaaaaaa-0000-0000-0000-000000000001"
OTHER_SID = "bbbbbbbb-0000-0000-0000-000000000002"


# ── Auth middleware ───────────────────────────────────────────────────────────

class TestAuthMiddleware:
    def test_no_token_returns_401(self, client):
        resp = client.get(f"/api/graph/{OWN_SID}")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        resp = client.get(f"/api/graph/{OWN_SID}",
                          headers={"X-Session-Token": "garbage"})
        assert resp.status_code == 401

    def test_valid_token_own_session_passes(self, client, token):
        resp = client.get(f"/api/graph/{OWN_SID}",
                          headers={"X-Session-Token": token})
        # May be 200 or 500 (no real Neo4j) but NOT 401/403
        assert resp.status_code not in (401, 403)

    def test_valid_token_foreign_session_returns_403(self, client, token):
        """Token is bound to OWN_SID; accessing OTHER_SID must be rejected."""
        resp = client.get(f"/api/graph/{OTHER_SID}",
                          headers={"X-Session-Token": token})
        assert resp.status_code == 403

    def test_health_endpoint_requires_no_token(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_auth_session_endpoint_requires_no_token(self, client):
        resp = client.post("/api/auth/session", json={"role": "clinician"})
        assert resp.status_code == 200

    def test_bearer_token_accepted(self, client, token):
        resp = client.get(f"/api/graph/{OWN_SID}",
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code not in (401, 403)


# ── Body session_id bypass prevention ────────────────────────────────────────

class TestBodySessionBypass:
    def test_chat_wrong_session_id_in_body_returns_422(self, client, token):
        """Sending a foreign session_id in the chat body must be rejected."""
        resp = client.post(
            "/api/chat",
            json={"message": "Hello", "session_id": OTHER_SID, "history": []},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_chat_own_session_id_passes_validation(self, client, token):
        """Sending own session_id must pass validation (may fail later in LLM)."""
        resp = client.post(
            "/api/chat",
            json={"message": "Hello", "session_id": OWN_SID, "history": []},
            headers={"X-Session-Token": token},
        )
        # 422 would mean our check wrongly rejected it; 401/403 means auth issue
        assert resp.status_code not in (422, 401, 403)

    def test_intake_conversation_wrong_session_returns_422(self, client, token):
        resp = client.post(
            "/api/intake/conversation",
            json={"text": "Patient has fever", "session_id": OTHER_SID},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_intake_measurements_wrong_session_returns_422(self, client, token):
        resp = client.post(
            "/api/intake/measurements",
            json={"measurements": [], "session_id": OTHER_SID},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_intake_clinical_wrong_session_returns_422(self, client, token):
        resp = client.post(
            "/api/intake/clinical",
            json={"inputs": [], "session_id": OTHER_SID},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422


# ── Input validation ──────────────────────────────────────────────────────────

class TestInputValidation:
    def test_chat_message_too_long_returns_422(self, client, token):
        resp = client.post(
            "/api/chat",
            json={"message": "A" * 10_001, "session_id": OWN_SID, "history": []},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_chat_empty_message_returns_422(self, client, token):
        resp = client.post(
            "/api/chat",
            json={"message": "", "session_id": OWN_SID, "history": []},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_hypothesis_counterfactual_too_long_returns_422(self, client, token):
        resp = client.post(
            f"/api/graph/{OWN_SID}/counterfactual/hypothesis",
            json={"hypothesis": "H" * 10_001},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_manual_claim_too_long_returns_422(self, client, token):
        resp = client.post(
            f"/api/graph/{OWN_SID}/claims",
            json={"text": "X" * 5_001},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_conflict_explain_message_too_long_returns_422(self, client, token):
        resp = client.post(
            f"/api/graph/{OWN_SID}/conflicts/explain",
            json={"type": "negation", "severity": "error",
                  "message": "M" * 5_001, "affected_claim_ids": []},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422


# ── PATCH/DELETE claim ownership ─────────────────────────────────────────────

class TestClaimOwnership:
    def test_patch_claim_belonging_to_foreign_session_returns_403(self, client, token):
        """Claim exists but belongs to a different session → 403."""
        foreign_claim = {"id": "claim-1", "session_id": OTHER_SID, "text": "x"}
        with patch("routers.graph.get_db") as mock_get_db:
            mock_get_db.return_value.get_claim_by_id.return_value = foreign_claim
            resp = client.patch(
                "/api/graph/claim/claim-1",
                json={"status": "confirmed"},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 403

    def test_delete_claim_belonging_to_foreign_session_returns_403(self, client, token):
        """Claim exists but belongs to a different session → 403."""
        foreign_claim = {"id": "claim-1", "session_id": OTHER_SID, "text": "x"}
        with patch("routers.graph.get_db") as mock_get_db:
            mock_get_db.return_value.get_claim_by_id.return_value = foreign_claim
            resp = client.delete(
                "/api/graph/claim/claim-1",
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 403

    def test_patch_own_claim_not_rejected_by_ownership_check(self, client, token):
        """Claim belongs to own session → ownership check passes."""
        own_claim = {"id": "claim-2", "session_id": OWN_SID, "text": "x"}
        with patch("routers.graph.get_db") as mock_get_db:
            db = mock_get_db.return_value
            db.get_claim_by_id.return_value = own_claim
            db.update_claim.return_value = None
            resp = client.patch(
                "/api/graph/claim/claim-2",
                json={"status": "confirmed"},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code not in (401, 403)

    def test_patch_nonexistent_claim_returns_404(self, client, token):
        with patch("routers.graph.get_db") as mock_get_db:
            mock_get_db.return_value.get_claim_by_id.return_value = None
            resp = client.patch(
                "/api/graph/claim/does-not-exist",
                json={"status": "confirmed"},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 404

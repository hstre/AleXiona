"""Router integration tests for /api/graph endpoints.

Uses FastAPI TestClient with a mocked Neo4j client and no real LLM calls.
Covers the happy paths and key guard conditions for the graph router.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")

from models import GraphData  # noqa: E402

# ── Shared mock DB ────────────────────────────────────────────────────────────

_GRAPH = GraphData(nodes=[], edges=[])

_mock_db = MagicMock()
_mock_db.get_graph.return_value = _GRAPH
_mock_db.get_all_claims_for_session.return_value = []
_mock_db.get_context_for_query.return_value = ""
_mock_db.store_claims.return_value = ["claim-id-001"]
_mock_db.get_claim_by_id.return_value = None
_mock_db.update_claim.return_value = None
_mock_db.delete_claim.return_value = None
_mock_db.link_explicit_derived_from.return_value = None

SID = "cccccccc-0000-0000-0000-000000000003"


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


# ── GET /{session_id} ─────────────────────────────────────────────────────────

class TestGetGraph:
    def test_returns_200_with_empty_graph(self, client, token):
        _mock_db.get_graph.return_value = _GRAPH
        resp = client.get(f"/api/graph/{SID}", headers={"X-Session-Token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data

    def test_no_token_returns_401(self, client):
        resp = client.get(f"/api/graph/{SID}")
        assert resp.status_code == 401

    def test_foreign_session_returns_403(self, client, token):
        """Token is bound to SID; accessing a different session_id must be 403."""
        foreign = "dddddddd-0000-0000-0000-000000000004"
        resp = client.get(f"/api/graph/{foreign}", headers={"X-Session-Token": token})
        assert resp.status_code == 403


# ── GET /{session_id}/conflicts ───────────────────────────────────────────────

class TestGetConflicts:
    def test_returns_200_with_no_claims(self, client, token):
        _mock_db.get_all_claims_for_session.return_value = []
        resp = client.get(f"/api/graph/{SID}/conflicts", headers={"X-Session-Token": token})
        assert resp.status_code == 200
        assert resp.json() == []


# ── POST /{session_id}/claims ─────────────────────────────────────────────────

class TestAddManualClaim:
    def test_valid_claim_returns_created(self, client, token):
        _mock_db.store_claims.return_value = ["new-claim-id"]
        resp = client.post(
            f"/api/graph/{SID}/claims",
            json={"text": "Patient has fever 38.5°C"},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 200
        assert resp.json().get("status") == "created"

    def test_empty_text_returns_422(self, client, token):
        resp = client.post(
            f"/api/graph/{SID}/claims",
            json={"text": ""},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_text_exceeding_max_length_returns_422(self, client, token):
        resp = client.post(
            f"/api/graph/{SID}/claims",
            json={"text": "x" * 5_001},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_invalid_derived_from_returns_422(self, client, token):
        _mock_db.get_all_claims_for_session.return_value = []
        resp = client.post(
            f"/api/graph/{SID}/claims",
            json={"text": "Derived finding", "derived_from": ["nonexistent-id"]},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_temporal_inconsistency_returns_422(self, client, token):
        """A derived claim whose time_offset is earlier than its source must be rejected."""
        _mock_db.get_all_claims_for_session.return_value = [
            {"id": "src-1", "time_offset": "t+48h"},
        ]
        resp = client.post(
            f"/api/graph/{SID}/claims",
            json={
                "text": "Earlier derived claim",
                "time_offset": "t+24h",
                "derived_from": ["src-1"],
            },
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422


# ── PATCH /claim/{claim_id} ───────────────────────────────────────────────────

class TestUpdateClaim:
    def test_own_claim_returns_200(self, client, token):
        with patch("routers.graph.get_db") as mock:
            db = mock.return_value
            db.get_claim_by_id.return_value = {"id": "c1", "session_id": SID, "text": "x"}
            db.update_claim.return_value = None
            resp = client.patch(
                "/api/graph/claim/c1",
                json={"status": "confirmed"},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 200

    def test_nonexistent_claim_returns_404(self, client, token):
        with patch("routers.graph.get_db") as mock:
            mock.return_value.get_claim_by_id.return_value = None
            resp = client.patch(
                "/api/graph/claim/does-not-exist",
                json={"status": "confirmed"},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 404

    def test_foreign_claim_returns_403(self, client, token):
        other_sid = "eeeeeeee-0000-0000-0000-000000000005"
        with patch("routers.graph.get_db") as mock:
            mock.return_value.get_claim_by_id.return_value = {
                "id": "c2", "session_id": other_sid, "text": "x"
            }
            resp = client.patch(
                "/api/graph/claim/c2",
                json={"status": "confirmed"},
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 403


# ── DELETE /claim/{claim_id} ──────────────────────────────────────────────────

class TestDeleteClaim:
    def test_own_claim_returns_200(self, client, token):
        with patch("routers.graph.get_db") as mock:
            db = mock.return_value
            db.get_claim_by_id.return_value = {"id": "c3", "session_id": SID, "text": "x"}
            db.delete_claim.return_value = None
            resp = client.delete(
                "/api/graph/claim/c3",
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 200

    def test_nonexistent_claim_returns_404(self, client, token):
        with patch("routers.graph.get_db") as mock:
            mock.return_value.get_claim_by_id.return_value = None
            resp = client.delete(
                "/api/graph/claim/ghost",
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 404

    def test_foreign_claim_returns_403(self, client, token):
        other_sid = "ffffffff-0000-0000-0000-000000000006"
        with patch("routers.graph.get_db") as mock:
            mock.return_value.get_claim_by_id.return_value = {
                "id": "c4", "session_id": other_sid, "text": "x"
            }
            resp = client.delete(
                "/api/graph/claim/c4",
                headers={"X-Session-Token": token},
            )
        assert resp.status_code == 403

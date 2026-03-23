"""Router integration tests for /api/intake endpoints.

The measurement route is fully rule-based (no LLM), so it can be tested
end-to-end with a mocked DB.  The conversation and clinical routes invoke
the LLM, so only the guard conditions (empty text, body session mismatch)
are tested here.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")

_mock_db = MagicMock()
_mock_db.store_claims.return_value = ["claim-001"]

SID = "11111111-aaaa-0000-0000-000000000001"

MEASUREMENT = {
    "id": "m1",
    "device_type": "wearable",
    "device_name": "Apple Watch",
    "token": "heart_rate",
    "value": 72.0,
    "unit": "bpm",
}

OBSERVATION = {
    "id": "o1",
    "raw_text": "Ich fühle mich schwindelig",
    "source_type": "patient_report",
}


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


# ── POST /api/intake/measurements ─────────────────────────────────────────────

class TestIntakeMeasurements:
    """Measurement ingestion is rule-based: no LLM → fully testable."""

    def test_single_measurement_returns_200(self, client, token):
        resp = client.post(
            "/api/intake/measurements",
            json={
                "session_id": SID,
                "measurements": [MEASUREMENT],
                "observations": [],
            },
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "claims" in data
        assert data["session_id"] == SID

    def test_empty_measurements_returns_200(self, client, token):
        resp = client.post(
            "/api/intake/measurements",
            json={"session_id": SID, "measurements": [], "observations": []},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 200
        assert resp.json()["claims"] == []

    def test_observation_only_returns_200(self, client, token):
        resp = client.post(
            "/api/intake/measurements",
            json={"session_id": SID, "measurements": [], "observations": [OBSERVATION]},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 200
        assert len(resp.json()["claims"]) >= 1

    def test_wrong_session_in_body_returns_422(self, client, token):
        other = "22222222-bbbb-0000-0000-000000000002"
        resp = client.post(
            "/api/intake/measurements",
            json={"session_id": other, "measurements": [], "observations": []},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_no_token_returns_401(self, client):
        resp = client.post(
            "/api/intake/measurements",
            json={"session_id": SID, "measurements": [], "observations": []},
        )
        assert resp.status_code == 401

    def test_trend_detection_with_three_points(self, client, token):
        """Three measurements for the same token trigger trend detection."""
        import datetime
        base = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        measurements = [
            {**MEASUREMENT, "id": f"m{i}", "value": 70.0 + i * 5,
             "event_time": (base + datetime.timedelta(hours=i * 12)).isoformat()}
            for i in range(3)
        ]
        resp = client.post(
            "/api/intake/measurements",
            json={"session_id": SID, "measurements": measurements, "observations": []},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        # 3 point-in-time claims + 1 trend claim
        assert len(data["claims"]) >= 3
        assert "trend_signals" in data


# ── POST /api/intake/conversation ─────────────────────────────────────────────

class TestIntakeConversation:
    """Only guard conditions — LLM calls are not mocked here."""

    def test_empty_text_returns_422(self, client, token):
        resp = client.post(
            "/api/intake/conversation",
            json={"session_id": SID, "text": "   "},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_wrong_session_in_body_returns_422(self, client, token):
        other = "33333333-cccc-0000-0000-000000000003"
        resp = client.post(
            "/api/intake/conversation",
            json={"session_id": other, "text": "Patient feels dizzy"},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_no_token_returns_401(self, client):
        resp = client.post(
            "/api/intake/conversation",
            json={"session_id": SID, "text": "Test"},
        )
        assert resp.status_code == 401

    def test_text_exceeding_max_length_returns_422(self, client, token):
        resp = client.post(
            "/api/intake/conversation",
            json={"session_id": SID, "text": "x" * 50_001},
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422


# ── POST /api/intake/clinical ─────────────────────────────────────────────────

class TestIntakeClinical:
    """Only guard conditions — LLM calls are not mocked here."""

    def test_empty_input_text_returns_422(self, client, token):
        resp = client.post(
            "/api/intake/clinical",
            json={
                "session_id": SID,
                "inputs": [{"input_type": "lab", "text": ""}],
            },
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_wrong_session_in_body_returns_422(self, client, token):
        other = "44444444-dddd-0000-0000-000000000004"
        resp = client.post(
            "/api/intake/clinical",
            json={
                "session_id": other,
                "inputs": [{"input_type": "lab", "text": "CRP 45 mg/L"}],
            },
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

    def test_no_token_returns_401(self, client):
        resp = client.post(
            "/api/intake/clinical",
            json={
                "session_id": SID,
                "inputs": [{"input_type": "lab", "text": "CRP elevated"}],
            },
        )
        assert resp.status_code == 401

    def test_input_text_exceeding_max_length_returns_422(self, client, token):
        resp = client.post(
            "/api/intake/clinical",
            json={
                "session_id": SID,
                "inputs": [{"input_type": "lab", "text": "x" * 20_001}],
            },
            headers={"X-Session-Token": token},
        )
        assert resp.status_code == 422

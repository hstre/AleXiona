"""Unit tests for neo4j_client helpers that don't require a live Neo4j instance.

Tests cover:
- _key_terms() helper
- get_db() singleton behaviour (mocked driver)
- Neo4jClient.update_claim() field mapping
- link_derived_from() key-term overlap logic
"""
import json
from unittest.mock import MagicMock, patch, call
import pytest

# ── _key_terms ────────────────────────────────────────────────────────────────

from neo4j_client import _key_terms


def test_key_terms_basic():
    result = _key_terms("Patient shows elevated troponin levels")
    assert "patient" in result
    assert "shows" in result      # 5 chars — included by ≥4 rule
    assert "elevated" in result
    assert "troponin" in result
    assert "levels" in result


def test_key_terms_short_words_excluded():
    result = _key_terms("No ST elevation seen")
    assert "seen" in result  # exactly 4 chars
    assert "No" not in result
    assert "ST" not in result


def test_key_terms_returns_lowercase():
    result = _key_terms("Troponin TROPONIN troponin")
    assert result == {"troponin"}


def test_key_terms_empty_string():
    assert _key_terms("") == set()


def test_key_terms_only_short_words():
    assert _key_terms("No ST in") == set()


def test_key_terms_overlap():
    a = _key_terms("elevated troponin levels")
    b = _key_terms("troponin levels increased")
    assert len(a & b) >= 2  # 'troponin', 'levels'


# ── get_db singleton ──────────────────────────────────────────────────────────

def test_get_db_returns_same_instance():
    """get_db() must return the same object on repeated calls."""
    import neo4j_client as nc
    original = nc._instance
    nc._instance = None
    fake = MagicMock()
    try:
        with patch.object(nc, 'Neo4jClient', return_value=fake) as MockClass:
            inst1 = nc.get_db()
            inst2 = nc.get_db()
            assert inst1 is inst2
            assert MockClass.call_count == 1  # constructed only once
    finally:
        nc._instance = original


def test_get_db_reuses_existing_instance(monkeypatch):
    """get_db() must not construct a new instance when one already exists."""
    import neo4j_client as nc
    fake = MagicMock()
    original = nc._instance
    nc._instance = fake
    try:
        result = nc.get_db()
        assert result is fake
    finally:
        nc._instance = original


# ── update_claim ──────────────────────────────────────────────────────────────

def _make_client_with_mock_session():
    """Return a Neo4jClient whose driver is fully mocked."""
    import neo4j_client as nc
    with patch.object(nc.Neo4jClient, '__init__', return_value=None):
        client = nc.Neo4jClient.__new__(nc.Neo4jClient)

    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    client.driver = mock_driver
    return client, mock_session


def test_update_claim_single_field():
    client, session = _make_client_with_mock_session()
    client.update_claim("abc-123", {"text": "New text"})
    session.run.assert_called_once()
    cypher, *_ = session.run.call_args[0]
    assert "c.text = $text" in cypher
    assert "abc-123" in str(session.run.call_args)


def test_update_claim_multiple_fields():
    client, session = _make_client_with_mock_session()
    client.update_claim("abc-123", {
        "text": "Updated",
        "evidence_support_score": 0.9,
        "status": "resolved",
    })
    session.run.assert_called_once()
    cypher = session.run.call_args[0][0]
    assert "c.text = $text" in cypher
    assert "c.evidence_support_score = $evidence_support_score" in cypher
    assert "c.status = $status" in cypher


def test_update_claim_enum_serialised():
    """Enum values must be converted to their .value string before Cypher."""
    from models import ClaimStatus
    client, session = _make_client_with_mock_session()
    client.update_claim("id1", {"status": ClaimStatus.resolved})
    kwargs = session.run.call_args[1]
    assert kwargs["status"] == "resolved"


def test_update_claim_noop_when_empty():
    """Empty field dict should not execute any Cypher."""
    client, session = _make_client_with_mock_session()
    client.update_claim("id1", {})
    session.run.assert_not_called()


# ── link_derived_from ─────────────────────────────────────────────────────────

def _make_session_rows(rows):
    """Return a mock Neo4j session whose .run().data() yields rows."""
    mock_result = MagicMock()
    mock_result.data.return_value = rows

    mock_session = MagicMock()
    mock_session.run.return_value = mock_result

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return mock_driver, mock_session


def test_link_derived_from_skips_when_no_old_claims():
    import neo4j_client as nc
    with patch.object(nc.Neo4jClient, '__init__', return_value=None):
        client = nc.Neo4jClient.__new__(nc.Neo4jClient)

    rows = [{"id": "new-1", "text": "troponin elevated levels seen"}]
    driver, session = _make_session_rows(rows)
    client.driver = driver

    # Only one claim (the new one) — no existing claims to link from
    client.link_derived_from(["new-1"], "sess-1")
    # Should only run the initial MATCH, no SET or MERGE
    set_calls = [c for c in session.run.call_args_list if "SET" in str(c)]
    assert len(set_calls) == 0


def test_link_derived_from_links_when_overlap():
    import neo4j_client as nc
    with patch.object(nc.Neo4jClient, '__init__', return_value=None):
        client = nc.Neo4jClient.__new__(nc.Neo4jClient)

    rows = [
        {"id": "old-1", "text": "elevated troponin levels indicate cardiac injury"},
        {"id": "new-1", "text": "troponin levels rising after admission"},
    ]
    driver, session = _make_session_rows(rows)
    client.driver = driver

    client.link_derived_from(["new-1"], "sess-1")

    # Expect SET call for derived_from JSON and MERGE for DERIVES_FROM edge
    all_calls = [str(c) for c in session.run.call_args_list]
    assert any("SET" in c and "derived_from" in c for c in all_calls)
    assert any("DERIVES_FROM" in c for c in all_calls)


def test_link_derived_from_no_link_when_insufficient_overlap():
    import neo4j_client as nc
    with patch.object(nc.Neo4jClient, '__init__', return_value=None):
        client = nc.Neo4jClient.__new__(nc.Neo4jClient)

    rows = [
        {"id": "old-1", "text": "patient has fever and chills"},
        {"id": "new-1", "text": "troponin levels rising quickly"},
    ]
    driver, session = _make_session_rows(rows)
    client.driver = driver

    client.link_derived_from(["new-1"], "sess-1")

    all_calls = [str(c) for c in session.run.call_args_list]
    assert not any("DERIVES_FROM" in c for c in all_calls)


def test_link_derived_from_noop_when_empty_list():
    import neo4j_client as nc
    with patch.object(nc.Neo4jClient, '__init__', return_value=None):
        client = nc.Neo4jClient.__new__(nc.Neo4jClient)
    client.driver = MagicMock()
    client.link_derived_from([], "sess-1")
    client.driver.session.assert_not_called()

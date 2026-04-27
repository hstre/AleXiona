"""Unit tests for lab_parser.py."""
import pytest

from lab_parser import (
    LAB_THRESHOLDS,
    lab_summary,
    parse_lab_value,
    parse_lab_values,
    qualitative_for_token,
)


def _claim(text: str, status: str = "active", claim_type: str = "lab") -> dict:
    return {"text": text, "status": status, "claim_type": claim_type}


# ── parse_lab_value ────────────────────────────────────────────────────────────

class TestParseLabValue:
    def test_crp_high(self):
        r = parse_lab_value("CRP 145 mg/L")
        assert r is not None
        assert r.token == "crp"
        assert r.value == 145.0
        assert r.qualitative == "high"

    def test_crp_normal(self):
        r = parse_lab_value("CRP 5.2 mg/L")
        assert r is not None
        assert r.qualitative == "normal"

    def test_troponin_high(self):
        r = parse_lab_value("Troponin I 0.12 µg/L")
        assert r is not None
        assert r.token == "troponin"
        assert r.qualitative == "high"

    def test_troponin_normal(self):
        r = parse_lab_value("hs-Troponin 0.01 µg/L")
        assert r is not None
        assert r.qualitative == "normal"

    def test_leukocytes_high(self):
        r = parse_lab_value("Leukocytes 14.5 G/L")
        assert r is not None
        assert r.token == "leukocytes"
        assert r.qualitative == "high"

    def test_leukocytes_low(self):
        r = parse_lab_value("WBC 2.1 G/L")
        assert r is not None
        assert r.qualitative == "low"

    def test_lactate_high(self):
        r = parse_lab_value("Lactate 4.2 mmol/L")
        assert r is not None
        assert r.qualitative == "high"

    def test_ddimer_high(self):
        r = parse_lab_value("D-Dimer 4.8 µg/mL")
        assert r is not None
        assert r.token == "ddimer"
        assert r.qualitative == "high"

    def test_temperature_high(self):
        r = parse_lab_value("Temperature 38.9°C")
        assert r is not None
        assert r.token == "temperature"
        assert r.qualitative == "high"

    def test_spo2_low(self):
        r = parse_lab_value("SpO2 88 %")
        assert r is not None
        assert r.token == "spo2"
        assert r.qualitative == "low"

    def test_heart_rate_high(self):
        r = parse_lab_value("Heart rate 115 bpm")
        assert r is not None
        assert r.token == "heart_rate"
        assert r.qualitative == "high"

    def test_german_alias(self):
        r = parse_lab_value("Leukozyten 12.0 G/L")
        assert r is not None
        assert r.token == "leukocytes"

    def test_comma_decimal(self):
        r = parse_lab_value("CRP 14,5 mg/L")
        assert r is not None
        assert r.value == pytest.approx(14.5)

    def test_no_unit(self):
        r = parse_lab_value("CRP 85")
        assert r is not None
        assert r.value == 85.0
        assert r.qualitative == "high"

    def test_returns_none_for_non_lab(self):
        assert parse_lab_value("Patient has fever and cough") is None

    def test_returns_none_for_empty(self):
        assert parse_lab_value("") is None

    def test_returns_none_no_number(self):
        # Token present but no numeric value
        assert parse_lab_value("CRP result pending") is None

    def test_bnp_high(self):
        r = parse_lab_value("BNP 350 pg/mL")
        assert r is not None
        assert r.token == "bnp"
        assert r.qualitative == "high"

    def test_result_has_clinical_note(self):
        r = parse_lab_value("CRP 145 mg/L")
        assert r is not None
        assert len(r.clinical_note) > 0

    def test_raw_text_preserved(self):
        text = "Troponin 0.05 µg/L elevated"
        r = parse_lab_value(text)
        assert r is not None
        assert r.raw == text


# ── parse_lab_values (batch) ──────────────────────────────────────────────────

class TestParseLabValues:
    def test_filters_non_lab(self):
        texts = ["CRP 145 mg/L", "Patient has fever", "D-Dimer 4.8 µg/mL"]
        results = parse_lab_values(texts)
        assert len(results) == 2
        tokens = {r.token for r in results}
        assert "crp" in tokens
        assert "ddimer" in tokens

    def test_empty_list(self):
        assert parse_lab_values([]) == []


# ── qualitative_for_token ─────────────────────────────────────────────────────

class TestQualitativeForToken:
    def test_returns_qualitative_for_active_claim(self):
        claims = [_claim("CRP 145 mg/L")]
        assert qualitative_for_token("crp", claims) == "high"

    def test_ignores_inactive_claim(self):
        claims = [_claim("CRP 145 mg/L", status="superseded")]
        assert qualitative_for_token("crp", claims) is None

    def test_returns_none_when_no_matching_claim(self):
        claims = [_claim("Temperature 38.9°C")]
        assert qualitative_for_token("crp", claims) is None

    def test_last_claim_wins(self):
        claims = [
            _claim("CRP 145 mg/L"),   # high
            _claim("CRP 4.2 mg/L"),   # normal (later)
        ]
        assert qualitative_for_token("crp", claims) == "normal"


# ── lab_summary ───────────────────────────────────────────────────────────────

class TestLabSummary:
    def test_returns_mapping(self):
        claims = [
            _claim("CRP 145 mg/L"),
            _claim("Troponin 0.12 µg/L"),
        ]
        summary = lab_summary(claims)
        assert "crp" in summary
        assert "troponin" in summary

    def test_ignores_non_active(self):
        claims = [_claim("CRP 145 mg/L", status="resolved")]
        assert lab_summary(claims) == {}

    def test_later_claim_overwrites(self):
        claims = [
            _claim("CRP 145 mg/L"),  # high → overwritten
            _claim("CRP 4 mg/L"),    # normal
        ]
        summary = lab_summary(claims)
        assert summary["crp"].qualitative == "normal"

    def test_empty_claims(self):
        assert lab_summary([]) == {}


# ── LAB_THRESHOLDS structure ──────────────────────────────────────────────────

class TestLabThresholds:
    def test_all_entries_have_aliases(self):
        for token, spec in LAB_THRESHOLDS.items():
            assert "aliases" in spec, f"{token} missing aliases"
            assert len(spec["aliases"]) > 0

    def test_all_entries_have_unit(self):
        for token, spec in LAB_THRESHOLDS.items():
            assert "unit" in spec, f"{token} missing unit"

    def test_at_least_one_threshold_per_entry(self):
        for token, spec in LAB_THRESHOLDS.items():
            has_threshold = "high" in spec or "low" in spec
            assert has_threshold, f"{token} has no high/low threshold"

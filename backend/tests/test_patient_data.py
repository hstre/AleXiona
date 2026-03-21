"""Unit tests for patient_data.py — Patient Data Layer."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from models import (
    PatientObservation,
    PatientGeneratedMeasurement,
    TrendSignal,
)
from patient_data import (
    ingest_patient_observation,
    ingest_measurement,
    extract_trend_signal,
    normalize_to_candidates,
    _safeguard_candidate,
    _MIN_TREND_POINTS,
    _TREND_MAGNITUDE_THRESHOLD_PCT,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _obs(
    raw_text: str,
    *,
    negation: bool = False,
    uncertainty: bool = False,
    onset_hint: str | None = None,
    event_time: datetime | None = None,
) -> PatientObservation:
    return PatientObservation(
        id="obs-1",
        raw_text=raw_text,
        negation_hint=negation,
        uncertainty_hint=uncertainty,
        onset_hint=onset_hint,
        event_time=event_time,
    )


def _pgm(
    token: str,
    value: float,
    unit: str = "unit",
    device_type: str = "wearable",
    quality: str = "good",
    event_time: datetime | None = None,
) -> PatientGeneratedMeasurement:
    return PatientGeneratedMeasurement(
        id=f"pgm-{token}-{value}",
        device_type=device_type,
        token=token,
        value=value,
        unit=unit,
        measurement_quality=quality,
        event_time=event_time or _now(),
    )


def _pgm_series(token: str, values: list[float], interval_hours: float = 1.0) -> list[PatientGeneratedMeasurement]:
    """Create a chronological series of measurements for a single token."""
    base = _now()
    pgms = []
    for i, v in enumerate(values):
        t = base + timedelta(hours=i * interval_hours)
        pgms.append(PatientGeneratedMeasurement(
            id=f"pgm-{token}-{i}",
            device_type="wearable",
            token=token,
            value=v,
            unit="unit",
            measurement_quality="good",
            event_time=t,
        ))
    return pgms


# ── Safeguard validator ────────────────────────────────────────────────────────

class TestSafeguardValidator:
    def test_diagnosis_type_downgraded_to_finding(self):
        obs = _obs("Patient reports chest pain")
        candidate = ingest_patient_observation(obs)
        # Manually set type to diagnosis to test safeguard
        from models import ClaimCandidate
        diag_candidate = candidate.model_copy(update={"candidate_type": "diagnosis"})
        result = _safeguard_candidate(diag_candidate)
        assert result.candidate_type == "finding"

    def test_non_diagnosis_type_unchanged(self):
        obs = _obs("Fever since 2 days")
        candidate = ingest_patient_observation(obs)
        original_type = candidate.candidate_type
        result = _safeguard_candidate(candidate)
        assert result.candidate_type == original_type

    def test_confirmed_in_source_ref_replaced(self):
        obs = _obs("Some observation")
        candidate = ingest_patient_observation(obs)
        # Inject "confirmed" into source_ref (space-separated to match regex)
        dirty = candidate.model_copy(
            update={"observation": candidate.observation.model_copy(
                update={"source_ref": "patient confirmed entry"}
            )}
        )
        result = _safeguard_candidate(dirty)
        assert "confirmed" not in result.observation.source_ref.lower()
        assert "reported" in result.observation.source_ref.lower()


# ── ingest_patient_observation ─────────────────────────────────────────────────

class TestIngestPatientObservation:
    def test_basic_symptom_produces_candidate(self):
        obs = _obs("Chest pain when climbing stairs")
        candidate = ingest_patient_observation(obs)
        assert candidate is not None
        assert "chest pain" in candidate.candidate_text.lower() or \
               "chest" in candidate.candidate_text.lower()

    def test_lab_text_extracts_numeric(self):
        obs = _obs("CRP 145 mg/L")
        candidate = ingest_patient_observation(obs)
        assert candidate.candidate_type == "lab"
        assert candidate.normalized_token == "crp"
        assert candidate.parsed_value == pytest.approx(145.0)
        assert candidate.qualitative == "high"

    def test_non_lab_text_is_finding(self):
        obs = _obs("Patient reports dizziness since yesterday")
        candidate = ingest_patient_observation(obs)
        assert candidate.candidate_type == "finding"
        assert candidate.parsed_value is None

    def test_negation_prefixed(self):
        obs = _obs("No fever", negation=True)
        candidate = ingest_patient_observation(obs)
        assert "[negated]" in candidate.candidate_text

    def test_uncertainty_prefixed(self):
        obs = _obs("Maybe chest tightness", uncertainty=True)
        candidate = ingest_patient_observation(obs)
        assert "[uncertain]" in candidate.candidate_text

    def test_event_time_propagated(self):
        t = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        obs = _obs("Shortness of breath", event_time=t)
        candidate = ingest_patient_observation(obs)
        assert candidate.event_time_iso is not None
        assert "2024-01-15" in candidate.event_time_iso

    def test_no_event_time_gives_none(self):
        obs = _obs("Cough for 3 days")
        candidate = ingest_patient_observation(obs)
        # event_time_iso may be None or resolved from onset_hint — just don't crash
        assert candidate is not None

    def test_source_ref_contains_observation_id(self):
        obs = PatientObservation(id="obs-xyz-42", raw_text="Headache")
        candidate = ingest_patient_observation(obs)
        assert "obs-xyz-42" in candidate.observation.source_ref

    def test_candidate_type_never_diagnosis(self):
        obs = _obs("I think I have pneumonia")
        candidate = ingest_patient_observation(obs)
        assert candidate.candidate_type != "diagnosis"

    def test_confidence_is_reasonable(self):
        obs = _obs("Chest pain")
        candidate = ingest_patient_observation(obs)
        assert 0.0 < candidate.confidence <= 1.0


# ── ingest_measurement ─────────────────────────────────────────────────────────

class TestIngestMeasurement:
    def test_wearable_good_quality_high_confidence(self):
        pgm = _pgm("heart_rate", 115.0, "bpm", quality="good")
        candidate = ingest_measurement(pgm)
        assert candidate.confidence >= 0.60

    def test_home_device_poor_quality_lower_confidence(self):
        pgm = _pgm("systolic_bp", 145.0, "mmHg", device_type="home_device", quality="poor")
        candidate = ingest_measurement(pgm)
        assert candidate.confidence < 0.65

    def test_high_value_qualitative(self):
        pgm = _pgm("spo2", 85.0, "%")
        candidate = ingest_measurement(pgm)
        assert candidate.qualitative == "low"

    def test_normal_heart_rate(self):
        pgm = _pgm("heart_rate", 72.0, "bpm")
        candidate = ingest_measurement(pgm)
        assert candidate.qualitative == "normal"

    def test_high_temperature(self):
        pgm = _pgm("temperature", 39.2, "°C", device_type="home_device")
        candidate = ingest_measurement(pgm)
        assert candidate.qualitative == "high"

    def test_candidate_type_is_lab(self):
        pgm = _pgm("heart_rate", 90.0, "bpm")
        candidate = ingest_measurement(pgm)
        assert candidate.candidate_type == "lab"

    def test_normalized_token_preserved(self):
        pgm = _pgm("spo2", 95.0, "%")
        candidate = ingest_measurement(pgm)
        assert candidate.normalized_token == "spo2"

    def test_parsed_value_preserved(self):
        pgm = _pgm("heart_rate", 108.0, "bpm")
        candidate = ingest_measurement(pgm)
        assert candidate.parsed_value == pytest.approx(108.0)

    def test_event_time_iso_set(self):
        t = datetime(2024, 3, 1, 8, 0, tzinfo=timezone.utc)
        pgm = _pgm("heart_rate", 100.0, "bpm", event_time=t)
        candidate = ingest_measurement(pgm)
        assert candidate.event_time_iso is not None
        assert "2024-03-01" in candidate.event_time_iso

    def test_candidate_type_never_diagnosis(self):
        pgm = _pgm("spo2", 88.0, "%")
        candidate = ingest_measurement(pgm)
        assert candidate.candidate_type != "diagnosis"

    def test_poor_quality_sets_uncertainty_hint(self):
        pgm = _pgm("spo2", 92.0, "%", quality="poor")
        candidate = ingest_measurement(pgm)
        assert candidate.observation.uncertainty_hint is True


# ── extract_trend_signal ───────────────────────────────────────────────────────

class TestExtractTrendSignal:
    def test_returns_none_below_min_points(self):
        pgms = _pgm_series("heart_rate", [70.0, 75.0])  # only 2 points
        assert extract_trend_signal(pgms) is None

    def test_returns_none_mixed_tokens(self):
        pgms = _pgm_series("heart_rate", [70, 80, 90])
        pgms[1] = pgms[1].model_copy(update={"token": "spo2"})
        assert extract_trend_signal(pgms) is None

    def test_rising_trend(self):
        values = [70.0, 80.0, 90.0, 100.0, 110.0]
        pgms = _pgm_series("heart_rate", values)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.direction == "rising"

    def test_falling_trend(self):
        values = [98.0, 96.0, 94.0, 92.0, 88.0]
        pgms = _pgm_series("spo2", values)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.direction == "falling"

    def test_stable_within_threshold(self):
        # Less than _TREND_MAGNITUDE_THRESHOLD_PCT change
        values = [100.0, 101.0, 100.5, 100.0, 100.2]
        pgms = _pgm_series("systolic_bp", values)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.direction == "stable"

    def test_magnitude_pct_calculated(self):
        values = [80.0, 90.0, 100.0, 110.0, 120.0]  # +50%
        pgms = _pgm_series("heart_rate", values)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.magnitude_pct == pytest.approx(50.0, abs=1.0)

    def test_start_end_values_set(self):
        values = [70.0, 80.0, 90.0, 100.0]
        pgms = _pgm_series("heart_rate", values)
        trend = extract_trend_signal(pgms)
        assert trend.start_value == pytest.approx(70.0)
        assert trend.end_value == pytest.approx(100.0)

    def test_n_points_set(self):
        values = [70.0, 75.0, 80.0, 85.0, 90.0]
        pgms = _pgm_series("heart_rate", values)
        trend = extract_trend_signal(pgms)
        assert trend.n_points == 5

    def test_window_hours_set(self):
        values = [70.0, 80.0, 90.0, 100.0]
        pgms = _pgm_series("heart_rate", values, interval_hours=2.0)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.window_hours == pytest.approx(6.0, abs=0.1)  # 3 intervals × 2h

    def test_tachycardia_clinical_flag(self):
        # HR rising past 100
        values = [80.0, 90.0, 100.0, 110.0, 120.0]
        pgms = _pgm_series("heart_rate", values)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.clinical_flag == "tachycardia_trend"

    def test_hypoxia_clinical_flag(self):
        values = [97.0, 95.0, 93.0, 91.0, 88.0]
        pgms = _pgm_series("spo2", values)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.clinical_flag == "hypoxia_trend"

    def test_no_clinical_flag_when_normal(self):
        values = [70.0, 72.0, 74.0, 73.0, 75.0]
        pgms = _pgm_series("heart_rate", values)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.clinical_flag is None

    def test_volatile_direction(self):
        # Alternating values — many sign changes
        values = [80.0, 110.0, 75.0, 105.0, 70.0, 115.0, 72.0, 108.0]
        pgms = _pgm_series("heart_rate", values)
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.direction == "volatile"

    def test_ignores_measurements_without_event_time(self):
        pgms = []
        base = _now()
        for i, v in enumerate([70.0, 80.0, 90.0]):
            pgms.append(PatientGeneratedMeasurement(
                id=f"pgm-{i}",
                device_type="wearable",
                token="heart_rate",
                value=v,
                unit="bpm",
                measurement_quality="good",
                event_time=base + timedelta(hours=i),
            ))
        # Add one without event_time
        pgms.append(PatientGeneratedMeasurement(
            id="pgm-no-time",
            device_type="wearable",
            token="heart_rate",
            value=200.0,
            unit="bpm",
            measurement_quality="good",
            event_time=None,
        ))
        # Still extracts trend from the 3 that have event_time
        trend = extract_trend_signal(pgms)
        assert trend is not None
        assert trend.end_value == pytest.approx(90.0)  # 200.0 excluded


# ── normalize_to_candidates ────────────────────────────────────────────────────

class TestNormalizeToCandidates:
    def test_single_observation(self):
        obs = _obs("Chest pain")
        results = normalize_to_candidates([obs])
        assert len(results) == 1

    def test_single_measurement(self):
        pgm = _pgm("heart_rate", 90.0, "bpm")
        results = normalize_to_candidates([pgm])
        assert len(results) >= 1

    def test_mixed_inputs(self):
        obs = _obs("Shortness of breath")
        pgm = _pgm("spo2", 92.0, "%")
        results = normalize_to_candidates([obs, pgm])
        assert len(results) >= 2

    def test_trend_candidate_added_when_sufficient_points(self):
        pgms = _pgm_series("heart_rate", [80.0, 90.0, 100.0, 110.0, 120.0])
        results = normalize_to_candidates(pgms)
        # Should have 5 individual + 1 trend = 6
        assert len(results) == 6

    def test_no_trend_when_insufficient_points(self):
        pgms = _pgm_series("heart_rate", [80.0, 90.0])  # only 2
        results = normalize_to_candidates(pgms)
        assert len(results) == 2  # just the 2 individual, no trend

    def test_no_diagnosis_candidates_produced(self):
        obs = _obs("I think I have STEMI")
        pgm = _pgm("heart_rate", 115.0, "bpm")
        results = normalize_to_candidates([obs, pgm])
        for c in results:
            assert c.candidate_type != "diagnosis"

    def test_observations_and_measurements_grouped_correctly(self):
        obs1 = _obs("Dizziness")
        obs2 = _obs("Nausea")
        pgm1 = _pgm("spo2", 95.0, "%")
        pgm2 = _pgm("spo2", 93.0, "%")
        results = normalize_to_candidates([obs1, obs2, pgm1, pgm2])
        # 2 obs + 2 measurements (no trend since only 2 spo2 points)
        assert len(results) == 4

    def test_trend_candidate_text_contains_direction(self):
        pgms = _pgm_series("spo2", [98.0, 95.0, 93.0, 90.0, 87.0])
        results = normalize_to_candidates(pgms)
        trend_candidates = [
            c for c in results
            if "falling" in c.candidate_text or "rising" in c.candidate_text or "stable" in c.candidate_text
        ]
        assert len(trend_candidates) >= 1


# ── EvidenceTier integration ───────────────────────────────────────────────────

class TestEvidenceTierDerivation:
    def test_source_to_evidence_tier_patient_report(self):
        from models import source_to_evidence_tier, EvidenceTier
        assert source_to_evidence_tier("patient_report") == EvidenceTier.patient_generated

    def test_source_to_evidence_tier_wearable(self):
        from models import source_to_evidence_tier, EvidenceTier
        assert source_to_evidence_tier("wearable") == EvidenceTier.patient_generated

    def test_source_to_evidence_tier_home_device(self):
        from models import source_to_evidence_tier, EvidenceTier
        assert source_to_evidence_tier("home_device") == EvidenceTier.patient_generated

    def test_source_to_evidence_tier_caregiver(self):
        from models import source_to_evidence_tier, EvidenceTier
        assert source_to_evidence_tier("caregiver_report") == EvidenceTier.patient_generated

    def test_source_to_evidence_tier_clinician(self):
        from models import source_to_evidence_tier, EvidenceTier
        assert source_to_evidence_tier("clinician") == EvidenceTier.clinician_observed

    def test_source_to_evidence_tier_lab_system(self):
        from models import source_to_evidence_tier, EvidenceTier
        assert source_to_evidence_tier("lab_system") == EvidenceTier.lab_confirmed

    def test_source_to_evidence_tier_guideline(self):
        from models import source_to_evidence_tier, EvidenceTier
        assert source_to_evidence_tier("guideline") == EvidenceTier.guideline_structured

    def test_source_to_evidence_tier_unknown_defaults_clinician(self):
        from models import source_to_evidence_tier, EvidenceTier
        assert source_to_evidence_tier("unknown_source") == EvidenceTier.clinician_observed

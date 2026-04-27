"""Patient Data Layer — ingestion, normalization, and trend detection.

Epistemic contract:
    Patient-generated inputs (PatientObservation, PatientGeneratedMeasurement)
    are NEVER directly used as clinical-grade evidence. They flow through this
    module, which normalises them into ClaimCandidates at the correct epistemic
    tier. The safeguard validator enforces:

        1. claim_type != "diagnosis"   (patients don't confirm diagnoses)
        2. status != "confirmed"       (only clinicians may confirm)

Architecture:
    PatientObservation / PatientGeneratedMeasurement
            │
            ▼  (ingest_*)
    ClaimCandidate  (evidence_tier=patient_generated, source_type=patient_report|wearable|…)
            │
            ▼  (validation pipeline in llm_client.py)
    Claim   (with evidence_tier preserved, patient_data_ref set)
"""

from __future__ import annotations

import contextlib
import re
import uuid
from datetime import UTC, datetime

from lab_parser import LAB_THRESHOLDS, parse_lab_value
from models import (
    ClaimCandidate,
    EvidenceTier,
    ExtractedObservation,
    PatientGeneratedMeasurement,
    PatientObservation,
    TrendPoint,
    TrendSignal,
)

# ── Constants ──────────────────────────────────────────────────────────────────

# Minimum number of measurements required for a trend to be reported
_MIN_TREND_POINTS = 3

# Minimum absolute percent change to report a directional trend (not "stable")
_TREND_MAGNITUDE_THRESHOLD_PCT = 5.0

# Clinical flag thresholds (token → (flag_name, direction, threshold_value))
_CLINICAL_FLAGS: dict[str, list[tuple[str, str, float]]] = {
    "spo2":       [("hypoxia_trend",       "falling", 94.0)],
    "heart_rate": [("tachycardia_trend",   "rising",  100.0),
                   ("bradycardia_trend",   "falling",  50.0)],
    "systolic_bp":[("hypotension_trend",   "falling",  90.0),
                   ("hypertension_trend",  "rising",  140.0)],
    "temperature":[("fever_trend",         "rising",   38.0)],
    "glucose":    [("hyperglycemia_trend", "rising",  180.0),
                   ("hypoglycemia_trend",  "falling",   70.0)],
    "rr":         [("tachypnea_trend",     "rising",   20.0)],
}


# ── Safeguard validator ────────────────────────────────────────────────────────

def _safeguard_candidate(candidate: ClaimCandidate) -> ClaimCandidate:
    """Enforce epistemic constraints for patient-generated ClaimCandidates.

    Rules:
        - candidate_type must not be "diagnosis"
        - observation.source_ref must not encode "confirmed" status
    Both rules downgrade rather than reject, keeping the data visible but
    clearly marked at the correct epistemic level.
    """
    if candidate.candidate_type == "diagnosis":
        candidate = candidate.model_copy(
            update={"candidate_type": "finding"}
        )

    # Ensure source_ref does not carry a "confirmed" status marker
    obs = candidate.observation
    if obs.source_ref and "confirmed" in obs.source_ref.lower():
        new_ref = re.sub(r'confirmed', 'reported', obs.source_ref, flags=re.IGNORECASE)
        candidate = candidate.model_copy(
            update={"observation": obs.model_copy(update={"source_ref": new_ref})}
        )

    return candidate


# ── Observation ingestion ──────────────────────────────────────────────────────

def ingest_patient_observation(obs: PatientObservation) -> ClaimCandidate:
    """Convert a PatientObservation (Stage 0) into a ClaimCandidate (Stage 2).

    No LLM call — rule-based extraction only. Lab values are parsed where
    possible; the rest is treated as a qualitative finding.
    """
    # Attempt numeric lab extraction
    lab = parse_lab_value(obs.raw_text)
    candidate_type = "finding"
    normalized_token: str | None = None
    parsed_value: float | None = None
    parsed_unit: str | None = None
    qualitative: str | None = None

    if lab:
        candidate_type = "lab"
        normalized_token = lab.token
        parsed_value = lab.value
        parsed_unit = lab.unit
        qualitative = lab.qualitative

    # Build synthetic ExtractedObservation (Stage 1 proxy)
    raw_obs = ExtractedObservation(
        raw_text=obs.raw_text,
        observation=obs.raw_text,
        observation_type=candidate_type,
        temporal_hint=obs.onset_hint,
        negation_hint=obs.negation_hint,
        uncertainty_hint=obs.uncertainty_hint,
        source_ref=f"patient_observation:{obs.id}",
    )

    event_time_iso: str | None = None
    if obs.event_time:
        event_time_iso = obs.event_time.isoformat()

    candidate_text = obs.raw_text
    if obs.negation_hint:
        candidate_text = f"[negated] {candidate_text}"
    if obs.uncertainty_hint:
        candidate_text = f"[uncertain] {candidate_text}"

    candidate = ClaimCandidate(
        observation=raw_obs,
        candidate_text=candidate_text,
        candidate_type=candidate_type,
        normalized_token=normalized_token,
        parsed_value=parsed_value,
        parsed_unit=parsed_unit,
        qualitative=qualitative,
        event_time_iso=event_time_iso,
        confidence=0.5,  # patient-reported baseline confidence
    )
    return _safeguard_candidate(candidate)


# ── Measurement ingestion ──────────────────────────────────────────────────────

def ingest_measurement(pgm: PatientGeneratedMeasurement) -> ClaimCandidate:
    """Convert a PatientGeneratedMeasurement (Stage 0) into a ClaimCandidate (Stage 2).

    Device measurements are already numeric — no text parsing needed.
    Confidence varies by device type and measurement quality.
    """
    # Base confidence by device type
    confidence_map = {
        "wearable":    0.65,
        "home_device": 0.75,
    }
    base_confidence = confidence_map.get(pgm.device_type, 0.60)

    # Quality modifier
    quality_modifier = {
        "good":    0.0,
        "medium": -0.10,
        "poor":   -0.25,
        "unknown":-0.05,
    }
    confidence = base_confidence + quality_modifier.get(pgm.measurement_quality or "unknown", -0.05)
    confidence = max(0.10, min(0.90, confidence))

    # Derive qualitative if not provided
    qualitative = pgm.qualitative
    if qualitative is None:
        spec = LAB_THRESHOLDS.get(pgm.token, {})
        if "high" in spec and pgm.value > spec["high"]:
            qualitative = "high"
        elif "low" in spec and pgm.value < spec["low"]:
            qualitative = "low"
        else:
            qualitative = "normal"

    # Build descriptive text
    device_label = pgm.device_name or pgm.device_type
    candidate_text = (
        f"{pgm.token} {pgm.value} {pgm.unit} "
        f"[{qualitative}] via {device_label}"
    )

    raw_obs = ExtractedObservation(
        raw_text=candidate_text,
        observation=candidate_text,
        observation_type="lab",
        temporal_hint=pgm.event_time.isoformat() if pgm.event_time else None,
        negation_hint=False,
        uncertainty_hint=(pgm.measurement_quality in ("poor", "unknown")),
        source_ref=f"measurement:{pgm.id}",
    )

    event_time_iso: str | None = None
    if pgm.event_time:
        event_time_iso = pgm.event_time.isoformat()

    candidate = ClaimCandidate(
        observation=raw_obs,
        candidate_text=candidate_text,
        candidate_type="lab",
        normalized_token=pgm.token,
        parsed_value=pgm.value,
        parsed_unit=pgm.unit,
        qualitative=qualitative,
        event_time_iso=event_time_iso,
        confidence=confidence,
    )
    return _safeguard_candidate(candidate)


# ── Trend detection ────────────────────────────────────────────────────────────

def _linear_regression_slope(points: list[TrendPoint]) -> float:
    """Return slope (units/hour) using ordinary least squares."""
    n = len(points)
    if n < 2:
        return 0.0

    # Convert timestamps to hours-since-first
    t0 = points[0].timestamp.timestamp()
    xs = [(p.timestamp.timestamp() - t0) / 3600.0 for p in points]
    ys = [p.value for p in points]

    x_mean = sum(xs) / n
    y_mean = sum(ys) / n

    numerator   = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=False))
    denominator = sum((x - x_mean) ** 2 for x in xs)

    if abs(denominator) < 1e-9:
        return 0.0
    return numerator / denominator


def extract_trend_signal(
    measurements: list[PatientGeneratedMeasurement],
) -> TrendSignal | None:
    """Derive a TrendSignal from a time-ordered list of PatientGeneratedMeasurements.

    Requirements:
        - All measurements must share the same token
        - Minimum _MIN_TREND_POINTS data points required
        - At least _TREND_MAGNITUDE_THRESHOLD_PCT change for a directional trend

    Returns None if conditions are not met.
    """
    if len(measurements) < _MIN_TREND_POINTS:
        return None

    # Verify all share the same token
    tokens = {m.token for m in measurements}
    if len(tokens) != 1:
        return None

    token = tokens.pop()

    # Filter to measurements that have event_time; sort chronologically
    timed = [m for m in measurements if m.event_time is not None]
    if len(timed) < _MIN_TREND_POINTS:
        return None

    timed.sort(key=lambda m: m.event_time)  # type: ignore[arg-type]

    points = [TrendPoint(timestamp=m.event_time, value=m.value) for m in timed]  # type: ignore[arg-type]

    start_value = points[0].value
    end_value   = points[-1].value
    n_points    = len(points)

    # Time window
    window_hours = (
        (points[-1].timestamp.timestamp() - points[0].timestamp.timestamp()) / 3600.0
    )
    if window_hours < 0.01:
        window_hours = 0.01

    # Percent change (relative to start)
    if abs(start_value) < 1e-9:
        magnitude_pct = 0.0
    else:
        magnitude_pct = ((end_value - start_value) / abs(start_value)) * 100.0

    # Direction from OLS slope
    slope = _linear_regression_slope(points)

    if abs(magnitude_pct) < _TREND_MAGNITUDE_THRESHOLD_PCT:
        direction = "stable"
    elif slope > 0:
        direction = "rising"
    else:
        direction = "falling"

    # Volatile: check if sign flips more than once
    if n_points >= 4:
        diffs = [points[i + 1].value - points[i].value for i in range(n_points - 1)]
        sign_changes = sum(
            1 for i in range(len(diffs) - 1)
            if diffs[i] * diffs[i + 1] < 0
        )
        # Require strictly more than half of consecutive diff-pairs to change sign
        if sign_changes > len(diffs) // 2:
            direction = "volatile"

    # Clinical flag
    clinical_flag: str | None = None
    for flag_name, flag_dir, threshold in _CLINICAL_FLAGS.get(token, []):
        if flag_dir == "rising" and direction == "rising" and end_value >= threshold:
            clinical_flag = flag_name
            break
        if flag_dir == "falling" and direction == "falling" and end_value <= threshold:
            clinical_flag = flag_name
            break

    return TrendSignal(
        id=str(uuid.uuid4()),
        token=token,
        direction=direction,
        magnitude_pct=round(magnitude_pct, 2),
        window_hours=round(window_hours, 2),
        start_value=start_value,
        end_value=end_value,
        n_points=n_points,
        clinical_flag=clinical_flag,
    )


# ── Batch normalisation entry point ───────────────────────────────────────────

def normalize_to_candidates(
    inputs: list[PatientObservation | PatientGeneratedMeasurement],
) -> list[ClaimCandidate]:
    """Convert a mixed list of patient inputs into ClaimCandidates.

    Groups PatientGeneratedMeasurements by token for trend detection;
    each measurement is also ingested individually (for point-in-time claims).
    Trend signals produce an additional ClaimCandidate tagged with the trend.
    """
    candidates: list[ClaimCandidate] = []

    # Separate types
    observations: list[PatientObservation] = []
    measurements_by_token: dict[str, list[PatientGeneratedMeasurement]] = {}

    for item in inputs:
        if isinstance(item, PatientObservation):
            observations.append(item)
        elif isinstance(item, PatientGeneratedMeasurement):
            measurements_by_token.setdefault(item.token, []).append(item)

    # Ingest individual observations
    for obs in observations:
        candidates.append(ingest_patient_observation(obs))

    # Ingest measurements + attempt trend detection
    for _token, pgms in measurements_by_token.items():
        for pgm in pgms:
            c = ingest_measurement(pgm)
            candidates.append(c)

        # Trend detection (needs ≥ _MIN_TREND_POINTS)
        trend = extract_trend_signal(pgms)
        if trend is not None:
            _add_trend_candidate(candidates, trend)

    return candidates


def candidate_to_claim(
    candidate: ClaimCandidate,
    source_type: str,
    evidence_tier: str = EvidenceTier.patient_generated,
    patient_data_ref: str = "",
) -> Claim:
    """Convert a validated ClaimCandidate into a Claim.

    Used by the measurements intake path (no LLM needed for structured data).
    The evidence_tier and source_type are always enforced from the API boundary.
    """
    from models import Claim, ClaimStatus, ClaimTrend, ClaimType  # local import avoids circular

    now = datetime.now(UTC)

    ct_map = {
        "lab":     ClaimType.lab,
        "finding": ClaimType.finding,
        "symptom": ClaimType.symptom,
        "therapy": ClaimType.therapy,
        "imaging": ClaimType.imaging,
    }
    claim_type = ct_map.get(candidate.candidate_type, ClaimType.finding)

    event_time = None
    if candidate.event_time_iso:
        with contextlib.suppress(ValueError):
            event_time = datetime.fromisoformat(candidate.event_time_iso)

    return Claim(
        text=candidate.candidate_text,
        entities=[candidate.normalized_token] if candidate.normalized_token else [],
        relations=[],
        evidence_support_score=candidate.confidence,
        claim_type=claim_type,
        source_type=source_type,
        source_ref=candidate.observation.source_ref,
        evidence_tier=evidence_tier,
        status=ClaimStatus.observed,
        trend=ClaimTrend.unknown,
        normalized_token=candidate.normalized_token,
        uncertainty_flag=candidate.observation.uncertainty_hint,
        assumptions=[],
        event_time=event_time,
        assertion_time=now,
        patient_data_ref=patient_data_ref or candidate.observation.source_ref,
        projection_confidence=candidate.confidence,
        projection_method=(
            "rule_based_measurement"
            if candidate.observation.source_ref.startswith("measurement:")
            else "rule_based_observation"
        ),
    )


def _add_trend_candidate(
    candidates: list[ClaimCandidate],
    trend: TrendSignal,
) -> None:
    """Append a ClaimCandidate synthesised from a TrendSignal."""
    flag_text = f" [{trend.clinical_flag}]" if trend.clinical_flag else ""
    candidate_text = (
        f"{trend.token} {trend.direction} "
        f"{abs(trend.magnitude_pct):.1f}% over {trend.window_hours:.1f}h "
        f"(n={trend.n_points}){flag_text}"
    )
    raw_obs = ExtractedObservation(
        raw_text=candidate_text,
        observation=candidate_text,
        observation_type="finding",
        temporal_hint=None,
        negation_hint=False,
        uncertainty_hint=(trend.direction == "volatile"),
        source_ref=f"trend_signal:{trend.id}",
    )
    candidate = ClaimCandidate(
        observation=raw_obs,
        candidate_text=candidate_text,
        candidate_type="finding",
        normalized_token=trend.token,
        parsed_value=None,
        parsed_unit=None,
        qualitative=None,
        event_time_iso=None,
        confidence=0.6,
    )
    # Link back to the trend signal
    trend.candidate_id = candidate.observation.source_ref
    candidates.append(_safeguard_candidate(candidate))

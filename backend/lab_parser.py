"""
Lab value parser for AleXiona.

Extracts numeric lab values from free-text claim strings and compares them
against clinical reference thresholds to produce a qualitative assessment
(high / low / normal) and a structured LabResult.

Typical usage in reasoning_engine:
    result = parse_lab_value("CRP 145 mg/L")
    # → LabResult(token="crp", value=145.0, unit="mg/L", qualitative="high", raw="CRP 145 mg/L")
"""
import re
from dataclasses import dataclass
from typing import Optional


# ── Reference thresholds ──────────────────────────────────────────────────────
# All values are in the listed canonical unit.
# A claim is "high" if value > high_threshold, "low" if value < low_threshold,
# "normal" otherwise.  Fields omitted = no boundary in that direction.
LAB_THRESHOLDS: dict[str, dict] = {
    "crp": {
        "aliases":  ["crp", "c-reactive protein", "c reactive protein"],
        "unit":     "mg/l",
        "high":     10.0,
        "clinical_note": "CRP >10 supports infection/inflammation",
    },
    "troponin": {
        "aliases":  ["troponin", "troponin i", "troponin t", "hs-troponin", "hstni", "hstnt"],
        "unit":     "µg/l",
        "high":     0.04,
        "clinical_note": "Troponin >0.04 µg/L supports myocardial injury",
    },
    "lactate": {
        "aliases":  ["lactate", "lactic acid", "laktat"],
        "unit":     "mmol/l",
        "high":     2.0,
        "clinical_note": "Lactate >2 mmol/L supports hypoperfusion/sepsis",
    },
    "ddimer": {
        "aliases":  ["d-dimer", "d dimer", "ddimer", "d-dimere"],
        "unit":     "µg/ml",
        "high":     0.5,
        "clinical_note": "D-Dimer >0.5 µg/mL supports thromboembolic event",
    },
    "leukocytes": {
        "aliases":  ["leukocytes", "wbc", "white blood cell", "leukocyten", "leukozyten"],
        "unit":     "g/l",
        "high":     11.0,
        "low":       4.0,
        "clinical_note": "WBC >11 G/L suggests leukocytosis; <4 G/L leukopenia",
    },
    "procalcitonin": {
        "aliases":  ["procalcitonin", "pct"],
        "unit":     "µg/l",
        "high":     0.5,
        "clinical_note": "PCT >0.5 µg/L supports bacterial infection",
    },
    "bnp": {
        "aliases":  ["bnp", "brain natriuretic peptide", "nt-probnp", "ntprobnp"],
        "unit":     "pg/ml",
        "high":     100.0,
        "clinical_note": "BNP >100 pg/mL supports heart failure",
    },
    "creatinine": {
        "aliases":  ["creatinine", "kreatinin", "creatinin"],
        "unit":     "mg/dl",
        "high":     1.2,
        "clinical_note": "Creatinine >1.2 mg/dL suggests renal impairment",
    },
    "hemoglobin": {
        "aliases":  ["hemoglobin", "hämoglobin", "haemoglobin", "hgb", "hb"],
        "unit":     "g/dl",
        "low":      12.0,
        "clinical_note": "Hemoglobin <12 g/dL indicates anemia",
    },
    "spo2": {
        "aliases":  ["spo2", "oxygen saturation", "o2 saturation", "sauerstoffsättigung"],
        "unit":     "%",
        "low":      94.0,
        "clinical_note": "SpO2 <94% indicates hypoxemia",
    },
    "heart_rate": {
        "aliases":  ["heart rate", "pulse", "herzfrequenz", "hr", "puls"],
        "unit":     "bpm",
        "high":     100.0,
        "low":       50.0,
        "clinical_note": "HR >100 bpm = tachycardia; <50 bpm = bradycardia",
    },
    "systolic_bp": {
        "aliases":  ["systolic", "sbp", "rr sys", "blutdruck systolisch"],
        "unit":     "mmhg",
        "low":      90.0,
        "clinical_note": "SBP <90 mmHg indicates hypotension",
    },
    "respiratory_rate": {
        "aliases":  ["respiratory rate", "atemfrequenz", "rr", "atemzüge"],
        "unit":     "/min",
        "high":     22.0,
        "clinical_note": "RR ≥22/min is a qSOFA criterion for sepsis",
    },
    "temperature": {
        "aliases":  ["temperature", "temperatur", "temp", "körpertemperatur"],
        "unit":     "°c",
        "high":     38.0,
        "low":      36.0,
        "clinical_note": "Temp >38°C = fever; <36°C = hypothermia",
    },
    "gcs": {
        "aliases":  ["gcs", "glasgow coma scale", "glasgow coma score"],
        "unit":     "",
        "low":      15.0,
        "clinical_note": "GCS <15 is a qSOFA criterion for sepsis",
    },
}

# ── Regex patterns ────────────────────────────────────────────────────────────
# Matches a numeric value (integer or decimal) possibly followed by a unit.
# Examples: "145", "0.04", "14.5 G/L", "38.2°C", "94 %"
_VALUE_RE = re.compile(
    r'(?<!\w)'            # not preceded by word char (avoids ICD codes)
    r'(\d{1,4}(?:[.,]\d{1,3})?)'   # integer or decimal (comma or dot)
    r'\s*'
    r'([a-zA-ZÄÖÜäöü°/%µ][a-zA-ZÄÖÜäöü°/%. \-]*)?'  # optional unit
)

# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class LabResult:
    token:       str            # canonical lab token (e.g. "crp")
    value:       float
    unit:        str            # as extracted from text (lowercased)
    qualitative: str            # "high" | "low" | "normal" | "unknown"
    raw:         str            # original text snippet
    clinical_note: str = ""


def _normalize_number(s: str) -> float:
    """Parse '14,5' or '14.5' → 14.5."""
    return float(s.replace(",", "."))


def _match_token(text: str) -> Optional[tuple[str, dict]]:
    """Find the first LAB_THRESHOLDS entry whose alias appears in *text*."""
    t = text.lower()
    for token, spec in LAB_THRESHOLDS.items():
        for alias in spec["aliases"]:
            if alias in t:
                return token, spec
    return None


def parse_lab_value(text: str) -> Optional[LabResult]:
    """Parse a single lab claim text and return a LabResult, or None if no match.

    Examples:
        parse_lab_value("CRP 145 mg/L")
            → LabResult(token="crp", value=145.0, unit="mg/l", qualitative="high", ...)
        parse_lab_value("Troponin negative, <0.01 µg/L")
            → LabResult(token="troponin", value=0.01, unit="µg/l", qualitative="normal", ...)
        parse_lab_value("No relevant lab values here")
            → None
    """
    match = _match_token(text)
    if not match:
        return None
    token, spec = match

    # Extract the first numeric value in the text
    m = _VALUE_RE.search(text)
    if not m:
        return None

    try:
        value = _normalize_number(m.group(1))
    except ValueError:
        return None

    unit = (m.group(2) or spec.get("unit", "")).strip().lower()

    # Determine qualitative assessment
    high = spec.get("high")
    low  = spec.get("low")
    if high is not None and value > high:
        qualitative = "high"
    elif low is not None and value < low:
        qualitative = "low"
    else:
        qualitative = "normal"

    return LabResult(
        token=token,
        value=value,
        unit=unit,
        qualitative=qualitative,
        raw=text,
        clinical_note=spec.get("clinical_note", ""),
    )


def parse_lab_values(texts: list[str]) -> list[LabResult]:
    """Parse a list of claim texts, returning all successfully parsed results."""
    results = []
    for t in texts:
        r = parse_lab_value(t)
        if r:
            results.append(r)
    return results


def qualitative_for_token(token: str, all_claims: list[dict]) -> Optional[str]:
    """Return the most recent qualitative assessment ("high"/"low"/"normal") for
    a given lab token across all active claims, or None if not found.

    Used by evaluate_guideline / composite score functions.
    """
    for c in reversed(all_claims):
        if c.get("status") != "active":
            continue
        result = parse_lab_value(c.get("text", ""))
        if result and result.token == token:
            return result.qualitative
    return None


def lab_summary(all_claims: list[dict]) -> dict[str, LabResult]:
    """Return a token → most-recent LabResult mapping for all active claims."""
    summary: dict[str, LabResult] = {}
    for c in all_claims:
        if c.get("status") != "active":
            continue
        result = parse_lab_value(c.get("text", ""))
        if result:
            summary[result.token] = result   # later claims overwrite earlier ones
    return summary

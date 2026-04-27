"""
Role-based clinical view builder for AleXiona.

Every role receives exactly the information relevant to their clinical task —
no more, no less.  The same underlying claim graph produces different views
for nurse, resident, specialist, lab, and chief physician.

Roles (German aliases accepted):
  pfleger   / nurse       — vitals, trend alerts, monitoring tasks
  assistenzarzt / resident — full diagnostic picture, MED, guidelines
  facharzt  / specialist  — specialty-filtered hypotheses + deep reasoning
  labor     / lab         — lab results, abnormal flags, requested tests
  chefarzt  / chief       — executive summary, risks, decisions pending
"""
from __future__ import annotations

from composite_scores import compute_all_scores
from lab_parser import LAB_THRESHOLDS, lab_summary, parse_lab_value
from reasoning_engine import (
    _ACTIVE_STATUSES,
    _TREND_FLAG_RE,
    evaluate_all_guidelines,
    explain_hypothesis_scores,
    get_confident_leading,
    rank_hypotheses,
)

# ── Role alias map ─────────────────────────────────────────────────────────────
ROLE_ALIASES: dict[str, str] = {
    "pfleger":        "nurse",
    "pflegerin":      "nurse",
    "nurse":          "nurse",
    "assistenzarzt":  "resident",
    "assistenzärztin":"resident",
    "resident":       "resident",
    "facharzt":       "specialist",
    "fachärztin":     "specialist",
    "specialist":     "specialist",
    "labor":          "lab",
    "laborant":       "lab",
    "lab":            "lab",
    "chefarzt":       "chief",
    "chefärztin":     "chief",
    "oberarzt":       "chief",
    "chief":          "chief",
    "attending":      "chief",
}

VALID_ROLES = frozenset(ROLE_ALIASES.values())

# ── Specialty → hypothesis keyword filter ─────────────────────────────────────
SPECIALTY_KEYWORDS: dict[str, list[str]] = {
    "cardiology":    ["myocardial", "infarction", "heart failure", "acs", "stemi",
                      "nstemi", "coronary", "cardiac", "arrhythmia", "herzinfarkt",
                      "herzinsuffizienz"],
    "pulmonology":   ["pneumonia", "embolism", "ards", "copd", "asthma", "respiratory",
                      "pleural", "pneumonie", "lungenembolie"],
    "infectiology":  ["sepsis", "pneumonia", "meningitis", "endocarditis", "infection",
                      "pneumonie", "urosepsis"],
    "neurology":     ["stroke", "seizure", "meningitis", "encephalitis", "syncope",
                      "schlaganfall", "apoplex"],
    "nephrology":    ["renal", "kidney", "aki", "creatinine", "dialysis", "uremia",
                      "niereninsuffizienz"],
    "gastroenterology": ["liver", "pancreatitis", "cholecystitis", "appendicitis",
                          "peritonitis", "hepatic", "leber", "darm"],
}

# Vital-sign lab tokens for nurse view
_VITAL_TOKENS = {
    "heart_rate", "systolic_bp", "respiratory_rate", "spo2", "temperature", "gcs",
}

# Trend flags that require nurse-level alerting
_NURSE_ALERT_FLAGS = {
    "hypoxia_trend", "tachycardia_trend", "fever_trend",
    "hypotension_trend", "tachypnea_trend",
}

_CLAIM_TYPES_EVIDENCE = {"finding", "lab", "imaging", "symptom"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_role(role_raw: str) -> str | None:
    return ROLE_ALIASES.get(role_raw.lower().strip())


def _alert_level(interpretation: str) -> str:
    return {"high": "critical", "intermediate": "warning", "low": "info"}.get(
        interpretation, "info"
    )


def _vital_claims(all_claims: list[dict]) -> list[dict]:
    """Return claims that carry at least one parseable vital sign."""
    result = []
    for c in all_claims:
        if c.get("status") not in _ACTIVE_STATUSES:
            continue
        parsed = parse_lab_value(c["text"])
        if parsed and parsed.token in _VITAL_TOKENS:
            result.append(c)
    return result


def _trend_claims(all_claims: list[dict]) -> list[dict]:
    return [
        c for c in all_claims
        if (c.get("source_ref", "").startswith("trend:") or
            c.get("source_ref", "").startswith("trend_signal:"))
        and c.get("status") in _ACTIVE_STATUSES
    ]


# ── Role builders ─────────────────────────────────────────────────────────────

def _build_nurse_view(all_claims: list[dict]) -> dict:
    """Vitals, trend alerts, active symptoms — no diagnostic reasoning."""
    alerts = []
    sections = []

    # ── Vitals section ──────────────────────────────────────────────────────
    labs = lab_summary(all_claims)
    vital_items = []
    for token, r in sorted(labs.items()):
        if token not in _VITAL_TOKENS:
            continue
        flag = r.qualitative.upper()
        vital_items.append({
            "parameter": token.replace("_", " ").title(),
            "value":     f"{r.value} {r.unit}".strip(),
            "flag":      flag,
            "note":      r.clinical_note or "",
        })
        if flag in ("HIGH", "LOW"):
            alerts.append({
                "level":   "warning",
                "message": f"{token.replace('_', ' ').title()}: {r.value} {r.unit} [{flag}]",
                "context": r.clinical_note or "",
            })

    if vital_items:
        sections.append({"section": "Vitals", "items": vital_items})

    # ── Trend alerts ─────────────────────────────────────────────────────────
    trend_items = []
    for c in _trend_claims(all_claims):
        flag_match = _TREND_FLAG_RE.search(c.get("text", ""))
        flag       = flag_match.group(1) if flag_match else "unknown_trend"
        item = {
            "flag":    flag.replace("_", " ").title(),
            "text":    c["text"],
            "source":  c.get("source_type", ""),
        }
        trend_items.append(item)
        if flag in _NURSE_ALERT_FLAGS:
            alerts.append({
                "level":   "critical",
                "message": f"Trend alert: {flag.replace('_', ' ').upper()}",
                "context": c["text"],
            })

    if trend_items:
        sections.append({"section": "Trend Alerts", "items": trend_items})

    # ── Active symptoms ──────────────────────────────────────────────────────
    symptom_items = [
        {"text": c["text"], "status": c.get("status", "active"),
         "source": c.get("source_type", "")}
        for c in all_claims
        if c.get("claim_type") == "symptom" and c.get("status") in _ACTIVE_STATUSES
    ]
    if symptom_items:
        sections.append({"section": "Active Symptoms", "items": symptom_items})

    # ── Monitoring tasks (missing vitals) ────────────────────────────────────
    documented_vitals = {r.token for r in labs.values()}
    missing_vitals = [
        t.replace("_", " ").title()
        for t in _VITAL_TOKENS
        if t not in documented_vitals
    ]
    if missing_vitals:
        sections.append({
            "section": "Monitoring Tasks",
            "items":   [{"task": f"Document {v}"} for v in sorted(missing_vitals)],
        })

    return {"alerts": alerts, "sections": sections}


def _build_resident_view(all_claims: list[dict]) -> dict:
    """Full diagnostic picture: ranked hypotheses, risk scores, missing evidence."""
    alerts = []
    sections = []

    # ── Hypothesis ranking ───────────────────────────────────────────────────
    ranked   = rank_hypotheses(all_claims)
    leading  = get_confident_leading(ranked)
    guidelines = evaluate_all_guidelines(all_claims)

    if leading.get("status") == "insufficient":
        alerts.append({
            "level":   "warning",
            "message": leading.get("reason", "Insufficient evidence"),
            "context": "",
        })

    hyp_items = []
    for h in ranked:
        g = guidelines.get(h["text"], {})
        hyp_items.append({
            "hypothesis":        h["text"],
            "claim_type":        h["claim_type"],
            "score":             h["rule_based_score"],
            "supporting_count":  len(h["supporting_claim_ids"]),
            "conflicting_count": len(h["conflicting_claim_ids"]),
            "guideline_eligible": g.get("eligible", None),
            "required_missing":  g.get("required_missing", []),
            "missing_priority":  g.get("missing_priority", [])[:4],
        })
    if hyp_items:
        sections.append({"section": "Hypothesis Ranking", "items": hyp_items})

    # ── Relevant risk scores ─────────────────────────────────────────────────
    scores = compute_all_scores(all_claims)
    relevant_scores = [s for s in scores if s["relevant"]]
    if relevant_scores:
        score_items = []
        for s in relevant_scores:
            score_items.append({
                "name":           s["name"],
                "score":          s["score"],
                "interpretation": s["interpretation"],
                "criteria_met":   s["criteria_met"],
                "criteria_missing": s["criteria_missing"],
                "recommendation": s["recommendation"],
            })
            if s["interpretation"] == "high":
                alerts.append({
                    "level":   "critical",
                    "message": f"{s['name']} HIGH RISK (score {s['score']})",
                    "context": s["recommendation"],
                })
        sections.append({"section": "Risk Scores", "items": score_items})

    # ── Evidence by type ─────────────────────────────────────────────────────
    by_type: dict[str, list[dict]] = {}
    for c in all_claims:
        ct = c.get("claim_type", "other")
        if ct not in _CLAIM_TYPES_EVIDENCE:
            continue
        if c.get("status") not in _ACTIVE_STATUSES:
            continue
        by_type.setdefault(ct, []).append({
            "id":     c["id"],
            "text":   c["text"],
            "status": c.get("status"),
            "source": c.get("source_type", ""),
            "ess":    c.get("evidence_support_score", 0.5),
        })
    for claim_type, items in sorted(by_type.items()):
        sections.append({"section": f"Evidence: {claim_type.title()}", "items": items})

    return {"alerts": alerts, "sections": sections}


def _build_specialist_view(
    all_claims: list[dict],
    specialty: str | None,
) -> dict:
    """Specialty-filtered hypotheses with full claim contribution breakdown."""
    alerts = []
    sections = []

    # Determine which hypotheses belong to this specialty
    kw_filter = SPECIALTY_KEYWORDS.get((specialty or "").lower(), [])

    ranked = rank_hypotheses(all_claims)
    if kw_filter:
        relevant_hyps = [
            h for h in ranked
            if any(kw in h["text"].lower() for kw in kw_filter)
        ]
    else:
        relevant_hyps = ranked   # no specialty filter → show all

    if not relevant_hyps:
        sections.append({
            "section": "Hypotheses",
            "items":   [{"note": f"No active hypotheses match specialty '{specialty}'"}],
        })
        return {"alerts": alerts, "sections": sections}

    # ── Filtered hypothesis scores ───────────────────────────────────────────
    sections.append({
        "section": "Relevant Hypotheses",
        "items": [
            {
                "hypothesis":        h["text"],
                "score":             h["rule_based_score"],
                "supporting_count":  len(h["supporting_claim_ids"]),
                "conflicting_count": len(h["conflicting_claim_ids"]),
            }
            for h in relevant_hyps
        ],
    })

    # ── Per-claim contribution breakdown for relevant hypotheses ─────────────
    all_explained = explain_hypothesis_scores(all_claims)
    relevant_ids  = {h["id"] for h in relevant_hyps}
    explained     = [e for e in all_explained if e["id"] in relevant_ids]

    for e in explained:
        contributions = e["contributions"]
        top_support   = [c for c in contributions if c["direction"] == "supporting"][:5]
        top_conflict  = [c for c in contributions if c["direction"] == "conflicting"][:3]
        sections.append({
            "section": f"Evidence Breakdown: {e['text'][:60]}",
            "items": [
                {
                    "direction":      c["direction"],
                    "contribution":   c["contribution"],
                    "claim":          c["claim_text"],
                    "source":         c["source_type"],
                    "source_weight":  c["source_weight"],
                    "temporal_weight":c["temporal_weight"],
                    "spl_rule":       c["spl_emission_rule"],
                    "trend_boosted":  c["trend_boosted"],
                }
                for c in top_support + top_conflict
            ],
        })

    # ── Specialty risk scores ────────────────────────────────────────────────
    scores = compute_all_scores(all_claims)
    spec_scores = [s for s in scores if s["relevant"]]
    if kw_filter:
        # Further restrict to scores relevant to this specialty
        spec_score_names = {
            "cardiology":    {"HEART", "GRACE-ACS", "Wells-PE"},
            "pulmonology":   {"CURB-65", "Wells-PE", "PERC"},
            "infectiology":  {"qSOFA", "CURB-65"},
            "neurology":     set(),
            "nephrology":    {"qSOFA"},
            "gastroenterology": {"qSOFA"},
        }.get((specialty or "").lower(), set())
        if spec_score_names:
            spec_scores = [s for s in spec_scores if s["name"] in spec_score_names]

    if spec_scores:
        sections.append({
            "section": "Risk Scores",
            "items": [
                {
                    "name":           s["name"],
                    "score":          s["score"],
                    "interpretation": s["interpretation"],
                    "criteria_met":   s["criteria_met"],
                    "criteria_missing": s["criteria_missing"],
                    "recommendation": s["recommendation"],
                }
                for s in spec_scores
            ],
        })
        for s in spec_scores:
            if s["interpretation"] == "high":
                alerts.append({
                    "level":   "critical",
                    "message": f"{s['name']} HIGH RISK (score {s['score']})",
                    "context": s["recommendation"],
                })

    return {"alerts": alerts, "sections": sections}


def _build_lab_view(all_claims: list[dict]) -> dict:
    """Lab results, abnormal flags, requested but missing tests."""
    alerts = []
    sections = []

    # ── All lab claims with parsed values ────────────────────────────────────
    labs = lab_summary(all_claims)
    lab_items = []
    abnormal_items = []
    for token, r in sorted(labs.items()):
        item = {
            "parameter":  token.replace("_", " ").upper(),
            "value":      r.value,
            "unit":       r.unit,
            "qualitative":r.qualitative.upper(),
            "note":       r.clinical_note or "",
        }
        lab_items.append(item)
        if r.qualitative in ("high", "low"):
            abnormal_items.append(item)
            alerts.append({
                "level":   "warning" if r.qualitative == "high" else "info",
                "message": f"{token.upper()} {r.qualitative.upper()}: {r.value} {r.unit}",
                "context": r.clinical_note or "",
            })

    if lab_items:
        sections.append({"section": "Lab Results", "items": lab_items})
    if abnormal_items:
        sections.append({"section": "Abnormal Values", "items": abnormal_items})

    # ── Free-text lab claims not matched by parser ────────────────────────────
    unstructured_lab_items = []
    for c in all_claims:
        if c.get("claim_type") != "lab":
            continue
        if c.get("status") not in _ACTIVE_STATUSES:
            continue
        if not parse_lab_value(c["text"]):
            unstructured_lab_items.append({
                "text":   c["text"],
                "source": c.get("source_type", ""),
                "status": c.get("status", "active"),
            })
    if unstructured_lab_items:
        sections.append({
            "section": "Unstructured Lab Notes",
            "items":   unstructured_lab_items,
        })

    # ── Expected but not yet documented ──────────────────────────────────────
    documented_tokens = set(labs.keys())
    from reasoning_engine import evaluate_all_guidelines
    guidelines = evaluate_all_guidelines(all_claims)
    requested_terms: set[str] = set()
    for g in guidelines.values():
        for term in g.get("missing_priority", []):
            # Only include terms that map to known lab tokens
            for token, spec in LAB_THRESHOLDS.items():
                if term.lower() in spec.get("aliases", []) or term.lower() == token:
                    if token not in documented_tokens:
                        requested_terms.add(term)
    if requested_terms:
        sections.append({
            "section": "Requested / Pending",
            "items":   [{"test": t} for t in sorted(requested_terms)],
        })

    # ── Trend signals for lab parameters ─────────────────────────────────────
    trend_items = []
    for c in _trend_claims(all_claims):
        flag_m = _TREND_FLAG_RE.search(c.get("text", ""))
        flag   = flag_m.group(1) if flag_m else "trend"
        if any(kw in flag for kw in ("glycemia", "lactate", "creatinine")):
            trend_items.append({"flag": flag, "text": c["text"]})
    if trend_items:
        sections.append({"section": "Lab Trends", "items": trend_items})

    return {"alerts": alerts, "sections": sections}


def _build_chief_view(all_claims: list[dict]) -> dict:
    """Executive summary: leading hypothesis, top risks, decisions pending."""
    alerts = []
    sections = []

    # ── Case summary ─────────────────────────────────────────────────────────
    ranked  = rank_hypotheses(all_claims)
    leading = get_confident_leading(ranked)
    summary_item = {
        "confidence": leading.get("status", "unknown"),
        "leading":    leading.get("leading", "No active hypothesis"),
        "score":      leading.get("score"),
        "reason":     leading.get("reason", ""),
    }
    if leading.get("status") == "insufficient":
        alerts.append({
            "level":   "warning",
            "message": "Confidence insufficient: " + leading.get("reason", ""),
            "context": "",
        })
    sections.append({"section": "Case Summary", "items": [summary_item]})

    # Top 3 hypotheses overview
    if ranked:
        sections.append({
            "section": "Differential",
            "items": [
                {
                    "rank":  i + 1,
                    "text":  h["text"],
                    "score": h["rule_based_score"],
                    "type":  h["claim_type"],
                }
                for i, h in enumerate(ranked[:5])
            ],
        })

    # ── High-risk scores ──────────────────────────────────────────────────────
    scores = compute_all_scores(all_claims)
    high_risk = [s for s in scores if s["relevant"] and s["interpretation"] in ("high", "intermediate")]
    if high_risk:
        sections.append({
            "section": "Risk Flags",
            "items": [
                {
                    "score":          s["name"],
                    "value":          s["score"],
                    "interpretation": s["interpretation"],
                    "recommendation": s["recommendation"],
                }
                for s in high_risk[:4]
            ],
        })
        for s in high_risk:
            if s["interpretation"] == "high":
                alerts.append({
                    "level":   "critical",
                    "message": f"{s['name']} = HIGH RISK",
                    "context": s["recommendation"],
                })

    # ── Open issues / contested claims ───────────────────────────────────────
    open_items = [
        {
            "text":   c["text"],
            "status": c["status"],
            "type":   c.get("claim_type", ""),
        }
        for c in all_claims
        if c.get("status") in ("contested", "inferred")
    ]
    if open_items:
        sections.append({"section": "Open Issues", "items": open_items})
        alerts.append({
            "level":   "info",
            "message": f"{len(open_items)} claim(s) require review (contested/inferred)",
            "context": "",
        })

    # ── Statistics ────────────────────────────────────────────────────────────
    total   = len(all_claims)
    active  = sum(1 for c in all_claims if c.get("status") == "active")
    refuted = sum(1 for c in all_claims if c.get("status") == "refuted")
    sections.append({
        "section": "Case Statistics",
        "items": [{
            "total_claims":   total,
            "active_claims":  active,
            "refuted_claims": refuted,
            "hypotheses":     len(ranked),
        }],
    })

    return {"alerts": alerts, "sections": sections}


# ── Public API ────────────────────────────────────────────────────────────────

def build_role_view(
    role_raw: str,
    all_claims: list[dict],
    specialty: str | None = None,
) -> dict:
    """
    Build the role-specific clinical view for a given role string.

    Args:
        role_raw:   Role name (German or English; see ROLE_ALIASES).
        all_claims: All claims for the session.
        specialty:  Optional specialty for the 'specialist' role
                    (e.g. 'cardiology', 'pulmonology').

    Returns:
        dict with keys:
          role      — canonical role name
          alerts    — list of {level, message, context}
          sections  — list of {section, items: list[dict]}

    Raises:
        ValueError: unknown role string.
    """
    role = _resolve_role(role_raw)
    if role is None:
        raise ValueError(
            f"Unknown role '{role_raw}'. "
            f"Valid: {', '.join(sorted(set(ROLE_ALIASES.keys())))}"
        )

    if role == "nurse":
        view = _build_nurse_view(all_claims)
    elif role == "resident":
        view = _build_resident_view(all_claims)
    elif role == "specialist":
        view = _build_specialist_view(all_claims, specialty)
    elif role == "lab":
        view = _build_lab_view(all_claims)
    elif role == "chief":
        view = _build_chief_view(all_claims)
    else:
        raise ValueError(f"Unhandled role: {role}")

    return {
        "role":     role,
        "alerts":   view["alerts"],
        "sections": view["sections"],
    }

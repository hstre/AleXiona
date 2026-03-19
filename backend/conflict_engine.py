"""
Rule-based conflict detection for AleXiona V0.
Operates on claim dicts returned from Neo4j.
"""
import re
from models import Conflict, ConflictType, ConflictSeverity

_NEGATION_RE = re.compile(
    r'\b(kein[e]?|nicht|nein|ohne|fehlt|negativ|absent|no\b|not\b|without|negative|ruled out)\b',
    re.IGNORECASE,
)

_KEY_TERM_RE = re.compile(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b')


def _key_terms(text: str) -> set[str]:
    return set(_KEY_TERM_RE.findall(text.lower()))


def detect_conflicts(claims: list[dict]) -> list[Conflict]:
    active = [c for c in claims if c.get("status", "active") == "active"]
    conflicts: list[Conflict] = []

    # ── Rule 1: Competing diagnoses / hypotheses ─────────────────────────────
    lead_types = {"diagnosis", "hypothesis"}
    leads = [c for c in active if c.get("claim_type") in lead_types]
    if len(leads) >= 2:
        labels = " vs. ".join(
            f'"{c["text"][:45]}{"…" if len(c["text"]) > 45 else ""}"'
            for c in leads[:3]
        )
        conflicts.append(Conflict(
            id="conflict-competing",
            type=ConflictType.competing_hypothesis,
            severity=ConflictSeverity.warning,
            message=f"{len(leads)} competing leading claims detected: {labels}",
            affected_claim_ids=[c["id"] for c in leads],
        ))

    # ── Rule 2: Negation clash ───────────────────────────────────────────────
    for i, c1 in enumerate(active):
        for j, c2 in enumerate(active):
            if j <= i:
                continue
            t1, t2 = c1["text"], c2["text"]
            overlap = _key_terms(t1) & _key_terms(t2)
            if len(overlap) < 2:
                continue
            neg1, neg2 = bool(_NEGATION_RE.search(t1)), bool(_NEGATION_RE.search(t2))
            if neg1 != neg2:
                conflicts.append(Conflict(
                    id=f"conflict-negation-{i}-{j}",
                    type=ConflictType.negation,
                    severity=ConflictSeverity.error,
                    message=(
                        f'Contradictory claims detected: '
                        f'"{t1[:60]}{"…" if len(t1) > 60 else ""}" '
                        f'contradicts '
                        f'"{t2[:60]}{"…" if len(t2) > 60 else ""}"'
                    ),
                    affected_claim_ids=[c1["id"], c2["id"]],
                ))

    # ── Rule 3: High-support evidence + low-support lead hypothesis ──────────
    evidence_types = {"finding", "lab", "imaging", "symptom"}
    strong_evidence = [
        c for c in active
        if c.get("claim_type") in evidence_types
        and c.get("evidence_support_score", 0) >= 0.85
    ]
    weak_leads = [
        c for c in active
        if c.get("claim_type") in lead_types
        and c.get("evidence_support_score", 1) < 0.4
    ]
    if strong_evidence and weak_leads:
        conflicts.append(Conflict(
            id="conflict-evidence-mismatch",
            type=ConflictType.evidence_mismatch,
            severity=ConflictSeverity.info,
            message=(
                f"{len(strong_evidence)} strongly supported findings exist, "
                f"but {len(weak_leads)} hypothesis/diagnosis claim(s) have low evidence support. "
                "Consider revising the leading hypothesis."
            ),
            affected_claim_ids=[c["id"] for c in weak_leads],
        ))

    # ── Rule 4: Superseded status clash ─────────────────────────────────────
    superseded_ids = {c["id"] for c in claims if c.get("status") == "superseded"}
    for c in active:
        for dep_id in c.get("derived_from", []):
            if dep_id in superseded_ids:
                conflicts.append(Conflict(
                    id=f"conflict-stale-{c['id']}",
                    type=ConflictType.timeline_gap,
                    severity=ConflictSeverity.warning,
                    message=(
                        f'Claim "{c["text"][:60]}" is derived from a superseded claim. '
                        "Review whether it is still valid."
                    ),
                    affected_claim_ids=[c["id"], dep_id],
                ))

    return conflicts

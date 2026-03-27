"""
Rule-based conflict detection for AleXiona V0.
Operates on claim dicts returned from Neo4j.
"""
import logging
import re
from datetime import datetime, timezone, timedelta
from models import Conflict, ConflictType, ConflictSeverity, _parse_offset_hours

_log = logging.getLogger(__name__)

_NEGATION_RE = re.compile(
    r'\b(kein[e]?|nicht|nein|ohne|fehlt|negativ|absent|no\b|not\b|without|negative|ruled out)\b',
    re.IGNORECASE,
)

# Contradictory quantitative qualifiers (Rule 7)
_HIGH_RE = re.compile(
    r'\b(elevated|increased|high|raised|positive|erhöht|angestiegen|hoch|erhöhter|positiv)\b',
    re.IGNORECASE,
)
_LOW_RE = re.compile(
    r'\b(decreased|low|lowered|normal|reduced|within normal|erniedrigt|gesunken|niedrig|normwertig|unauffällig)\b',
    re.IGNORECASE,
)

_KEY_TERM_RE = re.compile(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b')


def _key_terms(text: str) -> set[str]:
    return set(_KEY_TERM_RE.findall(text.lower()))


_ACTIVE_STATUSES = {"active", "observed", "inferred", "confirmed", "contested"}
_LAB_TYPES       = {"lab"}
_STALE_LAB_HOURS = 48.0  # lab results older than this trigger stale_lab_evidence


def _claim_is_active(claim: dict) -> bool:
    """Return True if the claim is epistemically active (status + valid_until check)."""
    if claim.get("status", "active") not in _ACTIVE_STATUSES:
        return False
    valid_until = claim.get("valid_until")
    if valid_until is None:
        return True
    now = datetime.now(timezone.utc)
    if isinstance(valid_until, str):
        try:
            valid_until = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
        except ValueError:
            return True
    if hasattr(valid_until, "tzinfo") and valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    return valid_until >= now


def _parse_event_time(claim: dict) -> datetime | None:
    """Extract event_time as a timezone-aware datetime, or None."""
    et = claim.get("event_time")
    if et is None:
        return None
    if isinstance(et, datetime):
        return et.replace(tzinfo=timezone.utc) if et.tzinfo is None else et
    if isinstance(et, str):
        try:
            dt = datetime.fromisoformat(et.replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError:
            _log.debug("_parse_event_time: unparsebare event_time '%s' in claim %s", et, claim.get("id", "?"))
            return None
    return None


def detect_conflicts(claims: list[dict]) -> list[Conflict]:
    active = [c for c in claims if _claim_is_active(c)]
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
                    id=f"conflict-negation-{c1['id']}-{c2['id']}",
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

    # ── Rule 5: Active therapy with no active supporting indication ──────────
    # Fires when an active therapy shares ≥2 key terms with at least one
    # superseded/resolved lead, but zero active leads with the same overlap.
    inactive_leads = [
        c for c in claims
        if c.get("claim_type") in lead_types
        and c.get("status") in ("superseded", "resolved")
    ]
    active_therapies = [c for c in active if c.get("claim_type") == "therapy"]
    for therapy in active_therapies:
        th_terms = _key_terms(therapy["text"])
        matching_inactive = [l for l in inactive_leads if len(th_terms & _key_terms(l["text"])) >= 2]
        matching_active   = [l for l in leads         if len(th_terms & _key_terms(l["text"])) >= 2]
        if matching_inactive and not matching_active:
            top = matching_inactive[0]
            conflicts.append(Conflict(
                id=f"conflict-therapy-{therapy['id']}",
                type=ConflictType.therapy_without_indication,
                severity=ConflictSeverity.warning,
                message=(
                    f'Therapy "{therapy["text"][:60]}" appears to target '
                    f'"{top["text"][:50]}" which is now {top.get("status", "inactive")}. '
                    "Verify whether treatment is still indicated."
                ),
                affected_claim_ids=[therapy["id"]] + [l["id"] for l in matching_inactive[:2]],
            ))

    # ── Rule 6: Active hypothesis supported only by superseded evidence ───────
    superseded_evidence = [
        c for c in claims
        if c.get("claim_type") in evidence_types and c.get("status") == "superseded"
    ]
    for hyp in leads:  # leads = active diagnoses/hypotheses
        hyp_terms = _key_terms(hyp["text"])
        stale_support  = [e for e in superseded_evidence if len(hyp_terms & _key_terms(e["text"])) >= 2]
        active_support = [
            e for e in active
            if e.get("claim_type") in evidence_types
            and len(hyp_terms & _key_terms(e["text"])) >= 2
        ]
        if stale_support and not active_support:
            conflicts.append(Conflict(
                id=f"conflict-stale-hyp-{hyp['id']}",
                type=ConflictType.stale_hypothesis,
                severity=ConflictSeverity.warning,
                message=(
                    f'Hypothesis "{hyp["text"][:60]}" is supported only by '
                    f"superseded evidence ({len(stale_support)} superseded finding(s)). "
                    "Verify with current data."
                ),
                affected_claim_ids=[hyp["id"]] + [e["id"] for e in stale_support[:3]],
            ))

    # ── Rule 7: Contradictory quantitative values for same finding ────────────
    # Two active evidence claims share ≥2 key terms; one has a HIGH qualifier
    # and the other a LOW qualifier — e.g. "CRP elevated" vs "CRP within normal".
    # Distinct from negation (which catches "no fever" / "not present" patterns).
    for i, c1 in enumerate(active):
        if c1.get("claim_type") not in evidence_types:
            continue
        for j, c2 in enumerate(active):
            if j <= i or c2.get("claim_type") not in evidence_types:
                continue
            if len(_key_terms(c1["text"]) & _key_terms(c2["text"])) < 2:
                continue
            # Skip pairs already caught by the negation rule
            if _NEGATION_RE.search(c1["text"]) or _NEGATION_RE.search(c2["text"]):
                continue
            high1, low1 = bool(_HIGH_RE.search(c1["text"])), bool(_LOW_RE.search(c1["text"]))
            high2, low2 = bool(_HIGH_RE.search(c2["text"])), bool(_LOW_RE.search(c2["text"]))
            if (high1 and low2) or (low1 and high2):
                t1, t2 = c1["text"], c2["text"]
                conflicts.append(Conflict(
                    id=f"conflict-values-{c1['id']}-{c2['id']}",
                    type=ConflictType.contradictory_values,
                    severity=ConflictSeverity.error,
                    message=(
                        f'Contradictory values for the same finding: '
                        f'"{t1[:60]}{"…" if len(t1) > 60 else ""}" '
                        f'vs "{t2[:60]}{"…" if len(t2) > 60 else ""}"'
                    ),
                    affected_claim_ids=[c1["id"], c2["id"]],
                ))

    # ── Rule 8: Temporal inconsistency ────────────────────────────────────────
    # A claim has a time_offset earlier than one or more of the claims it
    # explicitly derives from — the child cannot logically precede its source.
    # Applies to all claims (not just active) — data-integrity issue regardless.
    offset_by_id = {c["id"]: _parse_offset_hours(c.get("time_offset")) for c in claims}
    for c in claims:
        child_h = _parse_offset_hours(c.get("time_offset"))
        if child_h is None:
            continue
        for src_id in c.get("derived_from", []):
            src_h = offset_by_id.get(src_id)
            if src_h is not None and child_h < src_h:
                conflicts.append(Conflict(
                    id=f"conflict-temporal-{c['id']}-{src_id}",
                    type=ConflictType.temporal_inconsistency,
                    severity=ConflictSeverity.error,
                    message=(
                        f'Claim "{c["text"][:55]}" (t+{child_h}h) is timestamped '
                        f'before its source claim (t+{src_h}h) — child cannot precede parent.'
                    ),
                    affected_claim_ids=[c["id"], src_id],
                ))

    # ── Rule 9: Stale lab evidence still driving active hypothesis ────────────
    # A lab claim with event_time older than STALE_LAB_HOURS that is the only
    # matching evidence for an active hypothesis — the clinician should re-test.
    # Applies only when event_time (absolute) is available.
    now = datetime.now(timezone.utc)
    lab_claims = [
        c for c in active
        if c.get("claim_type") in _LAB_TYPES
    ]
    for hyp in leads:
        hyp_terms = _key_terms(hyp["text"])
        supporting_labs = [
            lab for lab in lab_claims
            if len(hyp_terms & _key_terms(lab["text"])) >= 1
        ]
        for lab in supporting_labs:
            et = _parse_event_time(lab)
            if et is None:
                continue
            age_h = (now - et).total_seconds() / 3600
            if age_h > _STALE_LAB_HOURS:
                conflicts.append(Conflict(
                    id=f"conflict-stale-lab-{hyp['id']}-{lab['id']}",
                    type=ConflictType.stale_lab_evidence,
                    severity=ConflictSeverity.warning,
                    message=(
                        f'Lab result "{lab["text"][:55]}" is {age_h:.0f}h old '
                        f'(>{_STALE_LAB_HOURS:.0f}h threshold) but still supports '
                        f'hypothesis "{hyp["text"][:50]}". Consider repeating the test.'
                    ),
                    affected_claim_ids=[hyp["id"], lab["id"]],
                ))

    # ── Rule 10: Time paradox — assertion_time before event_time ─────────────
    # A claim that was documented (assertion_time) before the event it describes
    # (event_time) is a physical impossibility — data-integrity error.
    for c in claims:
        et = _parse_event_time(c)
        if et is None:
            continue
        at_raw = c.get("assertion_time")
        if at_raw is None:
            continue
        if isinstance(at_raw, str):
            try:
                at = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
                at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
            except ValueError:
                continue
        elif isinstance(at_raw, datetime):
            at = at_raw.replace(tzinfo=timezone.utc) if at_raw.tzinfo is None else at_raw
        else:
            continue
        if at < et:
            delta_h = (et - at).total_seconds() / 3600
            conflicts.append(Conflict(
                id=f"conflict-time-paradox-{c['id']}",
                type=ConflictType.time_paradox,
                severity=ConflictSeverity.error,
                message=(
                    f'Claim "{c["text"][:55]}" has assertion_time {delta_h:.1f}h '
                    f'BEFORE its event_time — impossible; likely a documentation error.'
                ),
                affected_claim_ids=[c["id"]],
            ))

    return conflicts

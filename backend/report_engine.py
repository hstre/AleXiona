"""
Clinical report context builder for AleXiona.

Assembles a structured prompt context from the claim graph for each
supported report type, so the LLM can generate appropriate narrative
prose for each section.

Supported report types:
  arztbrief    — Ärztlicher Brief (Entlass- oder Verlegungsbrief)
  entlassbrief — Kurzarztbrief / Entlassbrief (subset of Arztbrief)
  konsilbrief  — Konsiliarbrief (Antwort an anfragende Stelle)
  befundbericht — Befundbericht (Labor / Bildgebung / EKG)
"""
from __future__ import annotations
from lab_parser import lab_summary
from reasoning_engine import rank_hypotheses, evaluate_all_guidelines
from composite_scores import compute_all_scores
from models import PatientContext

# ── Report type definitions ────────────────────────────────────────────────────

REPORT_TYPES: dict[str, dict] = {
    "arztbrief": {
        "title":       "Ärztlicher Brief",
        "description": "Vollständiger Arztbrief mit Anamnese, Befund, Diagnosen, Verlauf, Therapie und Procedere",
        "sections": [
            {"key": "anamnese",    "title": "Anamnese",             "required": True},
            {"key": "befund",      "title": "Klinischer Befund",    "required": True},
            {"key": "diagnostik",  "title": "Diagnostik",           "required": True},
            {"key": "diagnosen",   "title": "Diagnosen",            "required": True},
            {"key": "verlauf",     "title": "Verlauf",              "required": False},
            {"key": "therapie",    "title": "Therapie",             "required": True},
            {"key": "procedere",   "title": "Procedere / Empfehlungen", "required": True},
        ],
    },
    "entlassbrief": {
        "title":       "Entlassbrief",
        "description": "Kurzarztbrief für die Entlassung — komprimiert, fokussiert auf Diagnosen und Procedere",
        "sections": [
            {"key": "anamnese",       "title": "Anamnese (kurz)",       "required": True},
            {"key": "diagnostik",     "title": "Wesentliche Diagnostik", "required": True},
            {"key": "diagnosen",      "title": "Diagnosen",              "required": True},
            {"key": "therapie",       "title": "Therapie",               "required": True},
            {"key": "entlassstatus",  "title": "Entlassstatus",          "required": True},
            {"key": "procedere",      "title": "Procedere / Empfehlungen", "required": True},
        ],
    },
    "konsilbrief": {
        "title":       "Konsiliarbrief",
        "description": "Antwortschreiben auf eine Konsiliarbestellung — Befund, Diagnose, Empfehlung",
        "sections": [
            {"key": "fragestellung",  "title": "Fragestellung",    "required": True},
            {"key": "befund",         "title": "Befund",            "required": True},
            {"key": "diagnosen",      "title": "Diagnosen",         "required": True},
            {"key": "beurteilung",    "title": "Beurteilung",       "required": True},
            {"key": "empfehlung",     "title": "Empfehlung",        "required": True},
        ],
    },
    "befundbericht": {
        "title":       "Befundbericht",
        "description": "Strukturierter Befundbericht (Labor, Bildgebung oder EKG)",
        "sections": [
            {"key": "material",    "title": "Material / Untersuchung", "required": True},
            {"key": "befund",      "title": "Befund",                  "required": True},
            {"key": "beurteilung", "title": "Beurteilung",             "required": True},
        ],
    },
}

_ACTIVE_STATUSES  = {"active", "observed", "inferred", "confirmed", "contested"}
_EVIDENCE_TYPES   = {"finding", "lab", "imaging", "symptom"}
_REVISED_STATUSES = {"refuted", "superseded", "withdrawn"}
_HIGH_TRUST_SOURCES = {"clinician", "lab_system", "imaging_model"}


def _epistemic_tag(claim: dict) -> str:
    """
    Classify one claim into an epistemic status tag:

      [GESICHERT]   — confirmed or high-quality active evidence
      [VERDACHT]    — inferred, unconfirmed, or LLM-extracted
      [REVIDIERT]   — refuted / superseded / withdrawn
      [AUSSTEHEND]  — used externally for missing_critical items
    """
    status = claim.get("status", "active")
    if status in _REVISED_STATUSES:
        return "[REVIDIERT]"
    ess    = float(claim.get("evidence_support_score") or 0.8)
    source = claim.get("source_type", "llm")
    if status == "confirmed" or (ess >= 0.75 and source in _HIGH_TRUST_SOURCES):
        return "[GESICHERT]"
    return "[VERDACHT]"


def _build_epistemic_section(all_claims: list[dict], missing_critical: list[str]) -> str:
    """
    Build a compact epistemic status table for all claims + missing items.
    Injected into the LLM prompt so the report can carry provenance tags.
    """
    lines: list[str] = ["=== EPISTEMISCHER STATUS DER CLAIMS ==="]
    lines.append("Verwende diese Tags in deinem Bericht: [GESICHERT], [VERDACHT], [REVIDIERT], [AUSSTEHEND]")
    lines.append("")

    # Group by tag
    gesichert = []
    verdacht  = []
    revidiert = []

    for c in all_claims:
        tag = _epistemic_tag(c)
        entry = f"  {tag} {c['text']}"
        if tag == "[GESICHERT]":
            gesichert.append(entry)
        elif tag == "[REVIDIERT]":
            revidiert.append(entry)
        else:
            verdacht.append(entry)

    if gesichert:
        lines.append("Gesicherte Befunde:")
        lines.extend(gesichert)
        lines.append("")
    if verdacht:
        lines.append("Verdacht / nicht gesichert:")
        lines.extend(verdacht)
        lines.append("")
    if revidiert:
        lines.append("Revidierte / widerrufene Befunde:")
        lines.extend(revidiert)
        lines.append("")
    if missing_critical:
        lines.append("Ausstehende / fehlende kritische Untersuchungen:")
        for m in missing_critical:
            lines.append(f"  [AUSSTEHEND] {m}")
        lines.append("")

    return "\n".join(lines)


def _build_claim_context(all_claims: list[dict]) -> str:
    """Assemble a compact, structured context string for report generation."""
    lines: list[str] = []

    # Diagnoses / hypotheses
    ranked = rank_hypotheses(all_claims)
    if ranked:
        lines.append("=== AKTIVE DIAGNOSEN / HYPOTHESEN (nach Score) ===")
        guidelines = evaluate_all_guidelines(all_claims)
        for h in ranked:
            g = guidelines.get(h["text"], {})
            req_ok  = g.get("required_present", [])
            req_mis = g.get("required_missing", [])
            lines.append(
                f"  [{h['claim_type'].upper()}] {h['text']}"
                f" (score={h['rule_based_score']:.2f},"
                f" supporting={len(h['supporting_claim_ids'])},"
                f" conflicting={len(h['conflicting_claim_ids'])})"
            )
            if req_ok:
                lines.append(f"    Leitkriterien erfüllt: {', '.join(req_ok)}")
            if req_mis:
                lines.append(f"    Leitkriterien fehlend: {', '.join(req_mis)}")
        lines.append("")

    # Parsed lab values
    labs = lab_summary(all_claims)
    if labs:
        lines.append("=== LABORWERTE ===")
        for token, r in sorted(labs.items()):
            flag = f" [{r.qualitative.upper()}]" if r.qualitative != "normal" else ""
            lines.append(f"  {token}: {r.value} {r.unit}{flag}"
                         + (f" — {r.clinical_note}" if r.clinical_note else ""))
        lines.append("")

    # Clinical findings / symptoms
    findings = [c for c in all_claims
                if c.get("claim_type") in ("finding", "symptom")
                and c.get("status") in _ACTIVE_STATUSES]
    if findings:
        lines.append("=== KLINISCHER BEFUND / SYMPTOME ===")
        for c in findings:
            lines.append(f"  [{c['claim_type'].upper()}] {c['text']}"
                         f" (src={c.get('source_type','')}, ess={c.get('evidence_support_score',0):.0%})")
        lines.append("")

    # Imaging
    imaging = [c for c in all_claims
               if c.get("claim_type") == "imaging" and c.get("status") in _ACTIVE_STATUSES]
    if imaging:
        lines.append("=== BILDGEBUNG ===")
        for c in imaging:
            lines.append(f"  {c['text']}")
        lines.append("")

    # Therapy
    therapy = [c for c in all_claims
               if c.get("claim_type") == "therapy" and c.get("status") in _ACTIVE_STATUSES]
    if therapy:
        lines.append("=== THERAPIE ===")
        for c in therapy:
            lines.append(f"  {c['text']}")
        lines.append("")

    # Risk factors / history
    history = [c for c in all_claims
               if c.get("claim_type") == "risk_factor" and c.get("status") in _ACTIVE_STATUSES]
    if history:
        lines.append("=== RISIKOFAKTOREN / VORGESCHICHTE ===")
        for c in history:
            lines.append(f"  {c['text']}")
        lines.append("")

    # Relevant risk scores
    scores = compute_all_scores(all_claims)
    relevant = [s for s in scores if s["relevant"]]
    if relevant:
        lines.append("=== KLINISCHE SCORES ===")
        for s in relevant:
            lines.append(
                f"  {s['name']}: {s['score']} → {s['interpretation'].upper()} RISK"
                f" — {s['recommendation']}"
            )
        lines.append("")

    return "\n".join(lines)


def build_report_prompt(
    report_type: str,
    all_claims: list[dict],
    patient_context: PatientContext | None = None,
    missing_critical: list[str] | None = None,
) -> str:
    """
    Build a complete LLM prompt for clinical report generation.

    Args:
        report_type:     One of the REPORT_TYPES keys.
        all_claims:      All claims for the session.
        patient_context: Optional free-text meta (name, DOB, ward, etc.).

    Returns:
        Prompt string ready to send to the LLM.
    """
    rt = REPORT_TYPES.get(report_type)
    if not rt:
        raise ValueError(f"Unknown report type '{report_type}'. "
                         f"Valid: {', '.join(REPORT_TYPES)}")

    sections_str = "\n".join(
        f'  "{s["key"]}": "<{s["title"]}>"'
        for s in rt["sections"]
    )
    claim_context    = _build_claim_context(all_claims)
    epistemic_block  = _build_epistemic_section(all_claims, missing_critical or [])

    patient_block = ""
    if patient_context:
        patient_block = "\n=== PATIENTENKONTEXT ===\n" + "\n".join(
            f"  {k}: {v}" for k, v in patient_context.model_dump(exclude_none=True).items() if v
        ) + "\n"

    return f"""Du bist ein klinischer Dokumentationsassistent.
Erstelle auf Basis der folgenden Fallzusammenfassung einen vollständigen **{rt['title']}**.

Anforderungen:
- Medizinisch präzise, in vollständigen Sätzen (kein Bullet-Point-Stil)
- Formulierung in der 3. Person (z.B. "Die Patientin / Der Patient wurde ...")
- Zeitform: Präteritum für Ereignisse, Präsens für Befunde und Diagnosen
- Keine diagnostischen Schlussfolgerungen, die nicht durch die vorliegenden Befunde gestützt werden
- Fehlende Angaben mit "[nicht dokumentiert]" kennzeichnen
- Klinische Scores und Laborwerte direkt in den passenden Abschnitt integrieren
- Sprache: Deutsch (medizinischer Fachstil)
- Epistemische Transparenz: Kennzeichne Aussagen mit den vorgegebenen Tags:
    [GESICHERT]   für klinisch gesicherte Befunde (bestätigt, hohe Evidenz)
    [VERDACHT]    für nicht gesicherte Hypothesen oder LLM-extrahierte Claims
    [REVIDIERT]   für widerrufene oder widerlegte Befunde (nur im Verlauf erwähnen)
    [AUSSTEHEND]  für noch ausstehende Untersuchungen / fehlende Befunde
  Füge diese Tags direkt im Fließtext ein, z.B.:
  "Es bestand klinisch [GESICHERT] eine Tachykardie ... [VERDACHT] auf eine Lungenembolie ..."
{patient_block}
=== FALLZUSAMMENFASSUNG AUS DEM EVIDENZGRAPHEN ===
{claim_context}

{epistemic_block}

Antworte AUSSCHLIESSLICH mit gültigem JSON in folgendem Format:
{{
{sections_str}
}}

Halte jeden Abschnitt prägnant (2–6 Sätze). Verwende nur Informationen aus der Fallzusammenfassung."""

"""
Demo seed: creates a complete pneumonia/sepsis clinical scenario
with multiple claim types, temporal progression, and conflicts.
"""
import uuid
from datetime import datetime, timezone
from neo4j import GraphDatabase
import os
import json

DEMO_CLAIMS = [
    # t+0h – Admission
    {
        "text": "Patient presents with high fever (39.4 °C) since 2 days",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.95, "status": "active",
        "entities": ["Fever", "39.4°C"],
        "relations": [{"from_entity": "Fever", "to_entity": "Infection", "type": "indicates"}],
    },
    {
        "text": "Dyspnea at rest with O2 saturation 91% on room air",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.90, "status": "active",
        "entities": ["Dyspnea", "O2-Saturation", "91%"],
        "relations": [{"from_entity": "Dyspnea", "to_entity": "Respiratory Failure", "type": "indicates"}],
    },
    {
        "text": "Productive cough with yellow-green sputum",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "stable",
        "evidence_support_score": 0.85, "status": "active",
        "entities": ["Cough", "Sputum"],
        "relations": [{"from_entity": "Cough", "to_entity": "Pneumonia", "type": "indicates"}],
    },
    # t+6h – Lab results
    {
        "text": "Leukocyte count elevated: 16,400/μL (reference 4,000–10,000)",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+6h", "trend": "worsening",
        "evidence_support_score": 0.98, "status": "active",
        "entities": ["Leukocytes", "16,400/μL"],
        "relations": [{"from_entity": "Leukocytes", "to_entity": "Leukocytosis", "type": "is"},
                      {"from_entity": "Leukocytosis", "to_entity": "Bacterial Infection", "type": "indicates"}],
    },
    {
        "text": "CRP markedly elevated: 184 mg/L (reference <5 mg/L)",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+6h", "trend": "worsening",
        "evidence_support_score": 0.97, "status": "active",
        "entities": ["CRP", "184 mg/L"],
        "relations": [{"from_entity": "CRP", "to_entity": "Systemic Inflammation", "type": "indicates"}],
    },
    {
        "text": "Procalcitonin 2.8 ng/mL – bacterial infection likely",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+6h", "trend": "stable",
        "evidence_support_score": 0.88, "status": "active",
        "entities": ["Procalcitonin", "2.8 ng/mL"],
        "relations": [{"from_entity": "Procalcitonin", "to_entity": "Bacterial Infection", "type": "supports"}],
    },
    # t+8h – Imaging
    {
        "text": "CT chest: right lower lobe consolidation with air bronchograms",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+8h", "trend": "stable",
        "evidence_support_score": 0.99, "status": "active",
        "entities": ["Right Lower Lobe", "Consolidation", "Air Bronchograms"],
        "relations": [{"from_entity": "Consolidation", "to_entity": "Pneumonia", "type": "indicates"}],
    },
    {
        "text": "No pleural effusion, no pulmonary embolism features on CT",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+8h", "trend": "stable",
        "evidence_support_score": 0.92, "status": "active",
        "entities": ["Pleural Effusion", "Pulmonary Embolism"],
        "relations": [{"from_entity": "CT", "to_entity": "Pulmonary Embolism", "type": "rules_out"}],
    },
    # t+8h – Hypotheses
    {
        "text": "Community-acquired pneumonia (CAP) – leading hypothesis",
        "claim_type": "diagnosis", "source_type": "llm",
        "time_offset": "t+8h", "trend": "stable",
        "evidence_support_score": 0.82, "status": "active",
        "entities": ["Community-acquired Pneumonia", "CAP"],
        "relations": [{"from_entity": "CAP", "to_entity": "Bacterial Infection", "type": "is"}],
    },
    {
        "text": "Sepsis secondary to pneumonia – cannot be excluded",
        "claim_type": "hypothesis", "source_type": "llm",
        "time_offset": "t+8h", "trend": "unknown",
        "evidence_support_score": 0.45, "status": "active",
        "entities": ["Sepsis", "Pneumonia"],
        "relations": [{"from_entity": "Pneumonia", "to_entity": "Sepsis", "type": "causes"}],
    },
    # t+24h – Follow-up
    {
        "text": "After antibiotic therapy (amoxicillin-clavulanate): fever resolved",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+24h", "trend": "improving",
        "evidence_support_score": 0.90, "status": "active",
        "entities": ["Amoxicillin-Clavulanate", "Fever"],
        "relations": [{"from_entity": "Amoxicillin-Clavulanate", "to_entity": "Fever", "type": "reduces"}],
    },
    {
        "text": "O2 saturation improved to 96% after 2L supplemental oxygen",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+24h", "trend": "improving",
        "evidence_support_score": 0.93, "status": "active",
        "entities": ["O2-Saturation", "96%", "Supplemental Oxygen"],
        "relations": [{"from_entity": "Supplemental Oxygen", "to_entity": "O2-Saturation", "type": "enables"}],
    },
    # t+24h – Superseded
    {
        "text": "Initial suspicion of viral pneumonia – superseded by bacterial findings",
        "claim_type": "hypothesis", "source_type": "llm",
        "time_offset": "t+0h", "trend": "unknown",
        "evidence_support_score": 0.20, "status": "superseded",
        "entities": ["Viral Pneumonia"],
        "relations": [],
    },
]


DEMO_CLAIMS_DE = [
    # t+0h – Aufnahme
    {
        "text": "Patient stellt sich mit Hochfieber (39,4 °C) seit 2 Tagen vor",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.95, "status": "active",
        "entities": ["Fieber", "39,4°C"],
        "relations": [{"from_entity": "Fieber", "to_entity": "Infektion", "type": "indicates"}],
    },
    {
        "text": "Dyspnoe in Ruhe mit O2-Sättigung 91% bei Raumluft",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.90, "status": "active",
        "entities": ["Dyspnoe", "O2-Sättigung", "91%"],
        "relations": [{"from_entity": "Dyspnoe", "to_entity": "Ateminsuffizienz", "type": "indicates"}],
    },
    {
        "text": "Produktiver Husten mit gelblich-grünem Sputum",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "stable",
        "evidence_support_score": 0.85, "status": "active",
        "entities": ["Husten", "Sputum"],
        "relations": [{"from_entity": "Husten", "to_entity": "Pneumonie", "type": "indicates"}],
    },
    # t+6h – Laborbefunde
    {
        "text": "Leukozyten erhöht: 16.400/μL (Referenz 4.000–10.000)",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+6h", "trend": "worsening",
        "evidence_support_score": 0.98, "status": "active",
        "entities": ["Leukozyten", "16.400/μL"],
        "relations": [{"from_entity": "Leukozyten", "to_entity": "Leukozytose", "type": "is"},
                      {"from_entity": "Leukozytose", "to_entity": "Bakterielle Infektion", "type": "indicates"}],
    },
    {
        "text": "CRP deutlich erhöht: 184 mg/L (Referenz <5 mg/L)",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+6h", "trend": "worsening",
        "evidence_support_score": 0.97, "status": "active",
        "entities": ["CRP", "184 mg/L"],
        "relations": [{"from_entity": "CRP", "to_entity": "Systemische Entzündung", "type": "indicates"}],
    },
    {
        "text": "Procalcitonin 2,8 ng/mL – bakterielle Infektion wahrscheinlich",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+6h", "trend": "stable",
        "evidence_support_score": 0.88, "status": "active",
        "entities": ["Procalcitonin", "2,8 ng/mL"],
        "relations": [{"from_entity": "Procalcitonin", "to_entity": "Bakterielle Infektion", "type": "supports"}],
    },
    # t+8h – Bildgebung
    {
        "text": "CT-Thorax: Konsolidierung im rechten Unterlappen mit Luftbronchogramm",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+8h", "trend": "stable",
        "evidence_support_score": 0.99, "status": "active",
        "entities": ["Rechter Unterlappen", "Konsolidierung", "Luftbronchogramm"],
        "relations": [{"from_entity": "Konsolidierung", "to_entity": "Pneumonie", "type": "indicates"}],
    },
    {
        "text": "Kein Pleuraerguss, kein Nachweis einer Lungenembolie im CT",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+8h", "trend": "stable",
        "evidence_support_score": 0.92, "status": "active",
        "entities": ["Pleuraerguss", "Lungenembolie"],
        "relations": [{"from_entity": "CT", "to_entity": "Lungenembolie", "type": "rules_out"}],
    },
    # t+8h – Diagnosen
    {
        "text": "Ambulant erworbene Pneumonie (CAP) – Leitdiagnose",
        "claim_type": "diagnosis", "source_type": "llm",
        "time_offset": "t+8h", "trend": "stable",
        "evidence_support_score": 0.82, "status": "active",
        "entities": ["Ambulant erworbene Pneumonie", "CAP"],
        "relations": [{"from_entity": "CAP", "to_entity": "Bakterielle Infektion", "type": "is"}],
    },
    {
        "text": "Sepsis sekundär bei Pneumonie – kann nicht ausgeschlossen werden",
        "claim_type": "hypothesis", "source_type": "llm",
        "time_offset": "t+8h", "trend": "unknown",
        "evidence_support_score": 0.45, "status": "active",
        "entities": ["Sepsis", "Pneumonie"],
        "relations": [{"from_entity": "Pneumonie", "to_entity": "Sepsis", "type": "causes"}],
    },
    # t+24h – Verlauf
    {
        "text": "Nach antibiotischer Therapie (Amoxicillin-Clavulansäure): Fieber abgeklungen",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+24h", "trend": "improving",
        "evidence_support_score": 0.90, "status": "active",
        "entities": ["Amoxicillin-Clavulansäure", "Fieber"],
        "relations": [{"from_entity": "Amoxicillin-Clavulansäure", "to_entity": "Fieber", "type": "reduces"}],
    },
    {
        "text": "O2-Sättigung auf 96% nach 2L Sauerstoffgabe verbessert",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+24h", "trend": "improving",
        "evidence_support_score": 0.93, "status": "active",
        "entities": ["O2-Sättigung", "96%", "Sauerstoffgabe"],
        "relations": [{"from_entity": "Sauerstoffgabe", "to_entity": "O2-Sättigung", "type": "enables"}],
    },
    # t+24h – Überholt
    {
        "text": "Initialverdacht auf virale Pneumonie – durch bakterielle Befunde überholt",
        "claim_type": "hypothesis", "source_type": "llm",
        "time_offset": "t+0h", "trend": "unknown",
        "evidence_support_score": 0.20, "status": "superseded",
        "entities": ["Virale Pneumonie"],
        "relations": [],
    },
]


def seed_demo(session_id: str, lang: str = "en"):
    uri      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
    user     = os.getenv("NEO4J_USER",     "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "alexiona123")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    claims = DEMO_CLAIMS_DE if lang == "de" else DEMO_CLAIMS

    with driver.session() as s:
        # Check if already seeded
        result = s.run(
            "MATCH (c:Claim {session_id: $sid}) RETURN count(c) AS n",
            sid=session_id
        )
        if result.single()["n"] > 0:
            driver.close()
            return {"seeded": False, "reason": "Session already has claims"}

        created = []
        now_base = datetime.now(timezone.utc)

        for i, claim in enumerate(claims):
            cid = str(uuid.uuid4())
            created.append(cid)
            ts  = now_base.isoformat()

            s.run(
                """
                CREATE (c:Claim {
                    id: $id, text: $text, session_id: $sid,
                    evidence_support_score: $ess, claim_type: $ct,
                    source_type: $st, source_ref: $sr,
                    derived_from: $df, status: $status,
                    time_offset: $to, trend: $trend,
                    created_at: $now
                })
                """,
                id=cid, text=claim["text"], sid=session_id,
                ess=claim["evidence_support_score"],
                ct=claim["claim_type"], st=claim["source_type"],
                sr="", df="[]", status=claim["status"],
                to=claim["time_offset"], trend=claim["trend"],
                now=ts,
            )

            for entity in claim.get("entities", []):
                s.run(
                    """
                    MERGE (e:Entity {name: $name})
                    WITH e MATCH (c:Claim {id: $cid})
                    MERGE (c)-[:MENTIONS]->(e)
                    """,
                    name=entity, cid=cid,
                )

            for rel in claim.get("relations", []):
                s.run(
                    """
                    MERGE (f:Entity {name: $from_name})
                    MERGE (t:Entity {name: $to_name})
                    MERGE (f)-[r:RELATION {type: $rel_type}]->(t)
                    """,
                    from_name=rel["from_entity"],
                    to_name=rel["to_entity"],
                    rel_type=rel["type"],
                )

    driver.close()
    return {"seeded": True, "claim_count": len(claims)}

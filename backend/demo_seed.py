"""
Demo seed: creates a complete pneumonia/sepsis clinical scenario
with multiple claim types, temporal progression, and conflicts.

All seeding now goes through neo4j_client.store_claims() so every Claim
receives full provenance fields (evidence_tier, uncertainty_flag, etc.)
and an AuditEvent is generated for each seeded claim.
"""
import uuid
from datetime import datetime, timezone
import os
import json

# ── evidence_tier derivation (mirrors intake layer logic) ────────────────────

_EVIDENCE_TIER_MAP = {
    "lab_system":        "lab_confirmed",
    "clinician":         "clinician_observed",
    "llm":               "clinician_observed",
    "imaging_model":     "instrument_measured",
    "imported_document": "clinician_observed",
    "guideline":         "guideline_structured",
    "patient_report":    "patient_generated",
    "caregiver_report":  "patient_generated",
    "wearable":          "patient_generated",
    "home_device":       "patient_generated",
}


def _dict_to_claim(d: dict):
    """Convert a raw seed-dict to a validated Claim model instance."""
    from models import Claim, Relation

    source_type = d.get("source_type", "llm")
    relations = [
        Relation(from_entity=r["from_entity"], to_entity=r["to_entity"], type=r["type"])
        for r in d.get("relations", [])
    ]
    return Claim(
        text=d["text"],
        entities=d.get("entities", []),
        relations=relations,
        evidence_support_score=d.get("evidence_support_score", 0.8),
        claim_type=d.get("claim_type", "finding"),
        source_type=source_type,
        source_ref=d.get("source_ref", ""),
        evidence_tier=_EVIDENCE_TIER_MAP.get(source_type, "clinician_observed"),
        status=d.get("status", "active"),
        time_offset=d.get("time_offset"),
        trend=d.get("trend", "unknown"),
        uncertainty_flag=bool(d.get("uncertainty_flag", False)),
        assumptions=d.get("assumptions", []),
    )

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
    # ── patient-generated layer ───────────────────────────────────────────────
    # These are added to the demo to illustrate the intake layer epistemic split
    {
        "text": "I've had a fever and difficulty breathing since yesterday — I measured 38.8 °C at home",
        "claim_type": "symptom", "source_type": "patient_report",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.55, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["Fever", "38.8°C", "Dyspnea"],
        "relations": [],
    },
    {
        "text": "SpO2 91% via home pulse oximeter",
        "claim_type": "lab", "source_type": "home_device",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.72, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["SpO2", "91%"],
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
    # ── patientengenerierte Daten (Intake Layer Demo) ─────────────────────────
    {
        "text": "Ich habe seit gestern Fieber und Atemnot – zuhause 38,8 °C gemessen",
        "claim_type": "symptom", "source_type": "patient_report",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.55, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["Fieber", "38,8 °C", "Atemnot"],
        "relations": [],
    },
    {
        "text": "SpO2 91% via häusliches Pulsoximeter",
        "claim_type": "lab", "source_type": "home_device",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.72, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["SpO2", "91%"],
        "relations": [],
    },
]


# ── Scenario: Pulmonary Embolism (PE) ────────────────────────────────────────

PE_CLAIMS = [
    # t+0h – Presentation
    {
        "text": "Sudden onset chest pain and severe dyspnea, onset 2 hours ago",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.92, "status": "active",
        "entities": ["Chest Pain", "Dyspnea"],
        "relations": [{"from_entity": "Chest Pain", "to_entity": "Pulmonary Embolism", "type": "indicates"}],
    },
    {
        "text": "Heart rate 118 bpm (tachycardia), blood pressure 96/62 mmHg",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.90, "status": "active",
        "entities": ["Tachycardia", "Hypotension"],
        "relations": [{"from_entity": "Tachycardia", "to_entity": "Hemodynamic Instability", "type": "indicates"}],
    },
    {
        "text": "SpO2 88% on room air — significant hypoxemia",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.95, "status": "active",
        "entities": ["SpO2", "Hypoxemia"],
        "relations": [{"from_entity": "Hypoxemia", "to_entity": "Respiratory Failure", "type": "indicates"}],
    },
    {
        "text": "Wells score 7 — high clinical probability for pulmonary embolism",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "stable",
        "evidence_support_score": 0.88, "status": "active",
        "entities": ["Wells Score", "7"],
        "relations": [{"from_entity": "Wells Score", "to_entity": "Pulmonary Embolism", "type": "indicates"}],
    },
    # t+2h – Labs
    {
        "text": "D-Dimer markedly elevated: 4.8 µg/mL (reference < 0.5 µg/mL)",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+2h", "trend": "stable",
        "evidence_support_score": 0.94, "status": "active",
        "entities": ["D-Dimer", "4.8 µg/mL"],
        "relations": [{"from_entity": "D-Dimer", "to_entity": "Thrombosis", "type": "indicates"}],
    },
    {
        "text": "Troponin I mildly elevated: 0.12 ng/mL — right ventricular strain",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+2h", "trend": "stable",
        "evidence_support_score": 0.80, "status": "active",
        "entities": ["Troponin I", "0.12 ng/mL", "Right Ventricular Strain"],
        "relations": [{"from_entity": "Troponin", "to_entity": "Right Heart Strain", "type": "indicates"}],
    },
    {
        "text": "BNP elevated: 380 pg/mL — pressure overload right ventricle",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+2h", "trend": "stable",
        "evidence_support_score": 0.78, "status": "active",
        "entities": ["BNP", "380 pg/mL", "Right Ventricle"],
        "relations": [{"from_entity": "BNP", "to_entity": "Right Heart Strain", "type": "indicates"}],
    },
    # t+2h – ECG
    {
        "text": "ECG: S1Q3T3 pattern — classic sign of acute right heart strain",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+2h", "trend": "stable",
        "evidence_support_score": 0.75, "status": "active",
        "entities": ["ECG", "S1Q3T3", "Right Heart Strain"],
        "relations": [{"from_entity": "S1Q3T3", "to_entity": "Right Heart Strain", "type": "indicates"}],
    },
    # t+4h – CT-PA
    {
        "text": "CT-pulmonary angiography: saddle embolus at bifurcation, bilateral main pulmonary arteries",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.99, "status": "active",
        "entities": ["Saddle Embolus", "Pulmonary Arteries", "CT-PA"],
        "relations": [{"from_entity": "Saddle Embolus", "to_entity": "Pulmonary Embolism", "type": "is"}],
    },
    {
        "text": "Echo: right ventricular dilation, D-sign on short axis, McConnell sign positive",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.91, "status": "active",
        "entities": ["Right Ventricle", "D-Sign", "McConnell Sign"],
        "relations": [{"from_entity": "RV Dilation", "to_entity": "Right Heart Strain", "type": "indicates"}],
    },
    # t+4h – Hypothesis
    {
        "text": "High-risk pulmonary embolism with hemodynamic compromise — leading diagnosis",
        "claim_type": "diagnosis", "source_type": "llm",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.96, "status": "active",
        "entities": ["Pulmonary Embolism", "High-risk"],
        "relations": [{"from_entity": "PE", "to_entity": "Hemodynamic Instability", "type": "causes"}],
    },
    {
        "text": "Acute myocardial infarction — cannot be fully excluded, troponin elevation noted",
        "claim_type": "hypothesis", "source_type": "llm",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.18, "status": "active",
        "entities": ["Myocardial Infarction", "Troponin"],
        "relations": [],
    },
    # t+5h – Treatment
    {
        "text": "Systemic thrombolysis with rtPA initiated — criteria met (high-risk PE + hemodynamic instability)",
        "claim_type": "therapy", "source_type": "clinician",
        "time_offset": "t+5h", "trend": "improving",
        "evidence_support_score": 0.92, "status": "active",
        "entities": ["rtPA", "Thrombolysis"],
        "relations": [{"from_entity": "rtPA", "to_entity": "Pulmonary Embolism", "type": "reduces"}],
    },
    # ── patient-generated layer ───────────────────────────────────────────────
    {
        "text": "Sudden chest pain and shortness of breath — started during a long flight about 2 hours ago",
        "claim_type": "symptom", "source_type": "patient_report",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.60, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["Chest Pain", "Dyspnea"],
        "relations": [],
    },
    {
        "text": "Heart rate 122 bpm via smartwatch — elevated for the last 3 hours",
        "claim_type": "finding", "source_type": "wearable",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.68, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["Heart Rate", "122 bpm"],
        "relations": [],
    },
]


# ── Scenario: ARDS + Septic Shock ────────────────────────────────────────────

ARDS_SEPSIS_CLAIMS = [
    # t+0h – ICU admission
    {
        "text": "Septic shock: MAP < 65 mmHg despite 2L IV fluids, requiring norepinephrine 0.4 µg/kg/min",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.97, "status": "active",
        "entities": ["Septic Shock", "Norepinephrine", "MAP"],
        "relations": [{"from_entity": "Septic Shock", "to_entity": "Organ Failure", "type": "causes"}],
    },
    {
        "text": "SOFA score 11: Respiratory (4) + Coagulation (2) + Liver (2) + Cardiovascular (3)",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.95, "status": "active",
        "entities": ["SOFA Score", "11", "Organ Dysfunction"],
        "relations": [{"from_entity": "SOFA Score", "to_entity": "Organ Failure", "type": "indicates"}],
    },
    {
        "text": "Fever 40.1°C, rigors; suspected abdominal sepsis source — perforated viscus",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.88, "status": "active",
        "entities": ["Fever", "Rigors", "Abdominal Sepsis"],
        "relations": [{"from_entity": "Fever", "to_entity": "Sepsis", "type": "indicates"}],
    },
    # t+2h – Labs
    {
        "text": "Lactate 5.8 mmol/L — severe tissue hypoperfusion (Sepsis-3 criteria met)",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+2h", "trend": "worsening",
        "evidence_support_score": 0.98, "status": "active",
        "entities": ["Lactate", "5.8 mmol/L", "Tissue Hypoperfusion"],
        "relations": [{"from_entity": "Lactate", "to_entity": "Tissue Hypoperfusion", "type": "indicates"}],
    },
    {
        "text": "Procalcitonin 38 ng/mL — severe bacterial sepsis",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+2h", "trend": "stable",
        "evidence_support_score": 0.97, "status": "active",
        "entities": ["Procalcitonin", "38 ng/mL"],
        "relations": [{"from_entity": "Procalcitonin", "to_entity": "Bacterial Sepsis", "type": "indicates"}],
    },
    {
        "text": "Thrombocytopenia: platelets 58,000/µL (DIC suspected)",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+2h", "trend": "worsening",
        "evidence_support_score": 0.85, "status": "active",
        "entities": ["Thrombocytopenia", "Platelets", "DIC"],
        "relations": [{"from_entity": "DIC", "to_entity": "Coagulopathy", "type": "causes"}],
    },
    # t+4h – Imaging
    {
        "text": "CT abdomen: free air under diaphragm — hollow viscus perforation confirmed",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.99, "status": "active",
        "entities": ["Free Air", "Diaphragm", "Viscus Perforation"],
        "relations": [{"from_entity": "Perforation", "to_entity": "Peritonitis", "type": "causes"}],
    },
    {
        "text": "Chest CT: bilateral diffuse ground-glass opacities — ARDS pattern (PaO2/FiO2 = 84)",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+4h", "trend": "worsening",
        "evidence_support_score": 0.96, "status": "active",
        "entities": ["Ground-Glass Opacities", "ARDS", "PaO2/FiO2"],
        "relations": [{"from_entity": "ARDS", "to_entity": "Respiratory Failure", "type": "causes"}],
    },
    # t+6h – Diagnoses
    {
        "text": "Septic shock secondary to hollow viscus perforation — leading diagnosis",
        "claim_type": "diagnosis", "source_type": "llm",
        "time_offset": "t+6h", "trend": "stable",
        "evidence_support_score": 0.95, "status": "active",
        "entities": ["Septic Shock", "Viscus Perforation"],
        "relations": [{"from_entity": "Perforation", "to_entity": "Septic Shock", "type": "causes"}],
    },
    {
        "text": "ARDS (severe) secondary to sepsis — confirmed by Berlin criteria",
        "claim_type": "diagnosis", "source_type": "llm",
        "time_offset": "t+6h", "trend": "stable",
        "evidence_support_score": 0.93, "status": "active",
        "entities": ["ARDS", "Berlin Criteria", "Sepsis"],
        "relations": [{"from_entity": "Sepsis", "to_entity": "ARDS", "type": "causes"}],
    },
    # t+6h – Treatment
    {
        "text": "Broad-spectrum antibiotics: meropenem 2g q8h + vancomycin — sepsis bundle initiated",
        "claim_type": "therapy", "source_type": "clinician",
        "time_offset": "t+6h", "trend": "stable",
        "evidence_support_score": 0.94, "status": "active",
        "entities": ["Meropenem", "Vancomycin", "Sepsis Bundle"],
        "relations": [{"from_entity": "Antibiotics", "to_entity": "Sepsis", "type": "reduces"}],
    },
    {
        "text": "Mechanical ventilation: lung-protective strategy — tidal volume 6 mL/kg, PEEP 14 cmH2O",
        "claim_type": "therapy", "source_type": "clinician",
        "time_offset": "t+6h", "trend": "stable",
        "evidence_support_score": 0.92, "status": "active",
        "entities": ["Mechanical Ventilation", "PEEP", "Lung-Protective"],
        "relations": [{"from_entity": "Ventilation", "to_entity": "ARDS", "type": "reduces"}],
    },
    # t+8h – Blood cultures
    {
        "text": "Blood cultures positive: E. coli (ESBL-negative) — confirms gram-negative bacteremia",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+8h", "trend": "stable",
        "evidence_support_score": 0.98, "status": "active",
        "entities": ["E. coli", "Bacteremia", "Blood Cultures"],
        "relations": [{"from_entity": "E. coli", "to_entity": "Gram-negative Bacteremia", "type": "is"}],
    },
    # ── patient-generated layer ───────────────────────────────────────────────
    {
        "text": "I'm struggling to breathe — I think my oxygen is really low",
        "claim_type": "symptom", "source_type": "patient_report",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.50, "status": "observed",
        "uncertainty_flag": True,
        "entities": ["Dyspnea"],
        "relations": [],
    },
    {
        "text": "SpO2 84% via wearable pulse oximeter — multiple readings over 30 min",
        "claim_type": "lab", "source_type": "wearable",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.63, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["SpO2", "84%"],
        "relations": [],
    },
]


# ── Scenario: NSTEMI (Non-ST-Elevation Myocardial Infarction) ─────────────────

NSTEMI_CLAIMS = [
    # t+0h – Presentation
    {
        "text": "Retrosternal chest pressure radiating to left arm and jaw, onset 3 hours ago",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "stable",
        "evidence_support_score": 0.93, "status": "active",
        "entities": ["Chest Pressure", "Left Arm", "Jaw", "Angina"],
        "relations": [{"from_entity": "Chest Pressure", "to_entity": "Myocardial Ischemia", "type": "indicates"}],
    },
    {
        "text": "Diaphoresis and nausea present — autonomic response to acute ischemia",
        "claim_type": "symptom", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "stable",
        "evidence_support_score": 0.82, "status": "active",
        "entities": ["Diaphoresis", "Nausea", "Autonomic Response"],
        "relations": [{"from_entity": "Diaphoresis", "to_entity": "Acute Ischemia", "type": "indicates"}],
    },
    {
        "text": "Risk factors: hypertension, diabetes mellitus type 2, current smoker, family history ACS",
        "claim_type": "risk_factor", "source_type": "clinician",
        "time_offset": "t+0h", "trend": "stable",
        "evidence_support_score": 0.90, "status": "active",
        "entities": ["Hypertension", "Diabetes", "Smoking", "ACS"],
        "relations": [{"from_entity": "Risk Factors", "to_entity": "Coronary Artery Disease", "type": "indicates"}],
    },
    # t+1h – ECG
    {
        "text": "ECG: ST-depression 2mm in leads V3–V6 and reciprocal changes in aVL",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+1h", "trend": "stable",
        "evidence_support_score": 0.94, "status": "active",
        "entities": ["ST-Depression", "V3-V6", "aVL"],
        "relations": [{"from_entity": "ST-Depression", "to_entity": "Myocardial Ischemia", "type": "indicates"}],
    },
    {
        "text": "No ST-elevation — STEMI excluded; NSTEMI/unstable angina on differential",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+1h", "trend": "stable",
        "evidence_support_score": 0.88, "status": "active",
        "entities": ["STEMI", "NSTEMI", "Unstable Angina"],
        "relations": [{"from_entity": "ECG", "to_entity": "STEMI", "type": "rules_out"}],
    },
    # t+2h – Labs
    {
        "text": "Troponin I 1.4 ng/mL at 2h (reference < 0.04 ng/mL) — significant elevation",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+2h", "trend": "worsening",
        "evidence_support_score": 0.97, "status": "active",
        "entities": ["Troponin I", "1.4 ng/mL", "Myocardial Necrosis"],
        "relations": [{"from_entity": "Troponin", "to_entity": "Myocardial Necrosis", "type": "indicates"}],
    },
    {
        "text": "GRACE score 162 — high risk in-hospital mortality (> 3%); early invasive strategy indicated",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+2h", "trend": "stable",
        "evidence_support_score": 0.91, "status": "active",
        "entities": ["GRACE Score", "162", "High Risk"],
        "relations": [{"from_entity": "GRACE Score", "to_entity": "Mortality Risk", "type": "indicates"}],
    },
    {
        "text": "TIMI risk score 5/7 — high risk; early revascularization strongly indicated",
        "claim_type": "finding", "source_type": "clinician",
        "time_offset": "t+2h", "trend": "stable",
        "evidence_support_score": 0.89, "status": "active",
        "entities": ["TIMI Score", "5/7"],
        "relations": [{"from_entity": "TIMI Score", "to_entity": "Revascularization", "type": "requires"}],
    },
    # t+4h – Echo
    {
        "text": "Echo: anterior-lateral wall hypokinesia, EF 48% (mildly reduced)",
        "claim_type": "imaging", "source_type": "imaging_model",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.92, "status": "active",
        "entities": ["Anterior Hypokinesia", "EF 48%", "Echocardiography"],
        "relations": [{"from_entity": "Hypokinesia", "to_entity": "Myocardial Ischemia", "type": "indicates"}],
    },
    # t+4h – Diagnosis
    {
        "text": "NSTEMI — non-ST-elevation myocardial infarction: confirmed by troponin rise + ischemic ECG changes",
        "claim_type": "diagnosis", "source_type": "llm",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.96, "status": "active",
        "entities": ["NSTEMI", "Troponin", "ECG Changes"],
        "relations": [{"from_entity": "NSTEMI", "to_entity": "Coronary Artery Disease", "type": "is"}],
    },
    # t+4h – Treatment
    {
        "text": "Dual antiplatelet therapy initiated: aspirin 300mg loading + ticagrelor 180mg loading",
        "claim_type": "therapy", "source_type": "clinician",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.95, "status": "active",
        "entities": ["Aspirin", "Ticagrelor", "Dual Antiplatelet"],
        "relations": [{"from_entity": "Dual Antiplatelet", "to_entity": "Coronary Thrombosis", "type": "reduces"}],
    },
    {
        "text": "Fondaparinux 2.5mg SC — anticoagulation per ESC NSTEMI guidelines",
        "claim_type": "therapy", "source_type": "clinician",
        "time_offset": "t+4h", "trend": "stable",
        "evidence_support_score": 0.91, "status": "active",
        "entities": ["Fondaparinux", "Anticoagulation"],
        "relations": [{"from_entity": "Fondaparinux", "to_entity": "Thrombus", "type": "reduces"}],
    },
    # t+6h – Troponin rise pattern
    {
        "text": "Troponin I at 6h: 3.2 ng/mL — rising curve confirms myocardial injury (delta troponin positive)",
        "claim_type": "lab", "source_type": "lab_system",
        "time_offset": "t+6h", "trend": "worsening",
        "evidence_support_score": 0.98, "status": "active",
        "entities": ["Troponin I", "3.2 ng/mL", "Delta Troponin"],
        "relations": [{"from_entity": "Rising Troponin", "to_entity": "Myocardial Infarction", "type": "confirms"}],
    },
    # ── patient-generated layer ───────────────────────────────────────────────
    {
        "text": "I have chest pressure for 2 hours — feels like something squeezing my chest, also left arm pain",
        "claim_type": "symptom", "source_type": "patient_report",
        "time_offset": "t+0h", "trend": "worsening",
        "evidence_support_score": 0.65, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["Chest Pain", "Left Arm Pain"],
        "relations": [],
    },
    {
        "text": "Blood pressure 158/95 mmHg via home BP monitor (taken 30 min ago)",
        "claim_type": "finding", "source_type": "home_device",
        "time_offset": "t+0h", "trend": "stable",
        "evidence_support_score": 0.70, "status": "observed",
        "uncertainty_flag": False,
        "entities": ["Blood Pressure", "158/95 mmHg"],
        "relations": [],
    },
]


SCENARIO_MAP = {
    "cap":       (DEMO_CLAIMS,       DEMO_CLAIMS_DE),
    "pe":        (PE_CLAIMS,         PE_CLAIMS),
    "ards":      (ARDS_SEPSIS_CLAIMS, ARDS_SEPSIS_CLAIMS),
    "nstemi":    (NSTEMI_CLAIMS,     NSTEMI_CLAIMS),
}


def seed_demo(session_id: str, lang: str = "en", scenario: str = "cap"):
    """Seed a demo session with a pre-built clinical scenario.

    Uses neo4j_client.store_claims() so all provenance fields are persisted
    and an AuditEvent (actor=system) is generated for every seeded Claim.
    """
    from neo4j_client import get_db
    from audit_log import log_created_batch
    from models import AuditActor

    db = get_db()

    # Guard: refuse to seed if session already has claims
    with db.driver.session() as s:
        result = s.run(
            "MATCH (c:Claim {session_id: $sid}) RETURN count(c) AS n",
            sid=session_id,
        )
        if result.single()["n"] > 0:
            return {"seeded": False, "reason": "Session already has claims"}

    en_claims, de_claims = SCENARIO_MAP.get(scenario, (DEMO_CLAIMS, DEMO_CLAIMS_DE))
    raw_claims = de_claims if lang == "de" else en_claims

    # Convert raw dicts → validated Claim model instances (with evidence_tier)
    claim_objects = [_dict_to_claim(c) for c in raw_claims]

    # Persist through the official pipeline (includes all provenance fields)
    claim_ids = db.store_claims(claim_objects, session_id)

    # Audit trail: every seeded claim gets an AuditEvent
    log_created_batch(
        claim_ids, claim_objects, session_id,
        actor=AuditActor.system,
        pipeline_stage="Demo seed",
        meta={"scenario": scenario, "lang": lang},
    )

    return {"seeded": True, "claim_count": len(claim_objects)}

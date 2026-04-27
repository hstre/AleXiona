from fastapi import APIRouter, Query

from api_errors import internal_error
from demo_seed import seed_demo

router = APIRouter(prefix="/api/demo", tags=["demo"])

# ── Scenario metadata ─────────────────────────────────────────────────────────

SCENARIO_META = {
    "cap": {
        "id":          "cap",
        "label":       "Community-acquired Pneumonia (CAP)",
        "description": (
            "Classic CAP presentation: fever, dyspnea, CRP/leukocytosis, "
            "CT consolidation → antibiotic therapy response. "
            "Includes patient-generated SpO2 and symptom report."
        ),
        "lang_support": ["en", "de"],
        "claim_types":  ["symptom", "lab", "imaging", "diagnosis", "hypothesis", "finding", "therapy"],
        "n_claims_approx": 15,
    },
    "pe": {
        "id":          "pe",
        "label":       "High-risk Pulmonary Embolism (PE)",
        "description": (
            "Massive PE with hemodynamic compromise: saddle embolus, "
            "Wells score 7, D-Dimer, S1Q3T3, rtPA thrombolysis. "
            "Includes wearable heart-rate signal."
        ),
        "lang_support": ["en"],
        "claim_types":  ["symptom", "lab", "imaging", "finding", "diagnosis", "therapy"],
        "n_claims_approx": 14,
    },
    "ards": {
        "id":          "ards",
        "label":       "ARDS / Sepsis",
        "description": (
            "Severe ARDS secondary to gram-negative sepsis: Berlin criteria, "
            "mechanical ventilation, blood culture E. coli. "
            "Includes wearable SpO2 trend."
        ),
        "lang_support": ["en"],
        "claim_types":  ["finding", "lab", "imaging", "diagnosis", "therapy"],
        "n_claims_approx": 14,
    },
    "nstemi": {
        "id":          "nstemi",
        "label":       "NSTEMI — Non-ST-elevation Myocardial Infarction",
        "description": (
            "Acute NSTEMI: troponin rise, ECG changes, dual antiplatelet, "
            "Fondaparinux. Delta troponin pattern at 6h. "
            "Includes home BP device reading."
        ),
        "lang_support": ["en"],
        "claim_types":  ["symptom", "lab", "finding", "diagnosis", "therapy"],
        "n_claims_approx": 14,
    },
}


@router.get("/scenarios")
async def list_scenarios():
    """Return available demo scenarios with metadata."""
    return {"scenarios": list(SCENARIO_META.values())}


@router.post("/seed/{session_id}")
async def seed(
    session_id: str,
    lang:     str = Query(default="en",  pattern="^(en|de)$"),
    scenario: str = Query(default="cap", pattern="^(cap|pe|ards|nstemi)$"),
):
    try:
        result = seed_demo(session_id, lang=lang, scenario=scenario)
        return result
    except Exception as e:
        raise internal_error(e)

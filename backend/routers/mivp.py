"""MIVP router — read-only model-identity provenance.

GET /api/mivp/profile          → the current Composite Instance Hash (CIH) and
                                  its component hashes (model / policy / runtime).
GET /api/mivp/claim/{claim_id} → the producing-system CIH stored on one claim,
                                  compared against the current CIH (substitution
                                  detection: a mismatch means model/policy/runtime
                                  changed since that claim was extracted).

Read-only; no side effects on the clinical path.
"""

from __future__ import annotations

from fastapi import APIRouter

from api_errors import not_found
from llm_client import mivp_profile
from neo4j_client import get_db

router = APIRouter(prefix="/api/mivp", tags=["mivp"])


@router.get("/profile")
def get_profile() -> dict:
    """Return the current MIVP profile (CIH + MH/PH/RH + declared model)."""
    return mivp_profile()


@router.get("/claim/{claim_id}")
def get_claim_provenance(claim_id: str) -> dict:
    """Return the MIVP provenance stored on a claim vs. the current profile."""
    claim = get_db().get_claim_by_id(claim_id)
    if claim is None:
        raise not_found(f"Claim {claim_id} not found")

    stored_cih = claim.get("mivp_cih")
    current = mivp_profile()
    return {
        "claim_id":             claim_id,
        "mivp_cih":             stored_cih,
        "mivp_model":           claim.get("mivp_model"),
        "mivp_profile_version": claim.get("mivp_profile_version"),
        "current_cih":          current["cih"],
        # True/False if the claim carries a CIH; None for pre-MIVP / manual claims.
        "matches_current":      (stored_cih == current["cih"]) if stored_cih else None,
    }

from fastapi import APIRouter, HTTPException
from demo_seed import seed_demo

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/seed/{session_id}")
async def seed(session_id: str):
    try:
        result = seed_demo(session_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

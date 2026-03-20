from fastapi import APIRouter
from demo_seed import seed_demo
from api_errors import internal_error

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/seed/{session_id}")
async def seed(session_id: str):
    try:
        result = seed_demo(session_id)
        return result
    except Exception as e:
        raise internal_error(e)

import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException
from models import ChatRequest, ChatResponse
from llm_client import extract_claims, answer_with_context, analyze_reasoning
from neo4j_client import Neo4jClient
from conflict_engine import detect_conflicts

router = APIRouter(prefix="/api/chat", tags=["chat"])
_executor = ThreadPoolExecutor()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    db = Neo4jClient()
    loop = asyncio.get_event_loop()
    try:
        # 1. Extract claims from input
        extraction = extract_claims(request.message)

        # 2. Store in Neo4j
        if extraction.claims:
            db.store_claims(extraction.claims, request.session_id)

        # 3. Fetch all claims once for context + analysis + conflicts
        all_claims = db.get_all_claims_for_session(request.session_id)
        graph_context = db.get_context_for_query(request.session_id)

        # 4. Parallelize: LLM reply + reasoning analysis (both are sync calls)
        reply, reasoning = await asyncio.gather(
            loop.run_in_executor(
                _executor,
                answer_with_context,
                request.message, request.history, graph_context,
            ),
            loop.run_in_executor(_executor, analyze_reasoning, all_claims),
        )

        # 5. Rule-based conflict detection (fast, no LLM)
        conflicts = detect_conflicts(all_claims)

        return ChatResponse(
            reply=reply,
            claims=extraction.claims,
            session_id=request.session_id,
            reasoning=reasoning,
            conflicts=conflicts,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

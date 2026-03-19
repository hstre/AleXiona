import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from models import ChatRequest, ChatResponse
from llm_client import (
    extract_claims, answer_with_context, analyze_reasoning,
    stream_answer_with_context,
)
from neo4j_client import get_db
from conflict_engine import detect_conflicts

router = APIRouter(prefix="/api/chat", tags=["chat"])
_executor = ThreadPoolExecutor()


# ── Sync endpoint (kept for compatibility) ────────────────────────────────────

@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    db   = get_db()
    loop = asyncio.get_event_loop()
    try:
        extraction = extract_claims(request.message)

        new_ids: list[str] = []
        if extraction.claims:
            new_ids = db.store_claims(extraction.claims, request.session_id)
            db.link_derived_from(new_ids, request.session_id)

        all_claims    = db.get_all_claims_for_session(request.session_id)
        graph_context = db.get_context_for_query(request.session_id)

        reply, reasoning = await asyncio.gather(
            loop.run_in_executor(
                _executor, answer_with_context,
                request.message, request.history, graph_context,
            ),
            loop.run_in_executor(_executor, analyze_reasoning, all_claims),
        )

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


# ── Streaming endpoint ────────────────────────────────────────────────────────

@router.post("/stream")
async def chat_stream(request: ChatRequest):
    db   = get_db()
    loop = asyncio.get_event_loop()

    async def generate():
        # 1. Extract + store claims (sync work, run in thread)
        try:
            extraction = await loop.run_in_executor(
                _executor, extract_claims, request.message
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        new_ids: list[str] = []
        if extraction.claims:
            new_ids = await loop.run_in_executor(
                _executor, db.store_claims, extraction.claims, request.session_id
            )
            await loop.run_in_executor(
                _executor, db.link_derived_from, new_ids, request.session_id
            )

        # 2. Emit extracted claims immediately (so UI can refresh graph early)
        claims_payload = [c.model_dump(mode="json") for c in extraction.claims]
        yield f"data: {json.dumps({'type': 'claims', 'claims': claims_payload})}\n\n"

        # 3. Fetch session context
        all_claims    = await loop.run_in_executor(
            _executor, db.get_all_claims_for_session, request.session_id
        )
        graph_context = await loop.run_in_executor(
            _executor, db.get_context_for_query, request.session_id
        )

        # 4. Stream LLM reply tokens
        full_reply = ""
        try:
            async for token in stream_answer_with_context(
                request.message, request.history, graph_context
            ):
                full_reply += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # 5. Reasoning + conflicts (sync, run in thread)
        reasoning, conflicts = await asyncio.gather(
            loop.run_in_executor(_executor, analyze_reasoning, all_claims),
            loop.run_in_executor(_executor, detect_conflicts, all_claims),
        )

        # 6. Final done event with full payload
        done_payload = {
            "type":       "done",
            "reply":      full_reply,
            "claims":     claims_payload,
            "reasoning":  reasoning.model_dump(mode="json") if reasoning else None,
            "conflicts":  [c.model_dump(mode="json") for c in conflicts],
            "session_id": request.session_id,
        }
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

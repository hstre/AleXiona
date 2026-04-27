import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api_errors import internal_error
from audit_log import log_created_batch
from conflict_engine import detect_conflicts
from llm_client import (
    analyze_reasoning,
    answer_with_context,
    extract_claims,
    stream_answer_with_context,
)
from models import AuditActor, ChatRequest, ChatResponse
from neo4j_client import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])
_executor = ThreadPoolExecutor()


# ── Sync endpoint (kept for compatibility) ────────────────────────────────────

@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    db   = get_db()
    loop = asyncio.get_event_loop()
    try:
        extraction = extract_claims(request.message)

        if extraction.claims:
            claim_ids = db.store_claims(extraction.claims, request.session_id)
            log_created_batch(
                claim_ids, extraction.claims, request.session_id,
                actor=AuditActor.chat,
                pipeline_stage="Stage 1–3: LLM extraction via /api/chat",
            )

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
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


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

        if extraction.claims:
            claim_ids = await loop.run_in_executor(
                _executor, db.store_claims, extraction.claims, request.session_id
            )
            log_created_batch(
                claim_ids, extraction.claims, request.session_id,
                actor=AuditActor.chat,
                pipeline_stage="Stage 1–3: LLM extraction via /api/chat/stream",
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

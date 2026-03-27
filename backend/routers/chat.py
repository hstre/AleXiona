import asyncio
import json
import structlog
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException, Request
from api_errors import internal_error, validation_error
from auth import UserSession, require_clinician

log = structlog.get_logger(__name__)
from fastapi.responses import StreamingResponse
from models import ChatRequest, ChatResponse
from llm_client import (
    extract_claims, answer_with_context, analyze_reasoning,
    stream_answer_with_context,
)
from neo4j_client import get_db
from conflict_engine import detect_conflicts
from audit_log import log_created_batch
from models import AuditActor
from rate_limit import limiter

router = APIRouter(prefix="/api/chat", tags=["chat"])
_executor = ThreadPoolExecutor(max_workers=10)


# ── Sync endpoint (kept for compatibility) ────────────────────────────────────

@router.post("", response_model=ChatResponse)
@limiter.limit("10/minute")
async def chat(body: ChatRequest, request: Request, _user: UserSession = Depends(require_clinician)):
    token_sid = getattr(getattr(request.state, "user", None), "session_id", "")
    if token_sid and body.session_id != token_sid:
        raise validation_error("Session ID in body does not match session token")
    db   = get_db()
    loop = asyncio.get_running_loop()
    try:
        extraction = extract_claims(body.message)

        if extraction.claims:
            claim_ids = db.store_claims(extraction.claims, body.session_id)
            log_created_batch(
                claim_ids, extraction.claims, body.session_id,
                actor=AuditActor.chat,
                pipeline_stage="Stage 1–3: LLM extraction via /api/chat",
            )

        all_claims    = db.get_all_claims_for_session(body.session_id)
        graph_context = db.get_context_for_query(body.session_id)

        reply_result, reasoning_result = await asyncio.gather(
            loop.run_in_executor(
                _executor, answer_with_context,
                body.message, body.history, graph_context,
            ),
            loop.run_in_executor(_executor, analyze_reasoning, all_claims),
            return_exceptions=True,
        )

        if isinstance(reply_result, Exception):
            raise reply_result

        reply = reply_result
        if isinstance(reasoning_result, Exception):
            log.warning("Reasoning analysis failed (non-fatal): %s", reasoning_result)
            reasoning_result = None
        reasoning = reasoning_result

        conflicts = detect_conflicts(all_claims)

        return ChatResponse(
            reply=reply,
            claims=extraction.claims,
            session_id=body.session_id,
            reasoning=reasoning,
            conflicts=conflicts,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


# ── Streaming endpoint ────────────────────────────────────────────────────────

@router.post("/stream")
@limiter.limit("10/minute")
async def chat_stream(body: ChatRequest, request: Request, _user: UserSession = Depends(require_clinician)):
    token_sid = getattr(getattr(request.state, "user", None), "session_id", "")
    if token_sid and body.session_id != token_sid:
        raise validation_error("Session ID in body does not match session token")
    db   = get_db()
    loop = asyncio.get_running_loop()

    async def generate():
        # 1. Extract + store claims (sync work, run in thread)
        try:
            extraction = await loop.run_in_executor(
                _executor, extract_claims, body.message
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        if extraction.claims:
            try:
                claim_ids = await loop.run_in_executor(
                    _executor, db.store_claims, extraction.claims, body.session_id
                )
                log_created_batch(
                    claim_ids, extraction.claims, body.session_id,
                    actor=AuditActor.chat,
                    pipeline_stage="Stage 1–3: LLM extraction via /api/chat/stream",
                )
            except Exception as e:
                log.error("store_claims failed in stream: %s", e)
                yield f"data: {json.dumps({'type': 'error', 'message': 'Failed to store claims'})}\n\n"
                return

        # 2. Emit extracted claims immediately (so UI can refresh graph early)
        claims_payload = [c.model_dump(mode="json") for c in extraction.claims]
        yield f"data: {json.dumps({'type': 'claims', 'claims': claims_payload})}\n\n"

        # 3. Fetch session context
        all_claims    = await loop.run_in_executor(
            _executor, db.get_all_claims_for_session, body.session_id
        )
        graph_context = await loop.run_in_executor(
            _executor, db.get_context_for_query, body.session_id
        )

        # 4. Stream LLM reply tokens
        full_reply = ""
        try:
            async for tok in stream_answer_with_context(
                body.message, body.history, graph_context
            ):
                full_reply += tok
                yield f"data: {json.dumps({'type': 'token', 'content': tok})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # 5. Reasoning + conflicts (sync, run in thread)
        reasoning_result, conflicts_result = await asyncio.gather(
            loop.run_in_executor(_executor, analyze_reasoning, all_claims),
            loop.run_in_executor(_executor, detect_conflicts, all_claims),
            return_exceptions=True,
        )
        reasoning = None if isinstance(reasoning_result, Exception) else reasoning_result
        conflicts = [] if isinstance(conflicts_result, Exception) else conflicts_result
        if isinstance(reasoning_result, Exception):
            log.warning("Reasoning failed in stream (non-fatal): %s", reasoning_result)
        if isinstance(conflicts_result, Exception):
            log.warning("Conflict detection failed in stream (non-fatal): %s", conflicts_result)

        # 6. Final done event with full payload
        done_payload = {
            "type":       "done",
            "reply":      full_reply,
            "claims":     claims_payload,
            "reasoning":  reasoning.model_dump(mode="json") if reasoning else None,
            "conflicts":  [c.model_dump(mode="json") for c in conflicts],
            "session_id": body.session_id,
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

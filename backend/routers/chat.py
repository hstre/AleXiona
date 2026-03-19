import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException
from models import ChatRequest, ChatResponse
from llm_client import extract_claims, answer_with_context, analyze_graph
from neo4j_client import Neo4jClient

router = APIRouter(prefix="/api/chat", tags=["chat"])
_executor = ThreadPoolExecutor()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    db = Neo4jClient()
    loop = asyncio.get_event_loop()
    try:
        # 1. Extract claims
        extraction = extract_claims(request.message)

        # 2. Store in Neo4j
        if extraction.claims:
            db.store_claims(extraction.claims, request.session_id)

        # 3. Fetch claims once — used for both LLM context and analysis
        all_claims = db.get_all_claims_for_session(request.session_id)
        graph_context = "\n".join(f"- {c['text']}" for c in all_claims)

        # 4. Run answer + analysis in parallel (both are sync OpenAI calls)
        reply, analysis = await asyncio.gather(
            loop.run_in_executor(
                _executor,
                answer_with_context,
                request.message, request.history, graph_context,
            ),
            loop.run_in_executor(_executor, analyze_graph, all_claims),
        )

        return ChatResponse(
            reply=reply,
            claims=extraction.claims,
            session_id=request.session_id,
            analysis=analysis,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

from fastapi import APIRouter, HTTPException
from models import ChatRequest, ChatResponse
from llm_client import extract_claims, answer_with_context, analyze_graph
from neo4j_client import Neo4jClient

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    db = Neo4jClient()
    try:
        # 1. Extract claims
        extraction = extract_claims(request.message)

        # 2. Store in Neo4j
        if extraction.claims:
            db.store_claims(extraction.claims, request.session_id)

        # 3. Get context for grounded reply
        graph_context = db.get_context_for_query(request.session_id, request.message)

        # 4. Grounded LLM reply
        reply = answer_with_context(
            user_message=request.message,
            history=request.history,
            graph_context=graph_context,
        )

        # 5. AI analysis of full graph
        all_claims = db.get_all_claims_for_session(request.session_id)
        analysis = analyze_graph(all_claims) if all_claims else None

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

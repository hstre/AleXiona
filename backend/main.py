import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routers import chat, graph, sessions, demo, intake, audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Graceful shutdown: close the shared Neo4j driver
    try:
        from neo4j_client import _instance
        if _instance is not None:
            _instance.close()
    except Exception:
        pass


app = FastAPI(title="AleXiona API", version="0.1.0", lifespan=lifespan)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(chat.router)
app.include_router(graph.router)
app.include_router(sessions.router)
app.include_router(demo.router)
app.include_router(intake.router)
app.include_router(audit.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "AleXiona Backend"}

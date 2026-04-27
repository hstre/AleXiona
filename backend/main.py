from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from routers import audit, chat, demo, graph, intake, sessions


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routers import chat, graph, sessions, demo

app = FastAPI(title="AleXiona API", version="0.1.0")

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


@app.get("/health")
def health():
    return {"status": "ok", "service": "AleXiona Backend"}

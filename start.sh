#!/bin/bash
# AleXiona V0 – local dev startup (without Docker)
set -e

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env – please add your OPENAI_API_KEY"
  exit 1
fi

source .env

if [ -z "$OPENAI_API_KEY" ]; then
  echo "Error: OPENAI_API_KEY is not set in .env"
  exit 1
fi

# Start Neo4j via Docker if not already running
if ! docker ps --format '{{.Names}}' | grep -q 'alexiona-neo4j'; then
  echo "Starting Neo4j..."
  docker run -d \
    --name alexiona-neo4j \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/alexiona123 \
    neo4j:5.15
  echo "Waiting for Neo4j to be ready..."
  sleep 10
fi

# Start backend
echo "Starting backend on :8000..."
cd backend
pip install -r requirements.txt -q
NEO4J_URI=bolt://localhost:7687 \
NEO4J_USER=neo4j \
NEO4J_PASSWORD=alexiona123 \
OPENAI_API_KEY=$OPENAI_API_KEY \
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# Start frontend
echo "Starting frontend on :3000..."
cd frontend
npm install -q
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "AleXiona is running:"
echo "  Frontend:  http://localhost:3000"
echo "  Backend:   http://localhost:8000"
echo "  Neo4j:     http://localhost:7474"
echo ""
echo "Press Ctrl+C to stop"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" SIGINT SIGTERM
wait

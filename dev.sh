#!/usr/bin/env bash
# Lance le backend FastAPI (:8000) et le frontend Next.js (:3000) côte à côte.
# Ctrl-C arrête les deux.
set -euo pipefail
cd "$(dirname "$0")"

# Backend (venv attendu dans .venv)
if [ -x .venv/bin/uvicorn ]; then
  UVICORN=.venv/bin/uvicorn
else
  UVICORN=uvicorn
fi

echo "→ Backend FastAPI sur http://localhost:8000"
$UVICORN main:app --reload --port 8000 &
BACK=$!

echo "→ Frontend Next.js sur http://localhost:3000"
( cd frontend && npm run dev ) &
FRONT=$!

trap 'echo; echo "Arrêt…"; kill $BACK $FRONT 2>/dev/null || true' INT TERM
wait

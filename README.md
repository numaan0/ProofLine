# ProofLine

AI QA Inspector - Compare contractor work orders against photos to verify completion.

## Quick Start

1. Copy .env.example to ackend/.env and add your API keys
2. Install dependencies: 
pm run install:all
3. Run dev: 
pm run dev
   - Backend: http://127.0.0.1:8000
   - Frontend: http://localhost:5173

## Core Principle
Be conservative - if not 100% sure, mark as 'Can't tell - needs more photos'. Never guess done on weak evidence.

## Stack
- Frontend: React + TypeScript + Vite + Tailwind CSS
- Backend: FastAPI + Python
- AI: Meta Model API (Muse) + SAM 3.1

# ProofLine Plan

## Goal
Build a working demo of PROOFLINE - an AI QA inspector that compares a contractor's work order (checklist) against uploaded photos and tells the user what's done/missing/needs more proof.

## Core Principle
Be conservative. If not 100% sure evidence exists, mark as ""Can't tell - needs more photos"". Don't guess and say done.

## Folder Structure (All self-contained in ProofLine/)
`
ProofLine/
+-- AGENTS.md           # Rules to follow (must read first)
+-- PLAN.md             # This plan
+-- package.json        # Root scripts to run frontend/backend together
+-- .env.example        # Example env vars (API keys)
+-- README.md           # Quick start
+-- backend/            # FastAPI backend
+-- frontend/           # React + Vite + Tailwind
+-- scripts/            # Setup/dev scripts (all local)
+-- data/               # Test assets
`

## Tech Stack
- Frontend: React + TypeScript + Vite + Tailwind CSS
- Backend: Python + FastAPI + Uvicorn
- AI: Meta Model API (Muse models) + SAM 3.1. Fallback to open weights if needed.
- Storage: Local filesystem only

## Implementation Plan (10 Days)
### Phase 0: Setup (Day 1)
- [ ] Create full folder structure
- [ ] Write AGENTS.md with strict rules
- [ ] Create README.md
- [ ] Create root package.json with scripts
- [ ] Create backend/requirements.txt and frontend/package.json
- [ ] Create .env.example
- [ ] Create test data

### Phase 1: Backend Core (Days 2-3)
- [ ] FastAPI app with health check
- [ ] File upload endpoint
- [ ] Work order parsing
- [ ] Config for API keys
- [ ] Meta API + SAM services
- [ ] Local image storage

### Phase 2: Vision + Matching (Days 3-4)
- [ ] SAM segmentation
- [ ] Object labeling via Muse vision
- [ ] Matching logic
- [ ] Status: DONE / MISSING / CANT_TELL
- [ ] Conservative logic
- [ ] Structured results JSON

### Phase 3: Frontend (Days 5-6)
- [ ] Split screen UI
- [ ] Upload flow
- [ ] Results display with badges
- [ ] Overlays
- [ ] Report summary

### Phase 4: Integration & Testing (Days 7-8)
- [ ] E2E flow
- [ ] Ground truth tests
- [ ] Fix false approvals

### Phase 5: Polish & Submission (Days 9-10)
- [ ] Polish, error handling, demo video, submission prep

## Success Criteria
- [ ] Working app in ProofLine folder
- [ ] Upload work order + photos, get results
- [ ] Correct done/missing/cant tell
- [ ] No false approvals
- [ ] Clean demo

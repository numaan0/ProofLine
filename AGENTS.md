# AGENTS.md - ProofLine Rules

## Mission
You MUST follow these rules strictly. Everything for this project MUST stay inside the ProofLine/ folder.

## Core Rules
1. **All files go in ProofLine/** - Never create files outside this folder. All installs, deps, configs go here.
2. **Self-contained** - backend/, frontend/, data/, scripts/ must all be inside ProofLine/
3. **Local first** - Use local filesystem. No external databases.
4. **Conservative AI** - If not certain, mark CANT_TELL and ask for more photos. NEVER guess DONE on weak evidence.
5. **Sophisticated, not basic** - This must look and feel polished. Don't build a barebones form.
6. **Use Meta models** - Prioritize Muse + SAM 3.1 via Meta Model API.
7. **Use frontend-design** - Leverage the globally installed frontend-design skill for the UI.

## Design Requirements (CRITICAL)
- **Modern dashboard** - Clean, professional split-screen layout
- **Image focused** - Show uploaded photos prominently with overlays
- **Visual hierarchy** - Status badges with icons, clear reasoning
- **Micro-interactions** - Subtle animations where appropriate
- **Empty states** - Guide user through the flow
- **Status clarity** - DONE (green), MISSING (red), CAN'T TELL (amber)
- **Conservative messaging** - Explicitly show 'needs more photos' for uncertain items
- **Production-like** - Avoid generic bootstrap-looking UI. Make it look intentional

## Structure Enforcement
- Read this file before making changes
- Keep code organized by the structure in PLAN.md
- Don't create random files in root
- Put API keys in backend/.env (gitignored)
- Put test images in data/samples/

## Development Rules
- Frontend: React + TypeScript + Vite + Tailwind CSS + frontend-design
- Backend: FastAPI + Python
- Keep dependencies minimal but purposeful
- Prioritize UX for demo clarity

## Testing Rules
- Always test with ground truth
- Track false approvals - must be 0 on test cases
- Test the tricky case (missing item) explicitly
- Demo must clearly show the conservative behavior

## Submission
- Everything needed to run must be in ProofLine/
- Include README.md with clear setup
- Clean, polished demo video

# ProofLine

**Visual work verification that knows what it can't see.**

ProofLine checks a maintenance work order against completion photos. For each requirement it says whether the photos support completion, show that the work is *not* done, or don't show enough to tell. When the photos fall short, it says exactly which photo to take next. Every finding links back to the observations and photo regions it rests on.

It is built for residential maintenance and small renovation jobs, the kind where a coordinator receives "done!" plus three phone photos and has to decide whether to close the ticket.

> ProofLine reports what the submitted photos show. It does not certify safety, code compliance, or hidden work such as wiring or plumbing behind walls.

---

## What happens when you run an inspection

```
work order + photos (+ optional before photos)
  │
  ├─ Guardrails ─────────── text and file checks (deterministic), then a Muse Spark scope check
  │                         → bad input is rejected with a field- or file-specific error, before any analysis
  ├─ PLANNING ───────────── Muse Spark turns the work order into checkable requirements
  ├─ ANALYZING ──────────── Muse Spark looks at every after photo once and records concrete observations
  ├─ COMPARING ──────────── only with before photos: Muse Spark sees before and after together, checks they
  │                         show the same place, and records what changed
  ├─ VERIFYING ──────────── Muse Spark assigns DONE / MISSING / CANT_TELL per requirement,
  │                         citing observation IDs; a deterministic check rejects uncited verdicts
  ├─ INVESTIGATING ──────── bounded tool loop for unresolved requirements (see below)
  ├─ GROUNDING ──────────── SAM 3.1 locates the objects cited as evidence, for overlays
  └─ NEEDS_USER_ACTION / COMPLETED / FAILED
        + persisted report, follow-up photo requests, in-app notification

follow-up photo for one open requirement
  └─ REVERIFYING ────────── analyze only the new photo against that requirement → compare with before
                            photos, if any → verify → investigate → ground; other requirements are untouched
```

Each stage is persisted, and the UI shows the stage the backend is actually in. There are no fake progress timers.

### The investigation loop

When a requirement comes back `CANT_TELL`, Muse Spark gets a small set of allowlisted tools and decides whether the existing photos can settle it:

| Tool | What it does |
|---|---|
| `look_closer(photo, question)` | One focused Muse Spark question about one photo |
| `count_objects(photo, object_phrase)` | SAM 3.1 finds and counts every instance (e.g. "outlet cover plate") |
| `finalize(status, reasoning, observation_ids, follow_up_request)` | Records the decision |

Every argument is validated with Pydantic. Unknown tools, unknown photos, or malformed arguments go back to the model as recoverable errors. Each tool result is stored as a real observation, and `finalize` passes through the same deterministic check as the verifier, so a `DONE` still needs a cited observation. The loop is bounded to 3 requirements, 4 turns per requirement, and 8 tool calls per inspection. If the model is unavailable, the first-pass verdict stands and the inspection does not fail. Each step is recorded and shown under **How ProofLine checked this** in the report.

### Follow-up photos

Every `CANT_TELL` requirement has an **Add follow-up photo** button on its follow-up card. The new photo joins the same inspection. Only that requirement is re-checked: its existing observations plus the new photo go through verification, then the investigation loop if it is still unresolved. If the evidence now supports a decision, the request is closed. Otherwise it stays open with a new, more specific request. If the model is unavailable during a re-check, the earlier result stands and the card shows the error, so a re-check failure never becomes a finding or fails the inspection. While a re-check is running, further uploads return `409`.

### Before and after photos

Work like "patch the hole" or "repaint the wall" is hard to verify from an after photo alone: a smooth green wall doesn't prove it's the wall that had the hole. Before photos are optional. When they are added, one Muse Spark call sees them next to the after photos and reports, per requirement, whether the after photo shows the **same place** (matching fixed features such as outlets, trim, windows and doors) and **what changed**. Each comparison is stored as an observation on the after photo, so it can be cited and is shown in the report. The report places the before photo next to the after photo.

Two deterministic rules keep this conservative:

- **A before photo is never evidence on its own.** A `DONE` or `MISSING` that cites only before-photo observations is downgraded to `CANT_TELL`.
- **A different place blocks a verdict.** If every comparison says an after photo shows a different place than the before photo, a `DONE` or `MISSING` resting only on that photo becomes `CANT_TELL`, with a request to retake it from the same spot. A follow-up photo is compared with the before photos too, so a matching retake can resolve it.

If the comparison call fails, the inspection fails with a retryable error instead of silently ignoring the before photos.

### Statuses mean specific things

| Status | Meaning |
|---|---|
| `DONE` | Observations positively show the requirement is met |
| `MISSING` | Observations positively show it is *not* met. Not seeing something is not treated as proof it's missing |
| `CANT_TELL` | Insufficient, obscured or conflicting evidence. Always comes with a specific follow-up photo request |
| `FAILED` (inspection) | A technical problem such as a timeout, rate limit or malformed model output. **Never recorded as a finding**. One click retries it with the same photos |

---

## Evaluation

31 labelled cases (39 requirements, 5 of them with before photos) ran through the full pipeline against the live API. Results are in [data/eval/results.md](data/eval/results.md).

| Metric | Result |
|---|---|
| **False completions** (a requirement marked "Supported" when the photo doesn't support it) | **0 of 22** |
| Requirements flagged "Not met" without support | 0 of 39 |
| Acceptable verdict | 39 of 39 |
| Exact match with the primary label | 31 of 39 (the other 8 said "Needs evidence" where "Supported" was also defensible) |
| Technical failures | 0 of 31 cases |

The set includes deliberately tricky cases: a sticky note reading "ALL DONE" beside an uncovered outlet, a request for four outlet covers when only two outlets are in frame, a hidden leak under a sink, an irrelevant photo, a dark and blurry photo, a wall painted the wrong colour, an "after" photo of a freshly painted wall in a different room than the before photo, and a before photo of a damaged wall paired with an after photo that doesn't show the wall.

**Read these numbers with care:** the photos are AI-generated (`muse-image-1.0`) to show specific situations, the before photos were made by editing the after photos so the pairs really match, labels were assigned by one person, and 31 cases is a sanity check, not a benchmark. Across four full runs, there were 0 false completions every time. The first two runs each lost one case to a technical failure: invalid JSON in one, a provider HTTP 503 in the other. Both were reported as FAILED, never as a finding. The client now sends one corrective retry for invalid JSON and retries transient provider errors (429/5xx) once, and the published run had no failures. Reproduce with:

```bash
cd backend
.venv\Scripts\python scripts/run_eval.py      # about 6 minutes, about 250 model calls; uses a throwaway database
```

---

## Meta models used

| Model | Where | Why |
|---|---|---|
| `muse-spark-1.3` | Scope check, planning, per-photo analysis, verification, investigation loop (tool calling) | Multimodal reasoning over work orders and photos; function calling for the bounded agent loop |
| `sam-3.1` | `count_objects` tool and evidence grounding | Pixel boxes for the objects a finding cites, drawn as overlays in the report |
| `muse-image-1.0` | Only to generate the sample and evaluation photos (`data/samples/`, `data/eval/photos/`) | Not used at runtime |

All calls go through the Meta Model API (`https://api.meta.ai/v1`). Images are sent inline as base64 data URLs and are never published at a public URL.

---

## Run it locally

**Requirements:** Python 3.11, Node 18+, and a Meta Model API key with access to `muse-spark-1.3` and `sam-3.1`.

```bash
# 1. API key (backend only; never sent to the browser)
cp .env.example backend/.env        # then set MODEL_API_KEY (META_API_KEY also accepted)

# 2. Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # macOS/Linux: .venv/bin/pip
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 3. Frontend (second terminal)
cd frontend
npm install
npm run dev                          # http://localhost:5173 (proxies /api to :8000)
```

On Windows, `npm install && npm run install:all` and then `npm run dev` from the repo root start both servers.

**Check API access before a demo:**

```bash
cd backend
.venv\Scripts\python scripts/smoke_meta.py
```

This runs five live checks: model list, text, base64 image, tool calling, and SAM 3.1. It prints PASS/FAIL for each and never prints the key.

**Try it:** open http://localhost:5173 and click **Try it with a sample job**. This fills in the work order and photo below, and once the report is ready, the smoke-detector requirement offers **Use the sample follow-up photo**. **Try a before/after job** instead loads a damaged wall as the before photo and the repaired, repainted wall as the after photo, so the report shows the same-place comparison side by side. **All sample jobs** lists all 31 labelled evaluation cases with their expected result; click one to load it. To do it by hand, enter

```
- Install cover plates on both wall outlets
- Install a smoke detector on the hallway ceiling
```

and upload `data/samples/outlets_one_uncovered.png`. The expected result: outlets **Not met**, with SAM boxes on the installed plate and on the open box; smoke detector **Needs evidence**, because the photo shows no ceiling. Then open the smoke-detector requirement and add `data/samples/hallway_smoke_detector.png` as a follow-up photo. Only that requirement is re-checked: it becomes **Supported**, with a SAM box on the detector, and the inspection moves from "Needs your input" to complete.

`data/samples/hallway_ceiling_painted.png` shows the cautious side. Given as a follow-up for "Repaint the hallway ceiling", ProofLine took a closer look and still asked for more coverage (one upward angle, with an overexposed far end) rather than declaring the ceiling repainted from a single after-photo.

---

## Tests

```bash
cd backend
.venv\Scripts\python -m pytest -q
```

71 tests. **All of them mock the Meta API**, so none need network access or a key. They cover:

- **False completion:** `DONE` with no cited evidence, or citing invented observation IDs, is downgraded to `CANT_TELL`, in both the verifier and the investigation loop.
- **Failure separation:** provider timeouts and rate limits produce `FAILED` with an error code and leave tasks unassessed, never `CANT_TELL`. A model outage inside the optional investigation loop does not fail the inspection.
- **Guardrails:** empty work order, no files, corrupt files, undersized images, and every bad file reported at once. A preflight outage returns 503, not a rejection of the user's input.
- **Before and after:** a verdict citing only before photos is downgraded; a photo of a different place can't confirm or reject work; before photos are compared, not analyzed alone; a comparison outage fails the inspection; a follow-up retake is compared with the before photo.
- **Follow-up photos:** only the open requirement is re-checked; an uncited `DONE` is still downgraded; a model outage keeps the earlier result; uploads are rejected when nothing is waiting or a re-check is running.
- **Provider resilience:** a reasoning cut-off, invalid JSON, and a transient 429/5xx each get exactly one retry; auth errors are not retried.
- **Retry:** only `FAILED` inspections can be retried, and a retry starts from a clean slate.
- **Tool loop:** argument validation, unknown tools and photos, budget enforcement, SAM failure inside a tool.
- **SAM parsing:** real response format, out-of-bounds boxes, whole-frame boxes.
- **Data safety:** another device gets 404s for inspections, reports, photos and notifications it did not create; images can only be read through the inspection that owns them; old databases get missing columns added on startup.

Live behavior was checked separately with `scripts/smoke_meta.py` and end-to-end runs against the real API.

---

## API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/inspections` | Validate and create (`files`, optional `before_files`); runs in the background. Returns `202` with `inspection_id` |
| `GET` | `/api/inspections` | History with status, outcome and counts |
| `GET` | `/api/inspections/{id}` | Live status and stage (polled by the UI) |
| `GET` | `/api/inspections/{id}/report` | Tasks, observations, evidence links, SAM regions, follow-ups, investigation steps |
| `POST` | `/api/inspections/{id}/tasks/{task_id}/follow-up-photos` | Attach follow-up photos (1–5) to an open request; re-checks that requirement in the background. `202`, or `409` if nothing is waiting |
| `POST` | `/api/inspections/{id}/retry` | Re-run a `FAILED` inspection with the same work order and photos. `409` otherwise |
| `GET` | `/api/samples`, `/api/samples/{name}` | Bundled demo work orders and photos (fixed allowlist) |
| `GET` | `/api/samples/cases`, `/api/samples/cases/{name}` | The labelled evaluation cases as sample jobs; photos limited to those the cases use |
| `GET` | `/api/inspections/{id}/images/{image_id}` | Image bytes, only for an image belonging to that inspection |
| `GET` | `/api/notifications` | Notifications plus unread count |
| `POST` | `/api/notifications/{id}/read`, `/api/notifications/read-all` | Mark read |
| `POST` | `/api/inspect` | Legacy synchronous endpoint, kept for compatibility |

Errors share one shape: `{"error": {code, stage, message, suggestion, retryable, field?, file_id?}, "errors": [...]}`.

---

## Project layout

```
backend/app/
  api/                 inspections, notifications, legacy inspect
  guardrails/          deterministic validators, semantic preflight, error contract
  services/
    meta_client.py     Meta Model API client (typed errors, base64 images, SAM streaming)
    segmentation.py    SAM 3.1 output → internal regions
    agent/             orchestrator, planner, visual_analyst, comparer, verifier, investigator, tools
  models/              SQLAlchemy models (SQLite at data/db/proofline.db)
backend/scripts/smoke_meta.py   live API checks
backend/scripts/run_eval.py     labelled evaluation against the live API
data/eval/                      evaluation cases, photos, prompts, results
backend/tests/                  mocked test suite
frontend/src/
  pages/               NewInspection, InspectionView (progress + report), InspectionsList
  components/report/   EvidenceViewer (photo + SAM overlays), TaskPanel, StageProgress
```

---

## Known limitations

- **Per-device, no sign-in.** Each browser gets a random device id in an HttpOnly cookie on its first visit, and sees only its own inspections and notifications; other devices get 404s. This keeps demo users apart but is not authentication: clearing cookies starts a fresh, empty history, and anyone holding the cookie value is that device.
- **Background work runs in-process.** An inspection or follow-up re-check that is running when the server restarts stays at its last stage.
- **Same-place checks rely on visible fixed features.** A blank wall with no outlets, trim or windows in frame gives the comparison little to match, so it says "unclear" rather than "same place".
- **SAM masks are not decoded**, only boxes. A box means "this object was detected here", not "this work is complete".
- **Evaluation photos are generated, not real site photos.** See the caveats under Evaluation.
- Uploaded photos are stored locally under `backend/app/static/uploads/` with no automatic retention cleanup.
- With uvicorn's `--reload` on Windows, the server sometimes fails to finish reloading. Restart it manually if new code doesn't seem to take effect.

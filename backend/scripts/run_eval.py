"""Run the labelled evaluation set (data/eval/cases.json) through the real pipeline and score it.

Uses the live Meta API and a throwaway SQLite database, so the app's own history is untouched.
The semantic work-order preflight is skipped: this measures planning -> analysis -> verification
-> investigation -> grounding.

    .venv\\Scripts\\python scripts/run_eval.py            # all cases
    .venv\\Scripts\\python scripts/run_eval.py 05 12      # cases whose id starts with 05 or 12

Writes data/eval/results.json and data/eval/results.md.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

import app.models.inspection_models  # noqa: E402,F401  (register tables)
import app.services.agent.orchestrator as orch_mod  # noqa: E402
from app.models.inspection_models import Inspection, InspectionImage, Task  # noqa: E402
from app.services.persistence import Base  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVAL_DIR = os.path.join(REPO, "data", "eval")
CONCURRENCY = 3
STATUSES = ("DONE", "MISSING", "CANT_TELL")


def photo_path(ref: str) -> str:
    if ref.startswith("sample:"):
        return os.path.join(REPO, "data", "samples", ref.split(":", 1)[1] + ".png")
    return os.path.join(EVAL_DIR, "photos", ref + ".png")


def match_tasks(expectations: List[Dict[str, Any]], tasks: List[Dict[str, str]]):
    """Greedy keyword match of labelled requirements to planner tasks. Returns (pairs, unlabelled tasks)."""
    unused = list(tasks)
    pairs = []
    for exp in expectations:
        hit = next((t for t in unused if any(k in t["description"].lower() for k in exp["match"])), None)
        if hit:
            unused.remove(hit)
        pairs.append((exp, hit))
    return pairs, unused


async def run_case(case: Dict[str, Any], session_factory, sem: asyncio.Semaphore) -> Dict[str, Any]:
    async with sem:
        async with session_factory() as s:
            insp = Inspection(work_order_text=case["work_order"], status="QUEUED", title=case["id"])
            s.add(insp)
            await s.flush()
            # Before photos first, as the API stores them.
            for ref, role in [(r, "before") for r in case.get("before_photos", [])] + [(r, None) for r in case["photos"]]:
                s.add(InspectionImage(inspection_id=insp.id, storage_path=photo_path(ref), filename=os.path.basename(photo_path(ref)),
                                      validation_state="VALID", role=role))
                await s.flush()  # keeps created_at order stable
            await s.commit()
            inspection_id = insp.id
        started = time.monotonic()
        await orch_mod.orchestrator.run_inspection(inspection_id)
        seconds = round(time.monotonic() - started, 1)

    async with session_factory() as s:
        insp = await s.get(Inspection, inspection_id)
        tasks = [{"description": t.description, "status": t.status, "reasoning": t.reasoning}
                 for t in (await s.execute(select(Task).where(Task.inspection_id == inspection_id).order_by(Task.created_at))).scalars()]
        tool_calls = [step["tool"] for step in (insp.agent_trace or []) if step["tool"] in ("look_closer", "count_objects")]
        compared = sorted({step["result"] for step in (insp.agent_trace or []) if step["tool"] == "compare_before_after"})

    result = {"id": case["id"], "photos": case["photos"], "before_photos": case.get("before_photos", []), "comparisons": compared,
              "work_order": case["work_order"], "seconds": seconds,
              "inspection_status": insp.status, "error": insp.error_code, "tool_calls": tool_calls, "requirements": [], "unlabelled": []}
    if insp.status == "FAILED":
        print(f"  {case['id']}: FAILED ({insp.error_code})")
        return result
    pairs, extra = match_tasks(case["expect"], tasks)
    for exp, task in pairs:
        acceptable = [exp["status"], *exp.get("also_ok", [])]
        predicted = task["status"] if task else None
        result["requirements"].append({
            "match": exp["match"], "expected": exp["status"], "acceptable": acceptable,
            "predicted": predicted, "task": task and task["description"], "reasoning": task and task["reasoning"],
            "exact": predicted == exp["status"], "ok": predicted in acceptable,
        })
    result["unlabelled"] = extra
    marks = " ".join(f"{r['predicted'] or 'UNMATCHED'}{'' if r['ok'] else '(!)'}" for r in result["requirements"])
    print(f"  {case['id']}: {marks}  [{seconds}s, {len(tool_calls)} tool calls]")
    return result


def score(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    reqs = [r for res in results for r in res["requirements"] if r["predicted"]]
    not_done = [r for r in reqs if "DONE" not in r["acceptable"]]
    definite = [r for r in reqs if r["expected"] in ("DONE", "MISSING") and "CANT_TELL" not in r["acceptable"]]
    confusion = Counter((r["expected"], r["predicted"]) for r in reqs)
    return {
        "cases": len(results),
        "cases_failed": sum(1 for r in results if r["inspection_status"] == "FAILED"),
        "requirements_scored": len(reqs),
        "requirements_unmatched": sum(1 for res in results for r in res["requirements"] if not r["predicted"]),
        "unlabelled_tasks": sum(len(r["unlabelled"]) for r in results),
        "acceptable": sum(r["ok"] for r in reqs),
        "exact": sum(r["exact"] for r in reqs),
        "false_completions": sum(r["predicted"] == "DONE" for r in not_done),
        "false_completion_opportunities": len(not_done),
        "false_missing": sum(r["predicted"] == "MISSING" and "MISSING" not in r["acceptable"] for r in reqs),
        "over_cautious": sum(r["predicted"] == "CANT_TELL" for r in definite),
        "definite_labels": len(definite),
        "confusion": {f"{e}->{p}": n for (e, p), n in sorted(confusion.items())},
        "tool_calls": sum(len(r["tool_calls"]) for r in results),
        "median_seconds": sorted(r["seconds"] for r in results)[len(results) // 2] if results else 0,
    }


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def write_markdown(summary: Dict[str, Any], results: List[Dict[str, Any]]) -> str:
    s = summary
    lines = [
        "# Evaluation results", "",
        f"Run: {time.strftime('%Y-%m-%d %H:%M')} · {s['cases']} cases · {s['requirements_scored']} scored requirements · live Meta API", "",
        "| Metric | Result |", "|---|---|",
        f"| **False completions** (DONE where the photos don't support it) | **{pct(s['false_completions'], s['false_completion_opportunities'])}** |",
        f"| False MISSING (flagged as not done when that isn't supported) | {pct(s['false_missing'], s['requirements_scored'])} |",
        f"| Acceptable verdict | {pct(s['acceptable'], s['requirements_scored'])} |",
        f"| Exact match with the primary label | {pct(s['exact'], s['requirements_scored'])} |",
        f"| Over-cautious (CANT_TELL where the photo clearly decides) | {pct(s['over_cautious'], s['definite_labels'])} |",
        f"| Technical failures | {s['cases_failed']} of {s['cases']} cases |",
        f"| Investigation tool calls | {s['tool_calls']} |",
        f"| Median time per inspection | {s['median_seconds']} s |", "",
        "Confusion (expected → predicted): " + ", ".join(f"`{k}` {v}" for k, v in s["confusion"].items()), "",
        "## Per case", "",
        "| Case | Requirement | Expected | Got | |", "|---|---|---|---|---|",
    ]
    for res in results:
        if res["inspection_status"] == "FAILED":
            lines.append(f"| {res['id']} | — | — | FAILED ({res['error']}) | technical |")
            continue
        for r in res["requirements"]:
            exp = r["expected"] + (f" (or {', '.join(r['acceptable'][1:])})" if len(r["acceptable"]) > 1 else "")
            mark = "ok" if r["ok"] else "**wrong**"
            lines.append(f"| {res['id']} | {r['task'] or 'not planned'} | {exp} | {r['predicted'] or '—'} | {mark} |")
    lines += ["", "## Caveats", "",
              "- Photos are AI-generated (muse-image-1.0) to depict specific situations; real site photos are messier.",
              "- Labels were assigned by one person looking at each photo; `also_ok` marks answers that are also defensible.",
              f"- {s['cases']} cases is a small set: treat the numbers as a sanity check, not a benchmark.",
              "- Before photos for cases 27-31 were made by editing the after photo (muse-image-1.0 image edits), so the "
              "matching pairs really show the same wall; case 28 pairs it with a different room on purpose.",
              "- The work-order preflight is skipped; the rest of the pipeline runs exactly as in the app."]
    return "\n".join(lines) + "\n"


async def main(prefixes: List[str]) -> None:
    cases = json.load(open(os.path.join(EVAL_DIR, "cases.json"), encoding="utf-8"))["cases"]
    if prefixes:
        cases = [c for c in cases if any(c["id"].startswith(p) for p in prefixes)]
    db = os.path.join(tempfile.mkdtemp(prefix="proofline-eval-"), "eval.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    orch_mod.async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print(f"Running {len(cases)} case(s)...")
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(run_case(c, orch_mod.async_session, sem) for c in cases))
    await engine.dispose()

    summary = score(results)
    if not prefixes:  # partial runs are for debugging; only a full run replaces the published results
        with open(os.path.join(EVAL_DIR, "results.json"), "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "results": results}, f, indent=1)
        with open(os.path.join(EVAL_DIR, "results.md"), "w", encoding="utf-8") as f:
            f.write(write_markdown(summary, results))
    else:
        out = os.path.join(os.path.dirname(db), "partial_results.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "results": results}, f, indent=1)
        print("partial results:", out)
    print(json.dumps({k: v for k, v in summary.items() if k != "confusion"}, indent=1))
    print("confusion:", summary["confusion"])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

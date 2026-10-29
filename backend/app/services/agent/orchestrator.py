"""Inspection orchestrator: owns state and runs the bounded pipeline

PLANNING -> ANALYZING -> COMPARING (only with before photos) -> VERIFYING
  -> INVESTIGATING (only for unresolved requirements)
  -> GROUNDING (only if SAM is still needed) -> COMPLETED | NEEDS_USER_ACTION

Any provider failure ends in FAILED with an error code; it is never recorded as a task status.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from ...guardrails.errors import ErrorCode
from ..meta_client import ModelError
from ..persistence import async_session
from ..segmentation import segment_object
from app.models.inspection_models import (
    EvidenceLink, FollowUpRequest, Inspection, InspectionImage, Notification, Observation, Task,
)
from .comparer import comparer, enforce_same_place, observation_text
from .investigator import InvestigationContext, investigator
from .planner import planner
from .verifier import verifier
from .visual_analyst import visual_analyst

log = logging.getLogger("proofline.orchestrator")

MAX_SAM_CALLS = 6


def overall_outcome(statuses: List[str]) -> str:
    if "MISSING" in statuses:
        return "ATTENTION_REQUIRED"
    if "CANT_TELL" in statuses:
        return "EVIDENCE_INCOMPLETE"
    return "NO_FLAGGED_ISSUES"


def summarize(statuses: List[str], images_analyzed: int, images_total: int) -> str:
    done, missing, cant = (statuses.count(s) for s in ("DONE", "MISSING", "CANT_TELL"))
    return (f"{len(statuses)} requirement(s) checked against {images_analyzed} of {images_total} photo(s): "
            f"{done} supported, {missing} not met, {cant} need more evidence.")


class Orchestrator:
    async def _set_status(self, inspection_id: str, status: str, **fields: Any) -> None:
        async with async_session() as session:
            insp = await session.get(Inspection, inspection_id)
            if insp:
                insp.status = status
                for k, v in fields.items():
                    setattr(insp, k, v)
                await session.commit()

    async def _notify(self, inspection_id: str, type_: str, title: str, message: str) -> None:
        async with async_session() as session:
            session.add(Notification(inspection_id=inspection_id, type=type_, title=title, message=message))
            await session.commit()

    async def run_inspection(self, inspection_id: str) -> None:
        try:
            await self._run(inspection_id)
        except ModelError as e:
            log.warning("inspection %s failed: %s %s", inspection_id, e.code.value, e)
            await self._fail(inspection_id, e.code.value, str(e))
        except Exception:
            log.exception("inspection %s crashed", inspection_id)
            await self._fail(inspection_id, ErrorCode.INTERNAL_ERROR.value, "Unexpected error while running the inspection.")

    async def _fail(self, inspection_id: str, code: str, message: str) -> None:
        await self._set_status(inspection_id, "FAILED", error_code=code, error_message=message)
        await self._notify(inspection_id, "INSPECTION_FAILED", "Inspection failed",
                           "A technical problem stopped this inspection. No findings were recorded; you can retry.")

    async def _run(self, inspection_id: str) -> None:
        async with async_session() as session:
            insp = await session.get(Inspection, inspection_id)
            if not insp:
                return
            work_order = insp.work_order_text
            images = (await session.execute(
                select(InspectionImage).where(InspectionImage.inspection_id == inspection_id,
                                              InspectionImage.validation_state == "VALID")
                .order_by(InspectionImage.created_at)
            )).scalars().all()
            image_rows = [{"id": i.id, "path": i.storage_path, "filename": i.filename, "role": i.role} for i in images]
        alias_of = {img["id"]: f"P{n}" for n, img in enumerate(image_rows, 1)}
        after_rows = [r for r in image_rows if r["role"] != "before"]
        before_rows = [r for r in image_rows if r["role"] == "before"]

        # 1. Plan
        await self._set_status(inspection_id, "PLANNING")
        plan = await planner.plan(work_order)
        async with async_session() as session:
            task_rows = [Task(inspection_id=inspection_id, status="PENDING", description=t["description"],
                              observable_criteria=t["observable_criteria"]) for t in plan]
            session.add_all(task_rows)
            await session.commit()
            tasks = [{"alias": f"T{n}", "id": row.id, "description": row.description,
                      "observable_criteria": row.observable_criteria} for n, row in enumerate(task_rows, 1)]
        task_by_alias = {t["alias"]: t for t in tasks}

        # 2. Analyze every after photo once (before photos are only read next to after photos, in step 3)
        await self._set_status(inspection_id, "ANALYZING")
        analyses = await visual_analyst.analyze_images(after_rows, tasks)
        failures = [r for r in analyses.values() if isinstance(r, ModelError)]
        if after_rows and len(failures) == len(after_rows):
            raise failures[0]

        observations: List[Dict[str, Any]] = []
        async with async_session() as session:
            for img in after_rows:
                row = await session.get(InspectionImage, img["id"])
                result = analyses.get(img["id"])
                if isinstance(result, ModelError):
                    row.analysis_state = "FAILED"
                    continue
                row.analysis_state = "ANALYZED" if result["image_class"] == "USABLE" else result["image_class"]
                for o in result["observations"]:
                    obs = Observation(
                        inspection_id=inspection_id, image_id=img["id"],
                        relevant_task_ids=[task_by_alias[a]["id"] for a in o["task_aliases"]],
                        observation_text=o["text"], limitations=o["limitations"],
                        meta_data={"object_phrase": o["object_phrase"], "image_class": result["image_class"]},
                    )
                    session.add(obs)
                    await session.flush()
                    observations.append({"alias": f"O{len(observations) + 1}", "id": obs.id, "image_id": img["id"],
                                         "image_path": img["path"], "image_alias": alias_of[img["id"]], **o})
            await session.commit()
        obs_by_alias = {o["alias"]: o for o in observations}

        # 3. Compare before and after photos (a provider failure here fails the inspection: the user's
        #    before photos must not be silently ignored)
        usable_after = [r for r in after_rows if not isinstance(analyses.get(r["id"]), ModelError)]
        compare_trace: List[Dict[str, Any]] = []
        compared = bool(before_rows and usable_after)
        if compared:
            await self._set_status(inspection_id, "COMPARING")
            compare_trace = await self._compare(inspection_id, before_rows, usable_after, tasks, alias_of,
                                                observations, obs_by_alias)

        # 4. Verify
        await self._set_status(inspection_id, "VERIFYING")
        verdicts = enforce_same_place(await verifier.verify(tasks, observations), obs_by_alias, observations)

        # 5. Investigate unresolved requirements with the bounded tool loop
        photos = {alias_of[img["id"]]: {"id": img["id"], "path": img["path"], "filename": img.get("filename"),
                                        "image_class": analyses[img["id"]]["image_class"]}
                  for img in usable_after}
        if compared:
            photos.update({alias_of[img["id"]]: {"id": img["id"], "path": img["path"], "filename": img.get("filename"),
                                                 "image_class": "USABLE", "role": "before"} for img in before_rows})
        ctx = InvestigationContext(inspection_id=inspection_id, photos=photos, observations=observations,
                                   add_observation=self._observation_adder(inspection_id, photos, task_by_alias, observations, obs_by_alias))
        ctx.trace.extend(compare_trace)
        if photos and any(v["status"] == "CANT_TELL" for v in verdicts.values()):
            await self._set_status(inspection_id, "INVESTIGATING")
            verdicts = enforce_same_place(await investigator.investigate(ctx, tasks, verdicts), obs_by_alias, observations)

        # 6. Ground evidence for definite findings with SAM (best effort, bounded)
        regions = await self._ground(inspection_id, verdicts, obs_by_alias, known=ctx.regions)

        # 7. Persist findings, evidence, follow-ups, notifications
        statuses = []
        follow_ups = 0
        async with async_session() as session:
            for alias, verdict in verdicts.items():
                task = await session.get(Task, task_by_alias[alias]["id"])
                task.status = verdict["status"]
                task.reasoning = verdict["reasoning"]
                task.recommended_action = verdict["follow_up_request"] or None
                statuses.append(verdict["status"])
                for oa in verdict["observation_aliases"]:
                    obs = obs_by_alias[oa]
                    found = regions.get((obs["image_id"], obs["object_phrase"]))
                    session.add(EvidenceLink(task_id=task.id, observation_id=obs["id"], image_id=obs["image_id"],
                                             region=found or None, region_source="sam-3.1" if found else None))
                if verdict["status"] == "CANT_TELL":
                    follow_ups += 1
                    session.add(FollowUpRequest(inspection_id=inspection_id, task_id=task.id,
                                                request_text=verdict["follow_up_request"]))
            await session.commit()

        analyzed = len(after_rows) - len(failures) + (len(before_rows) if compared else 0)
        outcome = overall_outcome(statuses)
        lifecycle = "NEEDS_USER_ACTION" if follow_ups else "COMPLETED"
        await self._set_status(inspection_id, lifecycle, overall_outcome=outcome, agent_trace=ctx.trace or None,
                               summary=summarize(statuses, analyzed, len(image_rows)), error_code=None, error_message=None)
        if follow_ups:
            await self._notify(inspection_id, "FOLLOW_UP_REQUESTED", "More photos needed",
                               f"{follow_ups} requirement(s) could not be verified from the submitted photos.")
        elif outcome == "ATTENTION_REQUIRED":
            await self._notify(inspection_id, "INSPECTION_ATTENTION", "Inspection needs attention",
                               f"{statuses.count('MISSING')} requirement(s) appear not to be met.")
        else:
            await self._notify(inspection_id, "INSPECTION_COMPLETED", "Inspection report ready",
                               "All requirements are supported by the submitted photos.")

    async def recheck_task(self, inspection_id: str, task_id: str, new_image_ids: List[str]) -> None:
        """Re-verify one requirement after follow-up photos were attached.

        A provider failure here never touches the existing findings: the requirement keeps its
        previous verdict, the follow-up stays open with last_error set, and the user can retry.
        """
        try:
            await self._recheck(inspection_id, task_id, new_image_ids)
        except Exception as e:
            if isinstance(e, ModelError):
                log.warning("re-check %s/%s failed: %s %s", inspection_id, task_id, e.code.value, e)
                reason = f"The new photo could not be checked ({e.code.value}). The earlier result still stands; try again."
            else:
                log.exception("re-check %s/%s crashed", inspection_id, task_id)
                reason = "Unexpected error while checking the new photo. The earlier result still stands; try again."
            async with async_session() as session:
                fu = (await session.execute(select(FollowUpRequest).where(FollowUpRequest.task_id == task_id))).scalars().first()
                if fu:
                    fu.status, fu.last_error = "PENDING", reason
                await session.commit()
            await self._set_status(inspection_id, "NEEDS_USER_ACTION")
            await self._notify(inspection_id, "FOLLOW_UP_FAILED", "Follow-up photo not checked", reason)

    async def _recheck(self, inspection_id: str, task_id: str, new_image_ids: List[str]) -> None:
        async with async_session() as session:
            insp = await session.get(Inspection, inspection_id)
            task_row = await session.get(Task, task_id)
            images = (await session.execute(
                select(InspectionImage).where(InspectionImage.inspection_id == inspection_id,
                                              InspectionImage.validation_state == "VALID")
                .order_by(InspectionImage.created_at)
            )).scalars().all()
            prior = (await session.execute(
                select(Observation).where(Observation.inspection_id == inspection_id).order_by(Observation.created_at)
            )).scalars().all()
            trace = list(insp.agent_trace or [])
            image_alias = {img.id: f"P{n}" for n, img in enumerate(images, 1)}
            image_rows = [{"id": i.id, "path": i.storage_path, "filename": i.filename, "state": i.analysis_state, "role": i.role}
                          for i in images]
            task = {"alias": "T1", "id": task_row.id, "description": task_row.description,
                    "observable_criteria": task_row.observable_criteria}
            # Only evidence about this requirement is relevant; aliases are numbered fresh for this run.
            observations = [{"alias": f"O{n}", "id": o.id, "image_id": o.image_id,
                             "image_path": next((r["path"] for r in image_rows if r["id"] == o.image_id), None),
                             "image_alias": image_alias.get(o.image_id, ""), "text": o.observation_text,
                             "task_aliases": ["T1"], "limitations": o.limitations or "",
                             "object_phrase": (o.meta_data or {}).get("object_phrase", ""),
                             "taken": (o.meta_data or {}).get("role", "after"), "source": (o.meta_data or {}).get("source"),
                             "same_place": (o.meta_data or {}).get("same_place")}
                            for n, o in enumerate((o for o in prior if task_id in (o.relevant_task_ids or [])), 1)]
        obs_by_alias = {o["alias"]: o for o in observations}
        task_by_alias = {"T1": task}

        # 1. Analyze only the new photos, against this one requirement
        await self._set_status(inspection_id, "REVERIFYING")
        new_rows = [r for r in image_rows if r["id"] in new_image_ids]
        analyses = await visual_analyst.analyze_images(new_rows, [task])
        failures = [r for r in analyses.values() if isinstance(r, ModelError)]
        if new_rows and len(failures) == len(new_rows):
            async with async_session() as session:
                for r in new_rows:
                    (await session.get(InspectionImage, r["id"])).analysis_state = "FAILED"
                await session.commit()
            raise failures[0]

        async with async_session() as session:
            for img in new_rows:
                row = await session.get(InspectionImage, img["id"])
                result = analyses[img["id"]]
                if isinstance(result, ModelError):
                    row.analysis_state = "FAILED"
                    continue
                row.analysis_state = img["state"] = "ANALYZED" if result["image_class"] == "USABLE" else result["image_class"]
                for o in result["observations"]:
                    obs = Observation(inspection_id=inspection_id, image_id=img["id"], relevant_task_ids=[task_id],
                                      observation_text=o["text"], limitations=o["limitations"],
                                      meta_data={"object_phrase": o["object_phrase"], "image_class": result["image_class"],
                                                 "source": "follow_up"})
                    session.add(obs)
                    await session.flush()
                    entry = {"alias": f"O{len(observations) + 1}", "id": obs.id, "image_id": img["id"], "image_path": img["path"],
                             "image_alias": image_alias[img["id"]], **o, "task_aliases": ["T1"]}
                    observations.append(entry)
                    obs_by_alias[entry["alias"]] = entry
            await session.commit()

        # 2. Compare the new photos with any before photos, then verify, then let the investigator look closer
        before_rows = [r for r in image_rows if r["role"] == "before"]
        usable_new = [r for r in new_rows if not isinstance(analyses.get(r["id"]), ModelError)]
        compare_trace: List[Dict[str, Any]] = []
        if before_rows and usable_new:
            compare_trace = await self._compare(inspection_id, before_rows, usable_new, [task], image_alias,
                                                observations, obs_by_alias)
        verdict = enforce_same_place(await verifier.verify([task], observations), obs_by_alias, observations)["T1"]
        photos = {image_alias[r["id"]]: {"id": r["id"], "path": r["path"], "filename": r["filename"], "role": r["role"],
                                         "image_class": "USABLE" if r["state"] == "ANALYZED" else r["state"]}
                  for r in image_rows if r["state"] in ("ANALYZED", "LOW_QUALITY", "IRRELEVANT", "NOT_A_PHOTO")}
        ctx = InvestigationContext(inspection_id=inspection_id, photos=photos, observations=observations,
                                   add_observation=self._observation_adder(inspection_id, photos, task_by_alias, observations, obs_by_alias))
        ctx.trace.extend(compare_trace)
        if verdict["status"] == "CANT_TELL" and photos:
            verdict = await investigator.investigate_task(ctx, task, verdict)
            verdict = enforce_same_place({"T1": verdict}, obs_by_alias, observations)["T1"]
        ctx.trace.append({"task_id": task_id, "tool": "follow_up_check", "args": {"photos": len(new_rows)}, "ok": True,
                          "result": verdict["status"], "ms": 0})
        for step in ctx.trace:
            step["round"] = "follow_up"
        regions = await self._ground(inspection_id, {"T1": verdict}, obs_by_alias, known=ctx.regions, stage="REVERIFYING")

        # 3. Replace this requirement's findings; other requirements are untouched
        async with async_session() as session:
            task_row = await session.get(Task, task_id)
            task_row.status = verdict["status"]
            task_row.reasoning = verdict["reasoning"]
            task_row.recommended_action = verdict["follow_up_request"] or None
            for link in (await session.execute(select(EvidenceLink).where(EvidenceLink.task_id == task_id))).scalars().all():
                await session.delete(link)
            for oa in verdict["observation_aliases"]:
                obs = obs_by_alias[oa]
                found = regions.get((obs["image_id"], obs["object_phrase"]))
                session.add(EvidenceLink(task_id=task_id, observation_id=obs["id"], image_id=obs["image_id"],
                                         region=found or None, region_source="sam-3.1" if found else None))
            fu = (await session.execute(select(FollowUpRequest).where(FollowUpRequest.task_id == task_id))).scalars().first()
            fu.last_error = None
            if verdict["status"] == "CANT_TELL":
                fu.status, fu.request_text = "PENDING", verdict["follow_up_request"]
            else:
                fu.status = "RESOLVED"
            all_tasks = (await session.execute(select(Task).where(Task.inspection_id == inspection_id))).scalars().all()
            pending = (await session.execute(select(FollowUpRequest).where(
                FollowUpRequest.inspection_id == inspection_id, FollowUpRequest.status == "PENDING"))).scalars().all()
            insp = await session.get(Inspection, inspection_id)
            insp.agent_trace = trace + ctx.trace
            await session.commit()
            statuses = [t.status for t in all_tasks]
            open_follow_ups = len(pending)

        analyzed = sum(1 for r in image_rows if r["state"] not in ("FAILED", "PENDING"))
        outcome = overall_outcome(statuses)
        await self._set_status(inspection_id, "NEEDS_USER_ACTION" if open_follow_ups else "COMPLETED", overall_outcome=outcome,
                               summary=summarize(statuses, analyzed, len(image_rows)), error_code=None, error_message=None)
        label = {"DONE": "now supported", "MISSING": "shown as not met"}.get(verdict["status"], "still needs evidence")
        await self._notify(inspection_id, "FOLLOW_UP_CHECKED", "Follow-up photo checked",
                           f'"{task["description"][:80]}" is {label}.')

    async def _compare(self, inspection_id: str, before_rows: List[Dict[str, Any]], after_rows: List[Dict[str, Any]],
                       tasks: List[Dict[str, Any]], alias_of: Dict[str, str], observations: List[Dict[str, Any]],
                       obs_by_alias: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Compare before photos with after photos; store each comparison as an observation on the after photo.
        Returns one trace step per requirement that was compared."""
        started = time.monotonic()
        comparisons = await comparer.compare([{"alias": alias_of[r["id"]], "path": r["path"]} for r in before_rows],
                                             [{"alias": alias_of[r["id"]], "path": r["path"]} for r in after_rows], tasks)
        id_of = {alias: image_id for image_id, alias in alias_of.items()}
        path_of = {r["id"]: r["path"] for r in before_rows + after_rows}
        task_by_alias = {t["alias"]: t for t in tasks}
        by_task: Dict[str, List[Dict[str, Any]]] = {}
        async with async_session() as session:
            for r in before_rows:
                (await session.get(InspectionImage, r["id"])).analysis_state = "ANALYZED"
            for c in comparisons:
                after_id = id_of[c["after_photo"]]
                text = observation_text(c)
                obs = Observation(inspection_id=inspection_id, image_id=after_id,
                                  relevant_task_ids=[task_by_alias[a]["id"] for a in c["task_aliases"]],
                                  observation_text=text, limitations=c["limitations"],
                                  meta_data={"object_phrase": c["object_phrase"], "source": "comparison",
                                             "same_place": c["same_place"], "before_image_id": id_of[c["before_photo"]]})
                session.add(obs)
                await session.flush()
                entry = {"alias": f"O{len(observations) + 1}", "id": obs.id, "image_id": after_id, "image_path": path_of[after_id],
                         "image_alias": c["after_photo"], "text": text, "task_aliases": c["task_aliases"],
                         "object_phrase": c["object_phrase"], "limitations": c["limitations"], "taken": "after",
                         "source": "comparison", "same_place": c["same_place"]}
                observations.append(entry)
                obs_by_alias[entry["alias"]] = entry
                for a in c["task_aliases"]:
                    by_task.setdefault(a, []).append(c)
            await session.commit()
        ms = int((time.monotonic() - started) * 1000)
        label = {"YES": "same place", "NO": "different place", "UNSURE": "unclear if same place"}
        return [{"task_id": task_by_alias[a]["id"], "tool": "compare_before_after", "ok": True, "ms": ms,
                 "args": {"pairs": [f'{c["before_photo"][1:]}->{c["after_photo"][1:]}' for c in cs]},
                 "result": "; ".join(f'{label[c["same_place"]]}: {c["change"]}' for c in cs)[:300]}
                for a, cs in by_task.items()]

    def _observation_adder(self, inspection_id: str, photos: Dict[str, Dict[str, Any]], task_by_alias: Dict[str, Dict[str, Any]],
                           observations: List[Dict[str, Any]], obs_by_alias: Dict[str, Dict[str, Any]]):
        """Persist an observation produced by an investigation tool and return its alias."""
        async def add(image_alias: str, text: str, task_alias: str, limitations: str, object_phrase: str) -> str:
            photo = photos[image_alias]
            taken = "before" if photo.get("role") == "before" else "after"
            async with async_session() as session:
                obs = Observation(inspection_id=inspection_id, image_id=photo["id"],
                                  relevant_task_ids=[task_by_alias[task_alias]["id"]], observation_text=text,
                                  limitations=limitations,
                                  meta_data={"object_phrase": object_phrase, "source": "investigation", "role": taken})
                session.add(obs)
                await session.commit()
                entry = {"alias": f"O{len(observations) + 1}", "id": obs.id, "image_id": photo["id"], "image_path": photo["path"],
                         "image_alias": image_alias, "text": text, "task_aliases": [task_alias],
                         "object_phrase": object_phrase, "limitations": limitations, "taken": taken, "source": "investigation"}
            observations.append(entry)
            obs_by_alias[entry["alias"]] = entry
            return entry["alias"]
        return add

    async def _ground(self, inspection_id: str, verdicts: Dict[str, Dict[str, Any]], obs_by_alias: Dict[str, Dict[str, Any]],
                      known: Optional[Dict[Tuple[str, str], Optional[List[Dict[str, Any]]]]] = None,
                      stage: str = "GROUNDING") -> Dict[Tuple[str, str], Optional[List[Dict[str, Any]]]]:
        known = dict(known or {})
        targets = []
        for verdict in verdicts.values():
            if verdict["status"] not in ("DONE", "MISSING"):
                continue
            for oa in verdict["observation_aliases"]:
                obs = obs_by_alias[oa]
                key = (obs["image_id"], obs["object_phrase"])
                if obs["object_phrase"] and key not in targets and key not in known:
                    targets.append(key)
        targets = targets[:MAX_SAM_CALLS]
        if not targets:
            return known
        await self._set_status(inspection_id, stage)
        paths = {o["image_id"]: o["image_path"] for o in obs_by_alias.values()}
        regions = known
        for image_id, phrase in targets:
            try:
                regions[(image_id, phrase)] = await segment_object(paths[image_id], phrase) or None
            except ModelError as e:  # grounding is optional; the finding stands without an overlay
                log.info("SAM unavailable for %s/%r: %s", image_id, phrase, e)
                regions[(image_id, phrase)] = None
        return regions


orchestrator = Orchestrator()

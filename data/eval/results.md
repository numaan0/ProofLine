# Evaluation results

Run: 2026-10-29 15:04 · 31 cases · 39 scored requirements · live Meta API

| Metric | Result |
|---|---|
| **False completions** (DONE where the photos don't support it) | **0/22 (0%)** |
| False MISSING (flagged as not done when that isn't supported) | 0/39 (0%) |
| Acceptable verdict | 39/39 (100%) |
| Exact match with the primary label | 31/39 (79%) |
| Over-cautious (CANT_TELL where the photo clearly decides) | 0/11 (0%) |
| Technical failures | 0 of 31 cases |
| Investigation tool calls | 13 |
| Median time per inspection | 24.5 s |

Confusion (expected → predicted): `CANT_TELL->CANT_TELL` 12, `DONE->CANT_TELL` 8, `DONE->DONE` 9, `MISSING->MISSING` 10

## Per case

| Case | Requirement | Expected | Got | |
|---|---|---|---|---|
| 01-outlets-covered | Install cover plates on both wall outlets | DONE | DONE | ok |
| 02-outlets-covered-plus-ceiling | Install cover plates on both wall outlets | DONE | DONE | ok |
| 02-outlets-covered-plus-ceiling | Repaint the ceiling | CANT_TELL | CANT_TELL | ok |
| 03-four-outlets-two-visible | Install cover plates on all four outlets in the room | CANT_TELL | CANT_TELL | ok |
| 04-outlet-one-uncovered | Install cover plates on both wall outlets | MISSING | MISSING | ok |
| 05-sticky-note-says-done | Install a cover plate on the outlet | MISSING | MISSING | ok |
| 06-switch-no-plate | Install a cover plate on the light switch | MISSING | MISSING | ok |
| 07-irrelevant-photo | Caulk the joint between the bathtub and the wall tile | CANT_TELL | CANT_TELL | ok |
| 08-caulk-done | Caulk the joint between the bathtub and the wall tile | DONE (or CANT_TELL) | CANT_TELL | ok |
| 09-caulk-gap | Caulk the joint between the bathtub and the wall tile | MISSING | MISSING | ok |
| 10-caulk-plus-fan | Caulk the bathtub joint | DONE (or CANT_TELL) | CANT_TELL | ok |
| 10-caulk-plus-fan | Replace the bathroom exhaust fan | CANT_TELL | CANT_TELL | ok |
| 11-handles-all | Install handles on the kitchen base cabinet doors | DONE (or CANT_TELL) | DONE | ok |
| 12-handles-missing | Install handles on the kitchen base cabinet doors | MISSING | MISSING | ok |
| 13-handles-plus-faucet | Install handles on the kitchen base cabinet doors | DONE (or CANT_TELL) | CANT_TELL | ok |
| 13-handles-plus-faucet | Replace the kitchen faucet | CANT_TELL | CANT_TELL | ok |
| 14-patch-done | Patch the hole in the drywall | DONE (or CANT_TELL) | DONE | ok |
| 15-patch-not-painted | Paint over the drywall patch to match the wall | MISSING | MISSING | ok |
| 16-wall-painted-green | Paint the living room wall sage green | DONE (or CANT_TELL) | CANT_TELL | ok |
| 17-wall-wrong-color | Paint the living room wall white | MISSING (or CANT_TELL) | MISSING | ok |
| 18-smoke-detector | Install a smoke detector on the hallway ceiling | DONE (or CANT_TELL) | DONE | ok |
| 19-two-detectors-one-visible | Install two smoke detectors in the hallway | CANT_TELL (or MISSING) | CANT_TELL | ok |
| 20-faucet-installed | Install the new kitchen faucet | DONE (or CANT_TELL) | DONE | ok |
| 21-hidden-leak | Fix the leak under the kitchen sink | CANT_TELL | CANT_TELL | ok |
| 22-hinges-not-visible | Replace all three hinges on the bedroom door | CANT_TELL | CANT_TELL | ok |
| 23-dark-blurry | Install cover plates on both wall outlets | CANT_TELL | CANT_TELL | ok |
| 24-two-photos-both-done | Install cover plates on both wall outlets | DONE | DONE | ok |
| 24-two-photos-both-done | Caulk the bathtub joint | DONE (or CANT_TELL) | CANT_TELL | ok |
| 25-two-photos-both-missing | Install cover plates on both wall outlets | MISSING | MISSING | ok |
| 25-two-photos-both-missing | Caulk the bathtub joint | MISSING | MISSING | ok |
| 26-ceiling-painted | Repaint the hallway ceiling | DONE (or CANT_TELL) | CANT_TELL | ok |
| 27-wall-before-after | Patch the hole in the living room wall next to the outlet | DONE (or CANT_TELL) | DONE | ok |
| 27-wall-before-after | Repaint the living room wall sage green | DONE (or CANT_TELL) | DONE | ok |
| 28-before-after-different-room | Patch the hole in the living room wall next to the outlet | CANT_TELL | CANT_TELL | ok |
| 28-before-after-different-room | Repaint the living room wall sage green | CANT_TELL | CANT_TELL | ok |
| 29-drywall-before-after | Patch the hole in the hallway wall | DONE (or CANT_TELL) | CANT_TELL | ok |
| 29-drywall-before-after | Paint the patched area to match the wall | MISSING (or CANT_TELL) | MISSING | ok |
| 30-caulk-before-after | Remove old caulk around the bathtub and apply new caulk | DONE (or CANT_TELL) | CANT_TELL | ok |
| 31-before-photo-only-shows-the-wall | Patch the hole in the living room wall next to the outlet | CANT_TELL | CANT_TELL | ok |

## Caveats

- Photos are AI-generated (muse-image-1.0) to depict specific situations; real site photos are messier.
- Labels were assigned by one person looking at each photo; `also_ok` marks answers that are also defensible.
- 31 cases is a small set: treat the numbers as a sanity check, not a benchmark.
- Before photos for cases 27-31 were made by editing the after photo (muse-image-1.0 image edits), so the matching pairs really show the same wall; case 28 pairs it with a different room on purpose.
- The work-order preflight is skipped; the rest of the pipeline runs exactly as in the app.

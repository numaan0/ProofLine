"""Hourly cap on model-backed runs, so a public deployment can't spend the API credits.

New inspections, retries and follow-up checks all count, across all devices (RUNS_PER_HOUR) and per
device (RUNS_PER_DEVICE_PER_HOUR), over a rolling hour. A limit of 0 turns it off, which is the default
for local runs; the Render blueprint sets both. Counts live in memory, so a restart resets them.
"""
from __future__ import annotations

import os
import time
from collections import deque

from .guardrails.errors import ErrorCode, ErrorStage, GuardrailViolation, ValidationErrorDetail

WINDOW_SECONDS = 3600.0
_runs: deque[tuple[float, str]] = deque()


def _limit(name: str) -> int:
    return int(os.getenv(name, "0") or 0)


def count_run(device: str) -> None:
    """Record one run for this device, or raise USAGE_LIMIT if either hourly limit is reached."""
    now = time.monotonic()
    while _runs and now - _runs[0][0] > WINDOW_SECONDS:
        _runs.popleft()
    total, per_device = _limit("RUNS_PER_HOUR"), _limit("RUNS_PER_DEVICE_PER_HOUR")
    if (total and len(_runs) >= total) or (per_device and sum(d == device for _, d in _runs) >= per_device):
        raise GuardrailViolation(ValidationErrorDetail(
            code=ErrorCode.USAGE_LIMIT, stage=ErrorStage.REQUEST_VALIDATION,
            message="This public demo has reached its hourly limit of checks.",
            suggestion="Try again later, or run ProofLine locally from the GitHub repo.", retryable=True))
    _runs.append((now, device))

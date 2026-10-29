"""Anonymous per-device scoping, in place of sign-in.

Each browser gets a random device id in an HttpOnly cookie on its first request. Inspections and
their notifications belong to the device that created them; other devices get 404s. This keeps
devices apart in a demo; it is not authentication (anyone holding the cookie value is that device).
"""
from __future__ import annotations

import re
import uuid

from fastapi import Request

DEVICE_COOKIE = "proofline_device"
COOKIE_MAX_AGE = 400 * 24 * 3600  # the longest lifetime browsers honour
_VALID = re.compile(r"^[0-9a-f]{32}$")


async def device_middleware(request: Request, call_next):
    device = request.cookies.get(DEVICE_COOKIE, "")
    issued = not _VALID.match(device)
    if issued:
        device = uuid.uuid4().hex
    request.state.device_id = device
    response = await call_next(request)
    if issued:
        response.set_cookie(DEVICE_COOKIE, device, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
    return response


def current_device(request: Request) -> str:
    return request.state.device_id

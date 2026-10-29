"""Meta Model API client.

Verified against the live API with scripts/smoke_meta.py. Notes:
- Muse Spark is a reasoning model: hidden reasoning tokens are taken from
  max_tokens, so small caps return content=None with finish_reason="length".
- Images are sent inline as base64 data URLs; the provider cannot reach
  local URLs such as http://127.0.0.1:8000.
- Failures raise ModelError. Callers must never turn a ModelError into an
  inspection finding.
"""
from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx
from dotenv import dotenv_values

from ..guardrails.errors import ErrorCode

BACKEND_DIR = Path(__file__).resolve().parents[2]

SPARK_MODEL = os.getenv("META_SPARK_MODEL", "muse-spark-1.3")
SAM_MODEL = os.getenv("META_SAM_MODEL", "sam-3.1")
DEFAULT_MAX_TOKENS = 4000
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAY_S = 2.0
RETRY_MAX_TOKENS = 12000  # used once when reasoning exhausts the default budget


class ModelError(Exception):
    """A provider/infrastructure failure. Not an inspection result."""

    def __init__(self, code: ErrorCode, message: str, retryable: bool = True):
        self.code = code
        self.retryable = retryable
        super().__init__(message)


def _load_api_key() -> str:
    # MODEL_API_KEY is the documented name; META_API_KEY is this project's original name.
    env = {**dotenv_values(BACKEND_DIR / ".env"), **os.environ}
    return env.get("MODEL_API_KEY") or env.get("META_API_KEY") or ""


def image_data_url(path: str | Path) -> str:
    path = Path(path)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a model reply (tolerates ```json fences)."""
    if not text:
        raise ModelError(ErrorCode.MALFORMED_MODEL_OUTPUT, "Model returned no content.")
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ModelError(ErrorCode.MALFORMED_MODEL_OUTPUT, "Model reply contained no JSON.")
    start = min(starts)
    end = text.rfind("}" if text[start] == "{" else "]") + 1
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError as e:
        raise ModelError(ErrorCode.MALFORMED_MODEL_OUTPUT, f"Model reply was not valid JSON: {e.msg}") from e


class MetaClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout: float = 120.0):
        self.api_key = api_key if api_key is not None else _load_api_key()
        self.base_url = base_url or os.getenv("META_API_BASE_URL", "https://api.meta.ai/v1")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ModelError(ErrorCode.MODEL_AUTH_FAILURE, "No MODEL_API_KEY or META_API_KEY configured.", retryable=False)
        return {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        if resp.status_code in (401, 403):
            raise ModelError(ErrorCode.MODEL_AUTH_FAILURE, "Model API rejected the credentials.", retryable=False)
        if resp.status_code == 429:
            raise ModelError(ErrorCode.MODEL_RATE_LIMIT, "Model API rate limit reached.")
        raise ModelError(ErrorCode.INTERNAL_ERROR, f"Model API returned HTTP {resp.status_code}.", retryable=resp.status_code >= 500)

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
                    resp = await client.post(path, headers=self._headers(), json=body)
            except httpx.TimeoutException as e:
                raise ModelError(ErrorCode.MODEL_TIMEOUT, "Model API request timed out.") from e
            except httpx.HTTPError as e:
                raise ModelError(ErrorCode.INTERNAL_ERROR, f"Model API request failed: {type(e).__name__}.") from e
            # Transient provider errors get one retry after a short pause; everything else fails fast.
            if resp.status_code in TRANSIENT_STATUS and attempt == 0:
                await asyncio.sleep(RETRY_DELAY_S)
                continue
            break
        self._raise_for_status(resp)
        return resp.json()

    async def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None,
                   max_tokens: int = DEFAULT_MAX_TOKENS, model: str = SPARK_MODEL) -> Dict[str, Any]:
        """Return the assistant message dict (may contain tool_calls)."""
        body: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        data = await self._post("/chat/completions", body)
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError(ErrorCode.MALFORMED_MODEL_OUTPUT, "Model API response had no choices.") from e
        message = choice.get("message") or {}
        if choice.get("finish_reason") == "length" and not message.get("content") and not message.get("tool_calls"):
            # Hidden reasoning used the whole budget; one retry with more room usually answers.
            if max_tokens < RETRY_MAX_TOKENS:
                return await self.chat(messages, tools=tools, max_tokens=RETRY_MAX_TOKENS, model=model)
            raise ModelError(ErrorCode.MALFORMED_MODEL_OUTPUT, "Model ran out of tokens before answering.")
        return message

    async def chat_json(self, prompt: str, image_paths: Sequence[str | Path] = (), max_tokens: int = DEFAULT_MAX_TOKENS) -> Any:
        """Single-turn call that must answer with JSON. Images are attached inline."""
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for p in image_paths:
            content.append({"type": "image_url", "image_url": {"url": image_data_url(p)}})
        messages = [{"role": "user", "content": content}]
        message = await self.chat(messages, max_tokens=max_tokens)
        try:
            return extract_json(message.get("content") or "")
        except ModelError as e:
            if e.code != ErrorCode.MALFORMED_MODEL_OUTPUT:
                raise
        # One corrective turn: show the model its reply and ask for the JSON only.
        messages += [{"role": "assistant", "content": message.get("content") or ""},
                     {"role": "user", "content": "That reply was not valid JSON. Return ONLY the JSON object, with no other text."}]
        message = await self.chat(messages, max_tokens=max_tokens)
        return extract_json(message.get("content") or "")

    async def segment(self, image_path: str | Path, prompt: str) -> str:
        """Run SAM 3.1 with a noun-phrase prompt; return the raw segmentation token text."""
        body = {
            "model": SAM_MODEL,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_data_url(image_path)},
            ]}],
            "stream": True,
            "metadata": {"include_confidence": "true"},
        }
        text = ""
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
                async with client.stream("POST", "/responses", json=body,
                                         headers={**self._headers(), "Accept": "text/event-stream"}) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        self._raise_for_status(resp)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "response.output_text.delta":
                            text += event.get("delta", "")
        except httpx.TimeoutException as e:
            raise ModelError(ErrorCode.MODEL_TIMEOUT, "Segmentation request timed out.") from e
        except httpx.HTTPError as e:
            raise ModelError(ErrorCode.INTERNAL_ERROR, f"Segmentation request failed: {type(e).__name__}.") from e
        return text


meta_client = MetaClient()

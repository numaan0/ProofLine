"""Allowlisted tools for the investigation loop.

The model only proposes calls. Arguments are validated against a Pydantic model before
anything runs; invalid calls come back to the model as recoverable errors.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Type

from pydantic import BaseModel, ValidationError


@dataclass
class Tool:
    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[Dict[str, Any]]]

    def definition(self) -> Dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": schema}}


class ToolRegistry:
    def __init__(self, tools: List[Tool]):
        self._tools = {t.name: t for t in tools}

    def definitions(self) -> List[Dict[str, Any]]:
        return [t.definition() for t in self._tools.values()]

    def parse(self, name: str, raw_args: str | Dict[str, Any] | None) -> BaseModel:
        """Validate a proposed call. Raises ValueError with a message safe to show the model."""
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool '{name}'. Allowed: {', '.join(self._tools)}.")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except json.JSONDecodeError:
            raise ValueError("Arguments were not valid JSON.")
        try:
            return tool.args_model.model_validate(args)
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'args'}: {err['msg']}" for err in e.errors()[:5])
            raise ValueError(f"Invalid arguments: {problems}")

    async def run(self, name: str, args: BaseModel) -> Dict[str, Any]:
        return await self._tools[name].handler(args)

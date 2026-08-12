# src/tkos_runtime/api/render_models.py
"""Pydantic v2 models for ``POST /v1/context-packs:render``.

Two mutually exclusive input modes:
  * ``pack``: a pre-resolved ContextPack dict (from a prior /resolve call).
  * ``resolve_request``: resolve parameters — the server resolves first, then renders.

Exactly one must be present; both or neither → HTTP 422.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class RenderOptions(BaseModel):
    format: Literal["markdown"] = "markdown"
    mode: Literal["deterministic", "llm_with_fallback", "llm_required"] = "deterministic"
    include_structured: bool = False
    max_chars: int = Field(default=12000, ge=100, le=100000)
    language: str = "zh-CN"


class RenderRequest(BaseModel):
    pack: Optional[Dict[str, Any]] = None
    resolve_request: Optional[Dict[str, Any]] = None
    render_options: RenderOptions = Field(default_factory=RenderOptions)

    @model_validator(mode="after")
    def _exactly_one_input(self) -> "RenderRequest":
        has_pack = self.pack is not None
        has_resolve = self.resolve_request is not None
        if has_pack == has_resolve:  # both or neither
            raise ValueError(
                "exactly one of 'pack' or 'resolve_request' must be provided"
            )
        return self

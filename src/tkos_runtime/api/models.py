# src/tkos_runtime/api/models.py
"""Pydantic v2 request model for ``POST /v1/context-packs:resolve``.

The response is the dict produced by ``pack_to_dict`` (arbitrary JSON), so we
only model the request body here. All fields are strings/lists of string; the
resolver parses ``as_of`` from an ISO-8601 string.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ResolveRequest(BaseModel):
    query: str
    as_of: str
    scenario: Optional[str] = None
    render: bool = False
    token_budget: Optional[int] = Field(default=None, ge=100, le=100000)
    # deprecated（过渡期仍接受，迭代 1 删除）
    enterprise_id: Optional[str] = None
    organization_scope: List[str] = Field(default_factory=list)
    purpose: Optional[str] = None
    actor_id: Optional[str] = None
    persona_id: Optional[str] = None

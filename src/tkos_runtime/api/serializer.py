# src/tkos_runtime/api/serializer.py
"""Serialize a Phase-A ``ContextPack`` to a JSON-safe dict.

Thin transport concern: the resolver/domain never sees this code. We rely on
``dataclasses.asdict`` to recurse through the nested dataclasses
(``ScopeResolution``, ``ContextPackMember``, ``AdmissionDecision``,
``GraphStatement``, ``Omission``). List fields of plain dicts
(``alternative_matches``, ``proof``, ``conflicts``) are recursed into by
``asdict`` as well; their values are already JSON primitives (str/int), so no
``URIRef``/``datetime`` leaks. The input pack is not mutated.
"""
from __future__ import annotations

import dataclasses

from tkos_runtime.domain.models import ContextPack


def pack_to_dict(pack: ContextPack) -> dict:
    """Return a JSON-serializable dict view of ``pack`` (no mutation)."""
    return dataclasses.asdict(pack)

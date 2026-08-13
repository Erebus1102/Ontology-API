# src/tkos_runtime/api/auth.py
"""authN/authZ minimal slice for API 1 Context Pack endpoints.

v1 scope (deployment-blockers-fix-design.md §B.8):
  * authN: single Bearer token via ``TKOS_API_KEY`` env var (or
    ``TKOS_API_KEYS_JSON`` for multi-token with per-purpose scoping).
  * authZ: purpose gate — ``Principal.allowed_purposes`` ×
    ``assert_purpose`` — chained before the existing
    ``AdmissionPolicy.allowed_graphs``.
  * NOT implemented: RBAC, ODRL policy engine, AuthorityBoundary
    enforcement, JWT/OIDC.

Token comparison uses ``hmac.compare_digest`` (constant-time) to resist
timing attacks.
"""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass, field
from typing import Optional, Union

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """Authenticated caller identity.

    Attributes:
        name: label for logging / audit (never surfaced in responses).
        allowed_purposes: purposes this principal may use;
            ``{"*"}`` means unrestricted.
        allowed_scopes: ``organization_scope`` whitelist;
            ``None`` means no scope restriction (v1 default).
        tenant: tenancy anchor recorded on the Principal (2.0 Key model);
            scope narrowing is carried by ``allowed_scopes``.
        role: ``cxo`` (default, all-visible) or ``executor``.
        on_behalf_of: Person IRI the Key acts for (optional).
        confirmer: whether this Principal may confirm submissions
            (modeled in 2.0; not yet consumed by the read path).
        default_scenario: scenario id used to derive ``purpose`` when
            the request omits one (2.0 scenario registry).
    """
    name: str
    allowed_purposes: set[str] = field(default_factory=lambda: {"*"})
    allowed_scopes: Optional[set[str]] = None
    tenant: str = "default"
    role: str = "cxo"                       # cxo | executor
    on_behalf_of: Optional[str] = None      # Person IRI
    confirmer: bool = False                 # submissions 确认权（本轮建模不消费）
    default_scenario: Optional[str] = None


# ---------------------------------------------------------------------------
# credential loading
# ---------------------------------------------------------------------------

def _load_credentials() -> dict[str, Principal]:
    """Load token → Principal mapping from environment variables.

    Two modes, composable (single-token wins on collision):

    ``TKOS_API_KEY``
        Single token string → ``Principal(name="default",
        allowed_purposes={"*"}, allowed_scopes=None)``.  The 2.0 Key-model
        fields take their dataclass defaults (``tenant="default"``,
        ``role="cxo"``, ``on_behalf_of=None``, ``confirmer=False``,
        ``default_scenario=None``) — i.e. single-key callers stay cxo and
        all-visible (C.4 backward-compat red line).
    ``TKOS_API_KEYS_JSON``
        JSON: ``{"<token>": {"name":"...", "purposes":[...],
        "scopes":[...], "tenant":"...", "role":"cxo|executor",
        "on_behalf_of":"...", "confirmer": false,
        "default_scenario":"..."}}``.  *purposes* and *scopes* are optional;
        defaults are ``["*"]`` and ``null`` respectively.  The 2.0
        Key-model fields (``tenant``/``role``/``on_behalf_of``/
        ``confirmer``/``default_scenario``) are all optional and default
        to ``"default"`` / ``"cxo"`` / ``None`` / ``False`` / ``None``.
    """
    principals: dict[str, Principal] = {}

    # single shared key (v1 recommended)
    single = os.environ.get("TKOS_API_KEY", "").strip()
    if single:
        principals[single] = Principal(name="default", allowed_purposes={"*"})

    # multi-token with fine-grained purposes (v1.1)
    multi_raw = os.environ.get("TKOS_API_KEYS_JSON", "").strip()
    if multi_raw:
        try:
            multi: dict = json.loads(multi_raw)
        except json.JSONDecodeError:
            pass  # malformed JSON → treat as no extra tokens
        else:
            for token, entry in multi.items():
                token = token.strip()
                if not token:
                    continue
                name = entry.get("name", token[:8])
                purposes = set(entry.get("purposes", ["*"]))
                scopes_raw = entry.get("scopes")
                scopes: Optional[set[str]] = set(scopes_raw) if scopes_raw is not None else None
                principals[token] = Principal(
                    name=name,
                    allowed_purposes=purposes,
                    allowed_scopes=scopes,
                    tenant=entry.get("tenant", "default"),
                    role=entry.get("role", "cxo"),
                    on_behalf_of=entry.get("on_behalf_of"),
                    confirmer=bool(entry.get("confirmer", False)),
                    default_scenario=entry.get("default_scenario"),
                )

    return principals


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def require_token(
    request: Request,
    cred: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Principal:
    """authN dependency: validate Bearer token.

    Returns:
        ``Principal`` on success; raises ``HTTPException(401)`` otherwise.

    Reads the credential store from ``request.app.state.principals``
    (populated once in ``create_app``).
    """
    principals: dict[str, Principal] = request.app.state.principals

    if cred is None:
        raise HTTPException(
            status_code=401,
            detail="missing or malformed bearer token",
        )

    token = cred.credentials
    for candidate, principal in principals.items():
        if hmac.compare_digest(token, candidate):
            return principal

    raise HTTPException(status_code=401, detail="invalid api key")


def assert_purpose(purpose: str, principal: Principal) -> None:
    """authZ-1 gate: raise ``HTTPException(403)`` if *purpose* is not
    permitted for *principal*.

    ``Principal.allowed_purposes`` containing ``"*"`` means unrestricted.
    """
    if "*" in principal.allowed_purposes:
        return
    if purpose not in principal.allowed_purposes:
        raise HTTPException(
            status_code=403,
            detail=(
                f"purpose '{purpose}' not permitted "
                f"for principal '{principal.name}'"
            ),
        )

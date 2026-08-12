#!/usr/bin/env python3
# scripts/agent_harness.py
"""Agent integration harness (Phase C — 联调 acceptance gate).

Simulates an agent consuming the TKOS read API (Phase B server) and validates
that the returned Context Pack is correct and agent-usable. Agent code is not
accessible, so this client stands in for it: it issues the FE strategic-issue
query, prints a readable Pack summary, and exits non-zero if the Pack is not
agent-usable (non-200 HTTP, or any required field missing).

Usage (live server, e.g. ``uvicorn tkos_runtime.api.server:app``):

    python3 scripts/agent_harness.py
    python3 scripts/agent_harness.py --query "增长" --base-url http://localhost:8000

This script is a CONSUMER only. It does not import tkos_runtime internals —
it talks to the HTTP endpoint exactly as a real agent would.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Iterable

import httpx


DEFAULT_QUERY = "是否在本季度同时完成产品 1.0 上线和灯塔项目交付"
DEFAULT_PURPOSE = "decision_preparation"
DEFAULT_AS_OF = "2026-08-11T23:59:59+08:00"
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_ACTOR_ID = "agent-harness"
DEFAULT_ENTERPRISE_ID = "tokenking"
ENDPOINT_PATH = "/v1/context-packs:resolve"

# Required scalar version/identity fields an agent relies on for traceability.
REQUIRED_FIELDS = (
    "matched_root",
    "current_facts",
    "candidate_context",
    "provenance_context",
    "context_gaps",
    "reasoning_status",
    "contributing_graphs",
    "scope_resolution",
    "proof",
    "ontology_release_id",
    "dataset_revision",
    "policy_version",
    "query_plan_version",
    "schema_version",
)


def _member_ids(members: Iterable[dict[str, Any]]) -> set[str]:
    return {m["id"] for m in members if "id" in m}


def _confirmation_tags(members: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Return a count of each confirmation_status value across candidates."""
    counts: dict[str, int] = {}
    for m in members:
        tag = m.get("confirmation_status")
        key = tag if tag is not None else "(untagged)"
        counts[key] = counts.get(key, 0) + 1
    return counts


def print_summary(pack: dict[str, Any], out=sys.stdout) -> None:
    """Render a compact, human-readable summary of the Context Pack."""
    current = pack.get("current_facts", [])
    candidates = pack.get("candidate_context", [])
    provenance = pack.get("provenance_context", [])
    gaps = pack.get("context_gaps", [])
    scope = pack.get("scope_resolution") or {}

    print("=" * 72, file=out)
    print("TKOS Context Pack — agent summary", file=out)
    print("=" * 72, file=out)
    print(f"matched_root        : {pack.get('matched_root')}", file=out)
    print(f"current_facts       : {len(current)}", file=out)
    print(f"candidate_context   : {len(candidates)}  "
          f"tags={_confirmation_tags(candidates)}", file=out)
    print(f"provenance_context  : {len(provenance)}", file=out)
    print(f"context_gaps        : {len(gaps)}", file=out)
    print(f"reasoning_status    : {pack.get('reasoning_status')}", file=out)
    print(f"contributing_graphs : {pack.get('contributing_graphs')}", file=out)
    print(f"scope.enforcement   : {scope.get('enforcement')}", file=out)
    print(f"scope.resolved      : {scope.get('resolved_scope')}", file=out)
    print(f"ontology_release_id : {pack.get('ontology_release_id')}", file=out)
    ds = pack.get("dataset_revision") or ""
    print(f"dataset_revision    : {ds[:12]}… (len={len(ds)})", file=out)
    print(f"policy_version      : {pack.get('policy_version')}", file=out)
    print(f"query_plan_version  : {pack.get('query_plan_version')}", file=out)
    print(f"schema_version      : {pack.get('schema_version')}", file=out)
    print(f"pack_id             : {pack.get('pack_id')}", file=out)
    print(f"as_of               : {pack.get('as_of')}", file=out)

    if candidates:
        print("\nFirst 5 candidate members (id / confirmation / source_graphs):",
              file=out)
        for m in candidates[:5]:
            print(f"  - {m.get('id'):55s} "
                  f"[{m.get('confirmation_status')}]  "
                  f"{m.get('source_graphs')}", file=out)

    if gaps:
        print("\nContext gaps (unknowns the agent must surface):", file=out)
        for m in gaps[:8]:
            print(f"  - {m.get('id')}", file=out)

    # Trace: prove the agent can find a confirmsEntity edge in proof.
    proof = pack.get("proof") or []
    confirms = [e for e in proof if e.get("predicate") == "confirmsEntity"]
    print(f"\nproof               : {len(proof)} edges "
          f"({len(confirms)} confirmsEntity)", file=out)
    if confirms:
        e = confirms[0]
        print(f"sample edge         : {e.get('from')} "
              f"--confirmsEntity--> {e.get('to')} "
              f"[{e.get('source_graph')}]", file=out)
    print("=" * 72, file=out)


def validate_agent_usable(pack: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems; empty list means usable.

    This mirrors the acceptance gate from ``tests/test_agent_harness.py`` so
    the CLI fails loudly on the same contracts when pointed at a live server.
    """
    problems: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in pack or pack[field] is None:
            problems.append(f"missing required field: {field}")

    if problems:
        return problems  # downstream assertions would crash; bail early.

    # Every member across current/candidate/provenance must carry non-empty
    # source_graphs, and every statement a source_graph (graph-attributed).
    for bucket in ("current_facts", "candidate_context", "provenance_context"):
        for m in pack[bucket]:
            if not m.get("source_graphs"):
                problems.append(
                    f"member {m.get('id')} in {bucket} has empty source_graphs")
            for s in m.get("statements", []):
                if not s.get("source_graph"):
                    problems.append(
                        f"statement in {m.get('id')} ({bucket}) missing "
                        f"source_graph")

    # Candidates must be tagged and must NOT leak into current_facts.
    current_ids = _member_ids(pack["current_facts"])
    for m in pack["candidate_context"]:
        if m.get("confirmation_status") not in ("Candidate",
                                                "PreliminarilyConfirmed"):
            # Untagged members are allowed (e.g. evidence/criteria pulled in by
            # traversal); only flagged candidates must be honest.
            continue
        if m["id"] in current_ids:
            problems.append(
                f"candidate {m['id']} also appears in current_facts "
                f"(epistemic-honesty violation)")

    if not pack["context_gaps"]:
        problems.append("context_gaps empty — agent cannot surface unknowns")

    if not pack["reasoning_status"]:
        problems.append("reasoning_status missing")

    scope = pack["scope_resolution"] or {}
    if scope.get("enforcement") != "not_enforced":
        problems.append(
            f"scope.enforcement={scope.get('enforcement')!r}, "
            f"expected 'not_enforced'")

    if "graph-sensitive-persona" in pack.get("contributing_graphs", []):
        problems.append("sensitive graph leaked into contributing_graphs")

    proof = pack.get("proof") or []
    if not any(e.get("predicate") == "confirmsEntity" for e in proof):
        problems.append("proof missing confirmsEntity edge — agent cannot trace")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TKOS agent integration harness — 联调 acceptance client.")
    parser.add_argument("--query", default=DEFAULT_QUERY,
                        help="natural-language strategic query (default: FE issue)")
    parser.add_argument("--purpose", default=DEFAULT_PURPOSE,
                        help="admission purpose (default: decision_preparation)")
    parser.add_argument("--as-of", default=DEFAULT_AS_OF,
                        help="ISO-8601 as-of timestamp")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help="read-API base URL (default: http://localhost:8000)")
    parser.add_argument("--actor-id", default=DEFAULT_ACTOR_ID,
                        help="actor id sent in the request body")
    parser.add_argument("--enterprise-id", default=DEFAULT_ENTERPRISE_ID,
                        help="enterprise id sent in the request body")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="HTTP timeout in seconds (default: 30)")
    parser.add_argument("--trust-env", action="store_true",
                        help="honor HTTP(S)_PROXY env vars (default: off — "
                             "the harness targets local dev servers)")
    args = parser.parse_args(argv)

    request_body = {
        "enterprise_id": args.enterprise_id,
        "organization_scope": [],
        "purpose": args.purpose,
        "query": args.query,
        "as_of": args.as_of,
        "actor_id": args.actor_id,
    }
    url = args.base_url.rstrip("/") + ENDPOINT_PATH

    print(f"POST {url}\n     query={args.query!r}\n     purpose={args.purpose}",
          file=sys.stderr)

    try:
        # trust_env defaults to False: the harness is a local-dev acceptance
        # client, and ambient HTTP(S)_PROXY settings in the operator's shell
        # should not be allowed to break a request to localhost.
        with httpx.Client(timeout=args.timeout, trust_env=args.trust_env) as client:
            resp = client.post(url, json=request_body)
    except httpx.RequestError as exc:
        print(f"ERROR: request failed: {exc}", file=sys.stderr)
        return 3

    if resp.status_code != 200:
        print(f"ERROR: HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        return 2

    try:
        pack = resp.json()
    except ValueError as exc:
        print(f"ERROR: response not JSON: {exc}", file=sys.stderr)
        return 2

    print_summary(pack)
    problems = validate_agent_usable(pack)
    if problems:
        print("\nFAILED agent-usable gate:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print("\nPASS: Pack is agent-usable.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

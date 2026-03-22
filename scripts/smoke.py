#!/usr/bin/env python3
"""
AleXiona Smoke-Test
====================
Checks that all critical system components are reachable and respond correctly.

Usage
-----
  # Against a running stack (default):
  python scripts/smoke.py

  # Against a custom backend URL:
  BACKEND_URL=http://localhost:8000  python scripts/smoke.py
  FRONTEND_URL=http://localhost:3000 python scripts/smoke.py

  # Start the backend automatically (requires NEO4J_* env vars set):
  python scripts/smoke.py --start-backend

Exit codes
----------
  0  all checks passed
  1  one or more checks failed
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import urllib.request
import urllib.error

BACKEND_URL  = os.getenv("BACKEND_URL",  "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
SKIP = "\033[33m~\033[0m"


# ── helpers ───────────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 5) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(url: str, body: dict | None = None, timeout: int = 10) -> tuple[int, bytes]:
    data = json.dumps(body or {}).encode()
    req  = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _wait_for_backend(max_wait: int = 30) -> bool:
    """Poll /health until it responds or timeout is reached."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            status, _ = _get(f"{BACKEND_URL}/health", timeout=2)
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


# ── checks ────────────────────────────────────────────────────────────────────

results: list[tuple[str, bool, str]] = []   # (label, ok, detail)


def check(label: str, ok: bool, detail: str = "") -> bool:
    results.append((label, ok, detail))
    icon = PASS if ok else FAIL
    msg  = f"  {icon}  {label}"
    if detail:
        msg += f"  [{detail}]"
    print(msg)
    return ok


def check_health() -> bool:
    status, body = _get(f"{BACKEND_URL}/health")
    if status != 200:
        return check("Backend /health", False, f"HTTP {status}")
    try:
        data = json.loads(body)
    except Exception:
        return check("Backend /health", False, "non-JSON response")
    ok = data.get("status") == "ok"
    return check("Backend /health", ok, json.dumps(data))


def check_neo4j() -> bool:
    """
    /api/sessions lists sessions from Neo4j.
    A 200 response (even an empty list) means Neo4j is up and connected.
    A 500 means the DB is unreachable.
    """
    status, body = _get(f"{BACKEND_URL}/api/sessions")
    if status == 200:
        try:
            data = json.loads(body)
            return check("Neo4j connection", isinstance(data, list),
                         f"{len(data)} session(s) found")
        except Exception:
            return check("Neo4j connection", False, "non-JSON from /api/sessions")
    return check("Neo4j connection", False, f"HTTP {status} from /api/sessions")


def check_demo_seed() -> bool:
    """
    Seed a fresh throw-away session with the CAP demo scenario.
    Verifies that the backend can build Claims from seed data and write them to Neo4j.
    Cleans up the session afterwards.
    """
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    url = f"{BACKEND_URL}/api/demo/seed/{session_id}?lang=en&scenario=cap"
    status, body = _post(url)
    if status != 200:
        return check("Demo seed (CAP)", False, f"HTTP {status}")
    try:
        data = json.loads(body)
    except Exception:
        return check("Demo seed (CAP)", False, "non-JSON response")

    n = data.get("claim_count", 0)
    ok = data.get("seeded") is True and n > 0
    detail = f"{n} claims" if ok else json.dumps(data)

    if ok:
        # Best-effort cleanup — don't fail the smoke test if this fails
        try:
            req = urllib.request.Request(
                f"{BACKEND_URL}/api/sessions/{session_id}", method="DELETE"
            )
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:
            pass

    return check("Demo seed (CAP)", ok, detail)


def check_graph_endpoint(session_id: str | None = None) -> bool:
    """
    Query an existing session's graph, or verify the graph endpoint is reachable.
    """
    if session_id:
        url = f"{BACKEND_URL}/api/graph/{session_id}"
        status, body = _get(url)
        if status == 200:
            try:
                data = json.loads(body)
                nodes = len(data.get("nodes", []))
                edges = len(data.get("edges", []))
                return check("Graph endpoint", True, f"{nodes} nodes, {edges} edges")
            except Exception:
                return check("Graph endpoint", False, "non-JSON response")
        return check("Graph endpoint", False, f"HTTP {status}")
    # No session to test — just verify the route exists (404 for unknown session is fine)
    status, _ = _get(f"{BACKEND_URL}/api/graph/smoke-probe-nosession")
    reachable = status in (200, 404, 422)
    return check("Graph endpoint reachable", reachable, f"HTTP {status}")


def check_frontend() -> bool:
    try:
        status, body = _get(FRONTEND_URL, timeout=5)
        ok = status == 200 and b"html" in body.lower()
        return check("Frontend reachable", ok, f"HTTP {status}")
    except Exception as e:
        return check("Frontend reachable", False, f"connection refused ({e})",)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="AleXiona smoke-test")
    parser.add_argument("--start-backend", action="store_true",
                        help="Start uvicorn automatically before running checks")
    parser.add_argument("--wait", type=int, default=30,
                        help="Seconds to wait for backend to come up (default: 30)")
    args = parser.parse_args()

    proc = None
    if args.start_backend:
        print("  Starting backend …")
        proc = subprocess.Popen(
            ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=os.path.join(os.path.dirname(__file__), "..", "backend"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    print(f"\nAleXiona Smoke-Test  →  {BACKEND_URL}\n")

    # Wait for backend to be up
    if not _wait_for_backend(args.wait):
        print(f"  {FAIL}  Backend did not respond within {args.wait}s")
        if proc:
            proc.terminate()
        return 1

    # Run checks
    check_health()
    neo4j_ok = check_neo4j()
    if neo4j_ok:
        check_demo_seed()
    else:
        results.append(("Demo seed (CAP)", None, "skipped — Neo4j unreachable"))  # type: ignore[arg-type]
        print(f"  {SKIP}  Demo seed (CAP)  [skipped — Neo4j unreachable]")
    check_graph_endpoint()
    check_frontend()

    # Summary
    passed  = sum(1 for _, ok, _ in results if ok is True)
    skipped = sum(1 for _, ok, _ in results if ok is None)
    failed  = sum(1 for _, ok, _ in results if ok is False)
    total   = len(results)

    print(f"\n  {passed}/{total} checks passed", end="")
    if skipped:
        print(f", {skipped} skipped", end="")
    if failed:
        print(f", {failed} FAILED", end="")
    print()

    if proc:
        proc.terminate()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

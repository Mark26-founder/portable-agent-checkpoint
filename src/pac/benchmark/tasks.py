"""
PAC S9 Benchmark Task Definitions.

Each task defines:
  - task_id: unique identifier
  - objective: the original task given to Agent A
  - agent_a_work: what Agent A completed before stopping
  - agent_a_files: files Agent A created/modified (with content)
  - agent_a_decisions: architectural decisions Agent A made
  - agent_a_constraints: constraints Agent A documented
  - stopping_point: description of where Agent A stopped
  - remaining: what is left for Agent B
  - next_action: the specific next action Agent B should take
  - correct_first_action: the productive action Agent B should take immediately
  - reconstruction_signals: things an agent must discover WITHOUT PAC

Each task is designed so reconstruction has meaningful cost:
  - Multiple files touched
  - At least one non-obvious architectural decision
  - At least one non-trivial remaining step
  - Stopping mid-implementation (not at a clean boundary)
"""

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class BenchmarkFile:
    """Represents a file created/modified by Agent A."""
    path: str          # relative path within workspace
    content: str       # file content


@dataclass
class BenchmarkTask:
    """A single benchmark task definition."""
    task_id: str
    objective: str
    agent_a_work: List[str]
    agent_a_files: List[BenchmarkFile]
    agent_a_decisions: List[Dict[str, str]]
    agent_a_constraints: List[str]
    stopping_point: str
    remaining: List[str]
    next_action: str
    correct_first_action: str
    reconstruction_signals: List[str]


# ---------------------------------------------------------------------------
# Task 1: Rate-Limiting Middleware
# ---------------------------------------------------------------------------
TASK_1 = BenchmarkTask(
    task_id="T1-rate-limiter",
    objective="Add per-user rate limiting to the REST API. Use a sliding window counter. "
              "Store state in memory (no Redis). Reject requests over 100/min with HTTP 429.",
    agent_a_work=[
        "Created src/middleware/rate_limiter.py with SlidingWindowCounter class",
        "Added _get_user_id() helper extracting user ID from Authorization header",
        "Registered middleware in src/app.py at line 42 (before route handlers)",
        "Created tests/test_rate_limiter.py with 4 passing unit tests",
        "Decided against Redis to keep the service stateless across restarts (intentional trade-off)",
    ],
    agent_a_files=[
        BenchmarkFile(
            path="src/middleware/__init__.py",
            content="",
        ),
        BenchmarkFile(
            path="src/middleware/rate_limiter.py",
            content='''\
"""Sliding window rate limiter middleware."""
import time
from collections import defaultdict, deque
from typing import Callable


class SlidingWindowCounter:
    """Thread-unsafe in-memory sliding window counter.

    Decision: intentionally NOT thread-safe.
    Reason: the application uses a single-threaded async event loop (asyncio).
    Do not add threading locks — it will break async performance.
    """

    def __init__(self, limit: int = 100, window_seconds: int = 60):
        self.limit = limit
        self.window = window_seconds
        self._requests: dict = defaultdict(deque)

    def is_allowed(self, user_id: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        q = self._requests[user_id]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


_limiter = SlidingWindowCounter()


def _get_user_id(request) -> str:
    """Extract user identity from Authorization header.

    Format expected: 'Bearer <user_id>:<token>'
    Falls back to remote_addr if header is absent.
    """
    auth = getattr(request, "headers", {}).get("Authorization", "")
    if auth.startswith("Bearer "):
        parts = auth[7:].split(":", 1)
        if parts:
            return parts[0]
    return getattr(request, "remote_addr", "anonymous")


def rate_limit_middleware(handler: Callable) -> Callable:
    """WSGI/async-compatible middleware wrapper.

    INCOMPLETE: HTTP 429 response body not yet written.
    Remaining: add JSON error body {"error": "rate_limit_exceeded", "retry_after": 60}
    """
    def wrapped(request, *args, **kwargs):
        uid = _get_user_id(request)
        if not _limiter.is_allowed(uid):
            # TODO: return proper HTTP 429 with JSON body — NOT DONE YET
            raise NotImplementedError("429 response body pending")
        return handler(request, *args, **kwargs)
    return wrapped
''',
        ),
        BenchmarkFile(
            path="src/app.py",
            content='''\
"""Main application entry point."""
from src.middleware.rate_limiter import rate_limit_middleware

# Route handlers registered below
# Middleware applied at line 42 per architectural decision:
# rate_limit_middleware wraps all authenticated routes only.

def create_app():
    routes = []
    # ... existing routes ...
    return routes
''',
        ),
        BenchmarkFile(
            path="tests/test_rate_limiter.py",
            content='''\
"""Unit tests for rate limiter middleware."""
import unittest
from src.middleware.rate_limiter import SlidingWindowCounter, _get_user_id


class TestSlidingWindowCounter(unittest.TestCase):

    def test_allows_requests_under_limit(self):
        c = SlidingWindowCounter(limit=5, window_seconds=60)
        for _ in range(5):
            self.assertTrue(c.is_allowed("user1"))

    def test_blocks_requests_over_limit(self):
        c = SlidingWindowCounter(limit=3, window_seconds=60)
        for _ in range(3):
            c.is_allowed("user1")
        self.assertFalse(c.is_allowed("user1"))

    def test_different_users_independent(self):
        c = SlidingWindowCounter(limit=2, window_seconds=60)
        c.is_allowed("user1")
        c.is_allowed("user1")
        self.assertTrue(c.is_allowed("user2"))

    def test_get_user_id_from_bearer(self):

        class FakeRequest:
            headers = {"Authorization": "Bearer alice:tok123"}
            remote_addr = "127.0.0.1"

        self.assertEqual(_get_user_id(FakeRequest()), "alice")


if __name__ == "__main__":
    unittest.main()
''',
        ),
    ],
    agent_a_decisions=[
        {"decision": "Use in-memory sliding window, not Redis",
         "reason": "Service is single-instance; Redis adds operational overhead not justified at this scale"},
        {"decision": "SlidingWindowCounter is intentionally not thread-safe",
         "reason": "Application uses asyncio single-threaded event loop; locks would degrade performance"},
        {"decision": "Rate limit applies only to authenticated routes",
         "reason": "Anonymous endpoints are public health checks; limiting them breaks load-balancer probes"},
    ],
    agent_a_constraints=[
        "Do not add Redis or any external state store",
        "Do not add threading locks to SlidingWindowCounter",
        "HTTP 429 response must include JSON body with retry_after field",
        "Middleware must wrap only authenticated routes, not health check endpoints",
    ],
    stopping_point="SlidingWindowCounter implemented and tested. rate_limit_middleware skeleton "
                   "exists but raises NotImplementedError — the HTTP 429 response body is not yet written. "
                   "Middleware is not yet wired into the actual route handlers in app.py.",
    remaining=[
        "Implement HTTP 429 JSON response body in rate_limit_middleware",
        "Wire middleware around authenticated route handlers in src/app.py",
        "Add integration test for the 429 response body format",
    ],
    next_action="Implement the HTTP 429 JSON error response body in "
                "src/middleware/rate_limiter.py::rate_limit_middleware, then wire into app.py",
    correct_first_action="Edit src/middleware/rate_limiter.py to replace the NotImplementedError "
                         "with a proper 429 HTTP response returning "
                         '{"error": "rate_limit_exceeded", "retry_after": 60}',
    reconstruction_signals=[
        "The NotImplementedError in rate_limit_middleware is the stopping point",
        "The thread-safety decision is embedded in a code comment only",
        "The constraint against Redis is not in any config file",
        "The JSON body format requirement is in a TODO comment only",
        "The 'authenticated routes only' constraint is a code comment in app.py",
    ],
)


# ---------------------------------------------------------------------------
# Task 2: CSV Export Feature
# ---------------------------------------------------------------------------
TASK_2 = BenchmarkTask(
    task_id="T2-csv-export",
    objective="Add a CSV export endpoint to the reporting module. "
              "Endpoint: GET /reports/export?format=csv. "
              "Export all rows from the ReportRecord model. "
              "Use Python csv module only — no pandas.",
    agent_a_work=[
        "Created src/reports/exporter.py with generate_csv() function",
        "Defined CSV column order: id, created_at, user_id, category, amount",
        "Added streaming response logic (yields rows, does not buffer full file)",
        "Created tests/test_exporter.py with 3 unit tests",
        "Decided to use RFC 4180 quoting (csv.QUOTE_ALL) for all fields",
    ],
    agent_a_files=[
        BenchmarkFile(
            path="src/reports/__init__.py",
            content="",
        ),
        BenchmarkFile(
            path="src/reports/exporter.py",
            content='''\
"""CSV exporter for ReportRecord model.

Column order is fixed by contract with the downstream data team:
  id, created_at, user_id, category, amount

Do NOT reorder columns. The downstream pipeline is column-position sensitive.

Quoting: csv.QUOTE_ALL (RFC 4180 compliant).
Reason: downstream parser does not handle unquoted commas in 'category' field.
"""
import csv
import io
from typing import Iterable


# Fixed column order — do not change without downstream team sign-off
CSV_COLUMNS = ["id", "created_at", "user_id", "category", "amount"]


def generate_csv(records: Iterable) -> str:
    """Generate CSV string from an iterable of ReportRecord-like objects.

    Returns full CSV as string (suitable for small exports).
    For large exports, use generate_csv_streaming() below — NOT YET IMPLEMENTED.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(CSV_COLUMNS)
    for rec in records:
        writer.writerow([
            getattr(rec, "id", ""),
            getattr(rec, "created_at", ""),
            getattr(rec, "user_id", ""),
            getattr(rec, "category", ""),
            getattr(rec, "amount", ""),
        ])
    return output.getvalue()


def generate_csv_streaming(records: Iterable):
    """Generator version for streaming HTTP responses.

    INCOMPLETE: header row yielded; row iteration not yet implemented.
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(CSV_COLUMNS)
    output.seek(0)
    yield output.read()
    output.truncate(0)
    output.seek(0)
    # TODO: iterate records and yield each row — NOT DONE
''',
        ),
        BenchmarkFile(
            path="tests/test_exporter.py",
            content='''\
"""Unit tests for CSV exporter."""
import unittest
from src.reports.exporter import generate_csv, CSV_COLUMNS


class FakeRecord:
    def __init__(self, id, created_at, user_id, category, amount):
        self.id = id
        self.created_at = created_at
        self.user_id = user_id
        self.category = category
        self.amount = amount


class TestGenerateCsv(unittest.TestCase):

    def test_header_row_matches_contract(self):
        csv_out = generate_csv([])
        first_line = csv_out.strip().splitlines()[0]
        for col in CSV_COLUMNS:
            self.assertIn(col, first_line)

    def test_data_row_written_correctly(self):
        rec = FakeRecord("1", "2026-01-01", "u42", "sales", "99.50")
        csv_out = generate_csv([rec])
        self.assertIn("u42", csv_out)
        self.assertIn("sales", csv_out)

    def test_quote_all_applied(self):
        rec = FakeRecord("2", "2026-01-02", "u99", "a,b,c", "0.00")
        csv_out = generate_csv([rec])
        # QUOTE_ALL means category with comma is safely quoted
        self.assertIn('"a,b,c"', csv_out)


if __name__ == "__main__":
    unittest.main()
''',
        ),
    ],
    agent_a_decisions=[
        {"decision": "Use csv.QUOTE_ALL for all fields",
         "reason": "Downstream parser fails on unquoted commas in the 'category' field"},
        {"decision": "Column order is id, created_at, user_id, category, amount",
         "reason": "Downstream data pipeline is column-position sensitive — order is a contract"},
        {"decision": "Use Python csv module only, not pandas",
         "reason": "Explicit requirement; keeps the service dependency-free"},
    ],
    agent_a_constraints=[
        "Do not use pandas",
        "Do not reorder CSV columns without downstream team sign-off",
        "Must use csv.QUOTE_ALL — downstream parser requirement",
        "Streaming response required for exports over 10k rows",
    ],
    stopping_point="generate_csv() is complete and tested. generate_csv_streaming() exists but "
                   "only yields the header row — the record iteration loop is not implemented. "
                   "No HTTP endpoint has been wired up yet.",
    remaining=[
        "Complete generate_csv_streaming() record iteration",
        "Wire GET /reports/export?format=csv endpoint into the router",
        "Add integration test for the HTTP endpoint",
    ],
    next_action="Complete generate_csv_streaming() in src/reports/exporter.py by implementing "
                "the record iteration loop, then wire the HTTP endpoint",
    correct_first_action="Edit src/reports/exporter.py to complete the generate_csv_streaming() "
                         "function by adding the record yield loop after the header",
    reconstruction_signals=[
        "The column order contract is in a code comment only",
        "The QUOTE_ALL requirement is in a code comment only",
        "The streaming vs non-streaming split is structural — two functions",
        "The HTTP endpoint wiring has not started — no route file to read",
        "The constraint about pandas is not in any requirements file",
    ],
)


# ---------------------------------------------------------------------------
# Task 3: Auth Token Refresh
# ---------------------------------------------------------------------------
TASK_3 = BenchmarkTask(
    task_id="T3-token-refresh",
    objective="Implement JWT refresh token rotation. "
              "When an access token expires, the client submits a refresh token. "
              "Issue a new access token (15 min TTL) and rotate the refresh token (7 day TTL). "
              "Invalidate the old refresh token immediately on use.",
    agent_a_work=[
        "Created src/auth/tokens.py with generate_access_token() and generate_refresh_token()",
        "Implemented RefreshTokenStore (in-memory dict) with consume() — one-time-use enforcement",
        "Chose HS256 signing, not RS256, to avoid key-management complexity in this service",
        "Created tests/test_tokens.py with 5 passing unit tests covering generation and consumption",
        "Stopped before implementing the /auth/refresh HTTP endpoint and before adding token expiry validation",
    ],
    agent_a_files=[
        BenchmarkFile(
            path="src/auth/__init__.py",
            content="",
        ),
        BenchmarkFile(
            path="src/auth/tokens.py",
            content='''\
"""JWT token generation and refresh token rotation.

Algorithm: HS256 (symmetric).
Decision: NOT RS256.
Reason: This service owns both token issuance and validation. Asymmetric keys
add operational complexity (key rotation, JWKS endpoint) with no benefit
for a single-service deployment. If this becomes a multi-service architecture,
revisit RS256 at that time.

Do NOT change the algorithm to RS256 without the architecture discussion.

TTLs:
  access_token:  15 minutes
  refresh_token: 7 days
"""
import hmac
import hashlib
import json
import time
import secrets
from typing import Optional


SECRET_KEY = "PLACEHOLDER_SECRET"  # replaced by environment variable in production
ACCESS_TTL = 15 * 60       # 15 minutes in seconds
REFRESH_TTL = 7 * 24 * 3600  # 7 days in seconds


def _b64url_encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_access_token(user_id: str, secret: str = SECRET_KEY) -> str:
    """Generate a minimal HS256 JWT access token."""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub": user_id,
        "exp": int(time.time()) + ACCESS_TTL,
        "iat": int(time.time()),
    }).encode())
    signing_input = f"{header}.{payload}"
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(sig)}"


def generate_refresh_token() -> str:
    """Generate a cryptographically random refresh token (opaque, not JWT)."""
    return secrets.token_urlsafe(32)


class RefreshTokenStore:
    """In-memory one-time-use refresh token store.

    Tokens are consumed on use — the old token is immediately invalidated
    and a new token is issued. This is refresh token rotation.

    IMPORTANT: This is NOT persistent across restarts.
    Reason: MVP scope. Production deployment must replace this with
    a persistent store (Redis or database) before going to production.
    """

    def __init__(self):
        self._store: dict = {}  # token -> user_id

    def register(self, token: str, user_id: str) -> None:
        self._store[token] = user_id

    def consume(self, token: str) -> Optional[str]:
        """Consume a refresh token. Returns user_id if valid, None if invalid/already used."""
        return self._store.pop(token, None)

    def count(self) -> int:
        return len(self._store)


# INCOMPLETE: /auth/refresh endpoint not yet implemented.
# Next step: create src/auth/routes.py with POST /auth/refresh handler.
# The handler must:
#   1. Accept {"refresh_token": "<token>"}
#   2. Call store.consume(token) — returns user_id or None
#   3. If None: return 401 {"error": "invalid_or_expired_refresh_token"}
#   4. Generate new access_token + new refresh_token
#   5. Call store.register(new_refresh_token, user_id)
#   6. Return {"access_token": ..., "refresh_token": ..., "expires_in": 900}

# Token expiry validation on access_token is also NOT yet implemented.
''',
        ),
        BenchmarkFile(
            path="tests/test_tokens.py",
            content='''\
"""Unit tests for token generation and rotation."""
import unittest
from src.auth.tokens import (
    generate_access_token, generate_refresh_token, RefreshTokenStore
)


class TestAccessToken(unittest.TestCase):

    def test_access_token_is_three_part_jwt(self):
        tok = generate_access_token("user1")
        parts = tok.split(".")
        self.assertEqual(len(parts), 3)

    def test_different_users_get_different_tokens(self):
        t1 = generate_access_token("u1")
        t2 = generate_access_token("u2")
        self.assertNotEqual(t1, t2)


class TestRefreshTokenStore(unittest.TestCase):

    def test_register_and_consume(self):
        store = RefreshTokenStore()
        rt = generate_refresh_token()
        store.register(rt, "user42")
        uid = store.consume(rt)
        self.assertEqual(uid, "user42")

    def test_token_consumed_only_once(self):
        store = RefreshTokenStore()
        rt = generate_refresh_token()
        store.register(rt, "user42")
        store.consume(rt)
        self.assertIsNone(store.consume(rt))

    def test_unknown_token_returns_none(self):
        store = RefreshTokenStore()
        self.assertIsNone(store.consume("invalid_token"))


if __name__ == "__main__":
    unittest.main()
''',
        ),
    ],
    agent_a_decisions=[
        {"decision": "Use HS256, not RS256",
         "reason": "Single-service deployment; asymmetric keys add key-management overhead with no benefit here"},
        {"decision": "Refresh token is opaque (not JWT)",
         "reason": "Refresh tokens don't need to be inspected by the client; opacity prevents token forgery attempts"},
        {"decision": "RefreshTokenStore is in-memory (not persistent)",
         "reason": "MVP scope; must be replaced with Redis/DB before production"},
    ],
    agent_a_constraints=[
        "Do not switch to RS256 without architecture discussion",
        "Refresh tokens must be one-time-use (rotation enforced)",
        "Access token TTL: 15 minutes; Refresh token TTL: 7 days",
        "RefreshTokenStore must be replaced with persistent store before production",
        "/auth/refresh must return 401 for invalid/consumed tokens (not 400)",
    ],
    stopping_point="Token generation and RefreshTokenStore implemented and tested. "
                   "The /auth/refresh HTTP endpoint and access token expiry validation "
                   "have not been implemented. A detailed TODO is embedded in tokens.py.",
    remaining=[
        "Create src/auth/routes.py with POST /auth/refresh handler",
        "Implement access token expiry validation",
        "Add integration test for the refresh endpoint",
    ],
    next_action="Create src/auth/routes.py implementing POST /auth/refresh "
                "following the specification in the TODO comment in src/auth/tokens.py",
    correct_first_action="Create src/auth/routes.py with the POST /auth/refresh handler "
                         "that calls store.consume(), issues new tokens, and returns the correct JSON",
    reconstruction_signals=[
        "The HS256 vs RS256 decision is in a code comment only",
        "The one-time-use enforcement requirement is in comments and tests",
        "The TODO for /auth/refresh is in tokens.py — no routes.py file exists yet",
        "The 401 vs 400 distinction is in a comment only",
        "The persistence requirement is a comment warning only",
    ],
)

ALL_TASKS: List[BenchmarkTask] = [TASK_1, TASK_2, TASK_3]

"""
ReproForge FastAPI — TOON + Gemini 3.5 Flash -> 2.5 Pro + Supabase Cloud + SlowAPI Rate Limiting
Real only: no mocks, no JSON traces, real GitHub, pinned SHA, human_verified
"""
from __future__ import annotations
import os
import time
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from dotenv import load_dotenv

# Load .env.local if exists (project root or backend)
for p in [".env.local", "../.env.local", "../../.env.local"]:
    if os.path.exists(p):
        load_dotenv(p)
# also load ../.env.local from backend dir
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env.local"))

from app.api.routes import router as investigations_router
from app.api.github_api import router as github_router

limiter = Limiter(key_func=get_remote_address, storage_uri="memory://", default_limits=["60/minute"])

app = FastAPI(
    title="ReproForge API",
    description="Failure-reproduction lab for AI agents — real GitHub + TOON + Gemini + Supabase Cloud + rate limiting. No mock or local persistence fallback.",
    version="1.0.0",
)
app.state.limiter = limiter

# Rate limit exceeded handler
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit exceeded", "detail": str(exc.detail), "retry_after": "60"},
        headers={"Retry-After": "60", "X-RateLimit-Limit": "10", "X-RateLimit-Remaining": "0"},
    )

app.add_middleware(SlowAPIMiddleware)

# CORS for Next.js 15
# Apply rate limiting per endpoint via decorator in routes, but also global limits
# We'll add explicit limiters for health/investigations via routes that will check limiter

@app.get("/healthz")
@limiter.limit("60/minute")
async def healthz(request: Request):
    from app.providers.gemini import is_configured as gemini_is_configured
    from app.services.supabase import health
    supa = health()
    return {
        "status": "ok",
        "service": "reproforge",
        "supabase_mode": supa.get("mode", "supabase"),
        "supabase_connected": supa.get("connected", False),
        "model_primary": os.getenv("GEMINI_MODEL", os.getenv("GEMINI_FLASH_MODEL", "gemini-3.5-flash")),
        "model_fallback": os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash"),
        "model_chain": [
            os.getenv("GEMINI_MODEL", os.getenv("GEMINI_FLASH_MODEL", "gemini-3.5-flash")),
            os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash"),
        ],
        "gemini_configured": gemini_is_configured(),
        "toon": "enabled (TOON only, no JSON)",
        "rate_limiting": "enabled",
        "real_traces": "data/real_traces/*.toon (pinned SHAs, human_verified)",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

# Include router with rate-limited endpoints
# We wrap endpoints with limiter manually here to enforce per-route limits
# Since routes.py doesn't have limiter decorator directly (to keep testability), we inject limits via middleware?
# Instead, we will monkey-patch router endpoints with limiter after inclusion.

app.include_router(investigations_router, prefix="/api")
app.include_router(github_router, prefix="/api")

# Add limiter decorators to specific paths by re-registering wrappers?
# Approach: Use app.middleware to check path and apply custom limits via in-memory counter
# Simpler: Apply limits via dependency in routes? For MVP, we apply global 60/min and document 10/min for LLM endpoints.
# To enforce stricter, we add a custom middleware:

from collections import defaultdict
_request_log: dict[str, list[float]] = defaultdict(list)

LIMITS = {
    "/api/investigations": 60,
    "/api/investigations/analyze": 10,
    "/api/investigations/reproduce": 10,
    "/api/investigations/stress": 10,
    "/api/investigations/compare": 10,
    "/api/investigations/trace": 20,
}

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # simple sliding window per IP + path
    # only for POST to heavy endpoints
    path = request.url.path
    # determine limit
    limit = 60  # default
    if path.endswith("/analyze") or path.endswith("/reproduce") or path.endswith("/stress") or path.endswith("/compare") or path.endswith("/github/task/generate") or path == "/api/runs":
        limit = 10
    elif path.endswith("/trace"):
        limit = 20
    elif path.startswith("/api/investigations"):
        limit = 60
    else:
        limit = 60
    key = f"{get_remote_address(request)}:{path}:{limit}"
    now = time.time()
    window = 60
    # clean old
    _request_log[key] = [t for t in _request_log[key] if now - t < window]
    if len(_request_log[key]) >= limit:
        return JSONResponse(
            status_code=429,
            content={"error": "Too Many Requests", "limit": limit, "retry_after": 60 - int(now - _request_log[key][0])},
            headers={
                "Retry-After": str(60 - int(now - _request_log[key][0])),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(_request_log[key][0] + 60)),
            },
        )
    _request_log[key].append(now)
    response: Response = await call_next(request)
    # add headers
    remaining = max(0, limit - len(_request_log[key]))
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(int(now + 60))
    return response

# Add CORS after the custom middleware so it is the outermost layer and also
# attaches headers to 4xx/5xx responses (including Supabase setup failures).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)

@app.get("/")
async def root():
    return {
        "name": "ReproForge",
        "tagline": "Turn agent failures into reproducible tests.",
        "version": "1.0.0",
        "stack": "Frontend Next.js 15 + TypeScript + Tailwind + shadcn/ui | Backend Python + FastAPI + Pydantic + Supabase Cloud | AI Gemini 3.5 Flash (primary) -> 2.5 Pro (fallback) | Data TOON | Real GitHub pinned SHA | Eval deterministic runner",
        "data_flow": "GitHub account aviralsrivastava851 -> Fetch public repos -> User selects repository -> Fetch pinned commit SHA -> ReproForge Task Generator (Gemini 3.5 Flash grounded in README/package.json/routes) -> Live Agent (Gemini 3.5 Flash + real github_code_search/github_get_file/list_files) -> TOON TRACE RECORDER -> ReproForge Failure Analysis (3.5 Flash / difficult->2.5 Pro) -> Minimal Reproducer -> Stress -> Baseline vs Candidate -> Evidence Report -> Human Review",
        "real_traces": "data/real_traces/*.toon + datasets/github/case_*/task.toon + trace.toon (TOON only, no JSON, human_verified, pinned SHA)",
        "endpoints": [
            "GET /api/github/repos/{username}  # list_repositories() real",
            "POST /api/github/task/generate   # Gemini 3.5 Flash grounded task",
            "POST /api/runs                   # Live Agent (real GitHub tools, SSE)",
            "GET /api/runs/{run_id}/events    # SSE live trace",
            "GET /api/runs/{run_id}",
            "POST /api/investigations",
            "POST /api/investigations/{id}/trace",
            "POST /api/investigations/{id}/analyze  # Gemini 3.5 Flash / difficult 2.5 Pro",
            "POST /api/investigations/{id}/reproduce",
            "POST /api/investigations/{id}/stress",
            "POST /api/investigations/{id}/compare",
            "GET /healthz",
        ],
        "toon": "Content-Type: application/toon (no JSON for saved traces)",
        "env": ".env.local with GEMINI_API_KEY + SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY + optional GITHUB_TOKEN",
    }

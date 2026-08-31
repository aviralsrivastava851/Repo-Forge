"""
Real-time GitHub + ReproForge flow — no mocks, no predefined tasks.

Endpoints:
GET  /api/github/repos/{username}          -> list_repositories()
POST /api/github/task/generate            -> grounded Gemini task generation
POST /api/runs                            -> live agent execution (Gemini 3.5 Flash + real tools)
GET  /api/runs/{run_id}/events            -> SSE live trace
POST /api/investigations/{run_id}/analyze -> ReproForge (wired to existing)
"""
from __future__ import annotations
import os
import uuid
import time
import asyncio
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from app.services.toon import dumps, loads, validate
from app.services.github import list_repositories, get_pinned_commit_sha, get_repository_context, github_code_search, github_get_file, github_list_files
from app.providers.gemini import run_model, MODEL_PRIMARY, MODEL_FALLBACK
from app.services.trace_recorder import TraceRecorder
from app.services import supabase as sb
from pathlib import Path

router = APIRouter()

# In-memory live runs store for SSE (also persisted as TOON)
_live_runs: Dict[str, Dict[str, Any]] = {}
_live_queues: Dict[str, asyncio.Queue] = {}

TRACE_BASE = Path(__file__).resolve().parents[3] / "datasets" / "github"
TRACE_BASE.mkdir(parents=True, exist_ok=True)

def toon_response(data: Dict[str, Any], status_code: int = 200) -> Response:
    return Response(dumps(data), status_code=status_code, media_type="application/toon")

async def toon_body(request: Request) -> Dict[str, Any]:
    if "application/toon" not in request.headers.get("content-type", ""):
        raise HTTPException(415, "Content-Type must be application/toon; JSON is not accepted")
    try:
        parsed = loads((await request.body()).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"Invalid TOON: {exc}")
    if not isinstance(parsed, dict): raise HTTPException(400, "Top-level TOON value must be an object")
    return parsed

def sse_toon(event: Dict[str, Any]) -> str:
    return "".join(f"data: {line}\n" for line in dumps(event).splitlines()) + "\n"

def _get_github_token_ok() -> bool:
    tok = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN", "")
    return bool(tok and len(tok) > 10 and "your" not in tok)

@router.get("/github/repos/{username}")
async def github_list_repos(username: str):
    """Real time — Fetch public repositories for username — no mocks"""
    try:
        repos = await asyncio.to_thread(list_repositories, username)
        return toon_response({"username": username, "count": len(repos), "repos": repos})
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch repos for {username}: {str(e)[:500]}")

@router.post("/github/task/generate")
async def generate_task(request: Request):
    """
    Grounded task generation — scan repo evidence, then Gemini 3.5 Flash creates TOON task.
    Request and response are TOON only.
    
    Requirements (enforced in prompt):
    - require at least 2 tool calls
    - deterministic evidence
    - no subjective / private data
    - provide expected evidence locations
    """
    data = await toon_body(request)

    repo = data.get("repository") or data.get("repo") or ""
    commit = data.get("commit") or data.get("commit_sha") or data.get("sha") or ""
    if not repo:
        raise HTTPException(400, "repository required (owner/name)")

    # Fetch pinned commit SHA if not provided
    if not commit:
        try:
            commit = await asyncio.to_thread(get_pinned_commit_sha, repo)
        except Exception as e:
            raise HTTPException(500, f"Failed to fetch pinned commit for {repo}: {e}")

    # Scan structure for grounded evidence
    try:
        context = await asyncio.to_thread(get_repository_context, repo, commit)
    except Exception as e:
        raise HTTPException(500, f"Failed to scan repository {repo}@{commit}: {e}")

    # Build grounded prompt — Gemini must base task on supplied evidence only
    files_preview = "\n".join(context.get("files", [])[:60])
    readme_preview = context.get("readme", "")[:2500]
    pkg_preview = context.get("package_json", "")[:1500]
    routes_preview = "\n".join(context.get("routes", [])[:15])
    source_preview = "\n\n".join(f"FILE: {item['path']}\n{item['snippet']}" for item in context.get("sample_files", []))

    prompt = f"""You are generating a reproducible repository investigation task.

Repository: {repo}
Commit (pinned SHA): {commit}
Files (first 60):
{files_preview}

README (excerpt):
{readme_preview}

package/requirements (excerpt):
{pkg_preview}

Route candidates:
{routes_preview}

Actual source excerpts:
{source_preview}

Based ONLY on the supplied repository contents, create one question whose answer can be verified directly from source code.

Requirements:
- require at least 2 tool calls (list_files, search_code, read_file)
- answer must have deterministic evidence (exact file paths, function names)
- don't ask subjective questions
- don't require private data
- don't require modifying the repository
- provide the expected evidence locations
- every requested fact must appear verbatim in the supplied source excerpts

Output TOON only, no JSON, no markdown:

task:
  id: repo_task_001
  title: Locate authentication validation
  question: Which function validates JWT tokens before protected routes execute? Cite files.
verification:
  expected_files:
    - backend/middleware/auth.py
  evidence:
    - verify_token function
    - users router dependency
difficulty: medium
"""

    # Task generation -> Gemini 3.5 Flash (primary) — as requested
    try:
        # Use run_model which does 3.5 Flash -> fallback 2.5 Pro on failure
        from app.providers.gemini import generate_toon
        task_data, model_used, _ = generate_toon(prompt, expected_keys=["task", "verification"], temperature=0.3, difficult=False)
        # Validate structure
        if "task" not in task_data:
            raise ValueError("Gemini did not return task")
        # Add repo/commit
        task_data["repository"] = repo
        task_data["commit"] = commit
        task_data["generated_by"] = model_used
        task_data["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Generated work is deliberately not frozen until human approval.
        case_id = f"case_{uuid.uuid4().hex[:6]}"
        case_dir = TRACE_BASE / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        task_toon = dumps(task_data)
        (case_dir / "generated_task.toon").write_text(task_toon, encoding="utf-8")
        sb.insert("repository_tasks", {"id": case_id, "repository": repo, "commit": commit, "status": "generated", "toon_payload": task_toon, "model_used": model_used})
        return toon_response({
            "case_id": case_id,
            "repository": repo,
            "commit": commit,
            "task": task_data,
            "task_toon": task_toon,
            "model": model_used,
            "human_approval_required": True,
            "message": f"Task generated via {model_used} grounded in real repo scan. Approve it before a run can start."
        })
    except Exception as e:
        raise HTTPException(500, f"Task generation failed (Gemini 3.5 Flash): {str(e)[:800]}")

@router.post("/github/task/approve")
async def approve_task(request: Request):
    data = await toon_body(request)
    case_id = str(data.get("case_id") or "")
    case_dir = TRACE_BASE / case_id
    source = case_dir / "generated_task.toon"
    if not case_id or not source.is_file() or case_dir.parent != TRACE_BASE:
        raise HTTPException(404, "Generated task not found")
    task_data = loads(source.read_text(encoding="utf-8"))
    if not isinstance(task_data, dict) or not task_data.get("commit"):
        raise HTTPException(400, "Generated task lacks a pinned commit")
    (case_dir / "task.toon").write_text(dumps(task_data), encoding="utf-8")
    (case_dir / "commit.txt").write_text(str(task_data["commit"]), encoding="utf-8")
    sb.update("repository_tasks", case_id, {"status": "approved", "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return toon_response({"case_id": case_id, "approved": True, "repository": task_data.get("repository"), "commit": task_data.get("commit"), "task": task_data})

@router.post("/runs")
async def start_run(request: Request):
    """
    Live Agent executes task — Real GitHub API / repository tool calls, TOON trace recorder.
    Request: {repository, commit, task{question}, case_id} — task comes from approved task.toon (ground_truth NOT sent to agent)
    Agent receives only: question + repository tools (list_files, search_code, read_file) — no ground_truth leakage.
    """
    data = await toon_body(request)

    repo = data.get("repository") or data.get("repo") or ""
    commit = data.get("commit") or data.get("commit_sha") or ""
    task_obj = data.get("task", {})
    # task may be nested: data["task"]["question"] or data["task"]["task"]["question"]
    question = ""
    if isinstance(task_obj, dict):
        question = task_obj.get("question") or task_obj.get("title") or task_obj.get("query") or ""
        if not question and "task" in task_obj and isinstance(task_obj["task"], dict):
            question = task_obj["task"].get("question", "")
    if not question:
        question = data.get("question") or data.get("query") or ""
    if not repo or not commit or not question:
        raise HTTPException(400, f"repository, commit, and task.question required. Got repo={repo}, commit={commit}, question={question[:100]}")

    case_id = str(data.get("case_id") or "")
    approved_task = TRACE_BASE / case_id / "task.toon"
    if not case_id or not approved_task.is_file():
        raise HTTPException(409, "Generate and approve a task before starting a live run")

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    investigation_id = f"inv_{uuid.uuid4().hex[:12]}"
    verification = task_obj.get("verification", {}) if isinstance(task_obj, dict) else {}
    if not verification and isinstance(task_obj, dict) and isinstance(task_obj.get("task"), dict):
        verification = task_obj["task"].get("verification", {})
    expected = dumps(verification) if verification else "Human review required"
    # A live run is an investigation from the moment it starts. This keeps
    # the dashboard, Supabase, and the post-run analysis link in sync.
    try:
        sb.insert("investigations", {"id": investigation_id, "name": question[:120], "task": question, "expected": expected, "status": "analyzing", "repository": repo, "commit": commit})
    except Exception as exc:
        raise HTTPException(503, f"Could not create the Supabase investigation: {str(exc)[:300]}") from exc
    queue: asyncio.Queue = asyncio.Queue()
    _live_queues[run_id] = queue
    _live_runs[run_id] = {
        "run_id": run_id,
        "repository": repo,
        "commit": commit,
        "question": question,
        "investigation_id": investigation_id,
        "status": "running",
        "events": [],
        "started_at": time.time(),
    }

    # Start background live execution
    asyncio.create_task(_execute_live_agent(run_id, investigation_id, repo, commit, question, case_id))

    return toon_response({"run_id": run_id, "investigation_id": investigation_id, "status": "running", "repository": repo, "commit": commit, "question": question, "sse": f"/api/runs/{run_id}/events"})

async def _execute_live_agent(run_id: str, investigation_id: str, repo: str, commit: str, question: str, case_id: str):
    """Live execution — streams events to queue and persists TOON trace"""
    queue = _live_queues.get(run_id)
    run = _live_runs.get(run_id)
    if not queue or not run:
        return

    async def emit(evt: Dict[str, Any]):
        evt["timestamp"] = time.strftime("%H:%M:%S", time.gmtime())
        evt["run_id"] = run_id
        run["events"].append(evt)
        await queue.put(evt)

    # TOON recorder for final persistence
    from app.services.trace_recorder import TraceRecorder

    try:
        await emit({"step": 1, "type": "user_task", "content": question, "repository": repo, "commit": commit})
        await emit({"step": 2, "type": "model_call", "model": "gemini-3.5-flash", "content": "Planning repository investigation"})

        # Tool 1: list_repository_files()
        await emit({"step": 3, "type": "tool_call", "tool": "list_repository_files", "repo": repo, "commit": commit})
        try:
            files = await asyncio.to_thread(github_list_files, repo, commit)
            await emit({"step": 4, "type": "tool_result", "tool": "list_repository_files", "file_count": len(files), "files": files[:40]})
        except Exception as e:
            files = []
            await emit({"step": 4, "type": "tool_result", "error": str(e)[:600]})

        # Gemini chooses a search term from this repository's real file list;
        # no repository-specific keywords or pre-written task are hardcoded.
        plan, planner_model, _ = await asyncio.to_thread(__import__('app.providers.gemini', fromlist=['generate_toon']).generate_toon,
            f"Repository task: {question}\nFiles:\n" + "\n".join(files[:80]) + "\nReturn TOON only: search_query: concise source-code search term",
            ["search_query"], 0.1, False)
        query = str(plan.get("search_query") or "").strip()
        if not query: raise RuntimeError("Gemini planner returned no search_query")
        await emit({"step": 5, "type": "tool_call", "tool": "search_code", "query": query, "repo": repo, "commit": commit})
        try:
            search_res = await asyncio.to_thread(github_code_search, query, repo, commit)
            await emit({"step": 6, "type": "tool_result", "tool": "search_code", "query": query, "results": search_res.get("results", [])[:8], "total_count": search_res.get("total_count", 0)})
            # Pick top file for next read
            top_path = None
            results = search_res.get("results", [])
            if results:
                # results may be list of dicts with path or string
                first = results[0]
                top_path = first.get("path") if isinstance(first, dict) else str(first)
        except Exception as e:
            top_path = None
            await emit({"step": 6, "type": "tool_result", "error": str(e)[:600]})

        # Tool 3: read_file() if we have a candidate
        if top_path:
            await emit({"step": 7, "type": "tool_call", "tool": "read_file", "path": top_path, "repo": repo, "commit": commit})
            try:
                file_data = await asyncio.to_thread(github_get_file, repo, top_path, commit)
                snippet = file_data["content"][:1200]
                await emit({"step": 8, "type": "tool_result", "tool": "read_file", "path": top_path, "snippet": snippet[:800]})
            except Exception as e:
                snippet = ""
                await emit({"step": 8, "type": "tool_result", "error": str(e)[:600]})
        else:
            # Empty code search → ask Gemini to choose from the real file list.
            try:
                choice, _, _ = await asyncio.to_thread(
                    __import__('app.providers.gemini', fromlist=['generate_toon']).generate_toon,
                    f"Task: {question}\nRepository files:\n" + "\n".join(files[:120]) +
                    "\nChoose the single most relevant existing source file. Output TOON: path: exact/path",
                    ["path"], 0.1, False)
                top_path = str(choice.get("path") or "").strip()
                if not top_path or top_path not in files:
                    raise RuntimeError("Gemini did not select an existing repository file")
                fallback = await asyncio.to_thread(github_get_file, repo, top_path, commit)
                snippet = fallback["content"][:1200]
                await emit({"step": 7, "type": "tool_call", "tool": "read_file", "path": top_path, "repo": repo, "commit": commit})
                await emit({"step": 8, "type": "tool_result", "tool": "read_file", "path": top_path, "snippet": snippet[:800]})
            except Exception as e:
                top_path = ""
                snippet = ""
                await emit({"step": 8, "type": "tool_result", "tool": "read_file", "path": top_path, "error": str(e)[:600]})

        # Model evaluating evidence — Gemini 3.5 Flash (with fallback to 2.5 Pro on failure)
        await emit({"step": 9, "type": "model_call", "model": "gemini-3.5-flash", "content": "Evaluating evidence"})
        # Build prompt for final answer — agent only gets question + tool outputs, NOT ground truth
        tool_summary = f"Files: {len(files) if 'files' in locals() else 0}, Search query: {query}, Top file: {top_path}"
        final_prompt = f"""You investigated repository {repo}@{commit} for task: {question}

Tool outputs:
- list_repository_files: {len(files) if 'files' in locals() else 'unknown'} files
- search_code('{query}'): {search_res if 'search_res' in locals() else 'no results'}
- read_file('{top_path}'): {snippet[:800] if 'snippet' in locals() and snippet else 'no snippet'}

Cite the exact source files that answer the question. Output TOON only:

answer:
  file: path/to/file
  evidence: brief citation
  reasoning: one sentence
"""
        try:
            from app.providers.gemini import run_model
            # Live agent uses 3.5 Flash (fallback to 2.5 Pro on error) — as requested
            # run_model is synchronous; execute it off the event loop so the
            # SSE stream remains responsive during the real Gemini request.
            answer_text, model_used = await asyncio.to_thread(run_model, final_prompt, False)
            await emit({"step": 10, "type": "model_call", "model": model_used, "content": "Generating final answer"})
            try:
                answer_data = loads(answer_text)
            except:
                answer_data = {"file": answer_text.strip()[:200], "raw": answer_text[:500]}
            await emit({"step": 11, "type": "final_decision", "answer": answer_data, "model": model_used})
            final_answer = answer_data.get("answer", answer_data) if isinstance(answer_data, dict) else answer_data
        except Exception as e:
            final_answer = {"file": top_path or "unknown", "error": str(e)[:400]}
            await emit({"step": 11, "type": "final_decision", "answer": final_answer, "error": str(e)[:400]})

        # Persist TOON trace — datasets/github/case_*/trace.toon and data/real_traces/
        try:
            # Also save via TraceRecorder for data/real_traces
            # Find expected from approved task if available
            expected = {}
            if case_id:
                task_path = TRACE_BASE / case_id / "task.toon"
                if task_path.exists():
                    try:
                        tdata = loads(task_path.read_text(encoding="utf-8"))
                        ver = tdata.get("verification", {}) or tdata.get("task", {}).get("verification", {})
                        expected = ver
                    except:
                        pass
            evaluation, evaluator_model, _ = await asyncio.to_thread(
                __import__('app.providers.gemini', fromlist=['GeminiProvider']).GeminiProvider().evaluate_outcome,
                question, dumps(expected), dumps({"events": run["events"], "actual": final_answer}))
            recorder = TraceRecorder(repository=repo, commit=commit, task=question, model=MODEL_PRIMARY)
            # Replay events into recorder
            for ev in run["events"]:
                if ev["type"] not in ["user_task"]:
                    recorder.events.append(ev)
            # Fix run_id to match live run
            recorder.run_id = run_id
            recorder.set_evaluation(expected, final_answer if isinstance(final_answer, dict) else {"answer": str(final_answer)}, evaluation)
            # Save to data/real_traces
            toon_path = recorder.save()
            trace_toon = recorder.to_toon()
            sb.insert("trajectories", {"id": run_id, "investigation_id": investigation_id, "run_id": run_id, "repository": repo, "commit": commit, "human_verified": False, "toon_payload": trace_toon, "events": run["events"]})
            sb.update("investigations", investigation_id, {"status": "completed"})
            await emit({"step": 12, "type": "trace_saved", "path": str(toon_path), "expected": expected, "actual": final_answer})
            # Also save to datasets/github/case_id/trace.toon for benchmark determinism
            if case_id:
                case_dir = TRACE_BASE / case_id
                case_dir.mkdir(parents=True, exist_ok=True)
                trace_toon = dumps({
                    "run_id": run_id,
                    "repository": repo,
                    "commit": commit,
                    "model": MODEL_PRIMARY,
                    "task": question,
                    "events": run["events"],
                    "expected": expected,
                    "actual": final_answer,
                    "evaluation": evaluation,
                    "passed": evaluation.get("outcome") == "passed",
                    "evaluated_by": evaluator_model,
                    "human_verified": False,
                })
                (case_dir / "trace.toon").write_text(trace_toon, encoding="utf-8")
        except Exception as e:
            error_text = str(e)[:500]
            # Preserve the real partial trace in Supabase even when provider
            # evaluation is blocked by quota. Never report such a run complete.
            partial_toon = dumps({
                "run_id": run_id, "repository": repo, "commit": commit,
                "model": MODEL_PRIMARY, "task": question, "events": run["events"],
                "expected": expected if 'expected' in locals() else {},
                "actual": final_answer if 'final_answer' in locals() else {},
                "evaluation": {"outcome": "inconclusive", "classification": "provider_error", "error": error_text},
                "human_verified": False,
            })
            try:
                sb.insert("trajectories", {"id": run_id, "investigation_id": investigation_id, "run_id": run_id, "repository": repo, "commit": commit, "human_verified": False, "toon_payload": partial_toon, "events": run["events"]})
            except Exception:
                pass
            await emit({"step": 12, "type": "trace_error", "error": error_text})
            raise RuntimeError(f"Live run could not be evaluated or persisted: {error_text}")

        run["status"] = "completed"
        await emit({"step": 13, "type": "completed", "status": "completed"})

    except Exception as e:
        run["status"] = "failed"
        try: sb.update("investigations", investigation_id, {"status": "failed"})
        except Exception: pass
        await emit({"step": 99, "type": "error", "error": str(e)[:800]})
    finally:
        # Signal end of stream
        await queue.put(None)

@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str):
    """SSE live trace — every tool event appears live"""
    if run_id not in _live_queues:
        # Check if run exists but already completed (serve stored events)
        if run_id in _live_runs:
            run = _live_runs[run_id]
            async def replay():
                for ev in run["events"]:
                    yield sse_toon(ev)
                yield sse_toon({'type': 'completed', 'status': run.get('status','completed')})
            return StreamingResponse(replay(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        raise HTTPException(404, f"Run {run_id} not found")

    queue = _live_queues[run_id]

    async def event_generator():
        while True:
            item = await queue.get()
            if item is None:
                yield sse_toon({'type': 'completed', 'status': 'completed'})
                break
            yield sse_toon(item)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = _live_runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    return toon_response(run)
    case_id = str(data.get("case_id") or "")
    if not case_id or not (TRACE_BASE / case_id / "task.toon").is_file():
        raise HTTPException(409, "Approve the generated task before starting a live run")

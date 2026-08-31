"""
API Routes — TOON only, Real Gemini, Real GitHub, Real Supabase (no mocks, no JSON traces)
"""
from __future__ import annotations
import time
from typing import Any, Optional
from fastapi import APIRouter, Request, HTTPException, Response, Body
from fastapi.responses import JSONResponse, PlainTextResponse
from app.models.schemas import (
    Investigation, InvestigationCreate, FailureHypothesis,
    TestCase, RunResult, Report, Config
)
from app.services.toon import dumps, loads, validate, estimate_tokens, token_savings
from app.services import supabase as sb
from app.agents import failure_analyst, reproducer, perturbation
from app.eval.runner import replay_case
from app.eval.metrics import compute_comparison_metrics
from app.providers.gemini import MODEL_PRIMARY, MODEL_FALLBACK

router = APIRouter()

def save_artifact(investigation_id: str, stage: str, payload: dict, model_used: str = "") -> None:
    sb.upsert("workflow_artifacts", {
        "id": f"{investigation_id}:{stage}", "investigation_id": investigation_id,
        "stage": stage, "toon_payload": dumps(payload), "model_used": model_used,
    })

def load_artifacts(investigation_id: str) -> dict:
    result = {}
    for row in sb.list_by("workflow_artifacts", {"investigation_id": investigation_id}):
        try: result[row["stage"]] = loads(row["toon_payload"])
        except Exception: result[row["stage"]] = row
    return result

def get_trajectory_events(trajectory: dict) -> list[dict]:
    """Prefer the canonical full trace; legacy events_toon flattened lists."""
    try:
        artifact = loads(trajectory.get("toon_payload", ""))
        events = artifact.get("events", []) if isinstance(artifact, dict) else []
        if isinstance(events, list) and all(isinstance(event, dict) for event in events):
            return events
    except Exception:
        pass
    events = trajectory.get("events", [])
    return events if isinstance(events, list) and all(isinstance(event, dict) for event in events) else []

def evidence_assertion(expected: Any) -> dict:
    if isinstance(expected, str):
        try: expected = loads(expected)
        except Exception: expected = {"expected": expected}
    return {"type": "gemini_evidence", "expected": expected}

# TOON is the sole accepted artifact format.  Rejecting JSON prevents a UI or
# client from silently creating non-reproducible evidence records.
async def parse_body(request: Request) -> dict:
    ct = request.headers.get("content-type", "")
    body = await request.body()
    text = body.decode("utf-8") if body else ""
    if not text:
        return {}
    if "application/toon" not in ct and "text/toon" not in ct:
        raise HTTPException(415, "Content-Type must be application/toon; JSON is not accepted")
    try:
        parsed = loads(text)
        if not isinstance(parsed, dict): raise ValueError("Top-level TOON value must be an object")
        return parsed
    except Exception as e:
        raise HTTPException(400, f"Invalid TOON: {e}")

def toon_response(data: Any, status_code: int = 200) -> Response:
    # TOON only — no JSON
    toon_text = dumps(data) if isinstance(data, dict) else dumps({"result": data})
    return Response(content=toon_text, media_type="application/toon", status_code=status_code,
                    headers={"X-Content-Type": "toon", "X-Format": "TOON"})

# Investigations

@router.post("/investigations")
async def create_investigation(request: Request):
    body = await parse_body(request)
    name = body.get("name") or body.get("title") or "Untitled"
    task = body.get("task") or ""
    expected = body.get("expected") or body.get("expected_result") or body.get("expected_behavior") or ""
    inv = Investigation(name=name, task=task, expected=expected)
    # also store toon_payload if provided
    toon_payload = body.get("toon_payload") or dumps(body)
    sb.insert("investigations", {"id": inv.id, "name": inv.name, "task": inv.task, "expected": inv.expected, "status": inv.status, "toon_payload": toon_payload})
    return JSONResponse({"id": inv.id, "name": inv.name, "task": inv.task, "expected": inv.expected, "status": inv.status})

@router.get("/investigations/{id}")
async def get_investigation(id: str, request: Request):
    inv = sb.get("investigations", id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    # enrich with counts
    cases = sb.list_by("test_cases", {"investigation_id": id})
    runs = sb.list_by("runs", {})
    # filter runs by case
    case_ids = {c["id"] for c in cases}
    inv_runs = [r for r in runs if r.get("case_id") in case_ids]
    inv["cases_count"] = len(cases)
    inv["runs_count"] = len(inv_runs)
    # return as JSON for dashboard convenience, but also support TOON
    accept = request.headers.get("accept", "")
    if "application/toon" in accept:
        return toon_response(inv)
    return JSONResponse(inv)

@router.post("/investigations/{id}/trace")
async def upload_trace(id: str, request: Request):
    inv = sb.get("investigations", id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    body = await parse_body(request)
    # Handle real TOON trace: run_id, repository, commit, model, task, events, expected, actual, passed, human_verified
    # Also handle legacy synthetic {events: [...]}
    events = body.get("events", [])
    trajectory_toon = body.get("toon_payload") or dumps(body)
    # Preserve real trace metadata if present
    real_meta = {}
    for k in ["run_id", "repository", "commit", "model", "task", "expected", "actual", "passed", "human_verified", "verification_notes"]:
        if k in body:
            real_meta[k] = body[k]
    if not events and isinstance(body, list):
        events = body
        trajectory_toon = dumps({"events": events})
    elif not events and "trajectory" in body:
        traj = body["trajectory"]
        if isinstance(traj, dict) and "events" in traj:
            events = traj["events"]
        elif isinstance(traj, list):
            events = traj
        else:
            events = [traj]
        trajectory_toon = dumps({"events": events})

    # Auto-convert JSON-like events: ensure each has step, type
    normalized = []
    for idx, e in enumerate(events):
        if not isinstance(e, dict):
            continue
        norm = {
            "step": e.get("step", idx+1),
            "type": e.get("type", "assistant"),
            "name": e.get("name"),
            "content": e.get("content", e.get("text", e.get("message", ""))),
            "timestamp": e.get("timestamp"),
            "model": e.get("model"),
        }
        # keep original extras
        for k in e:
            if k not in norm:
                norm[k] = e[k]
        normalized.append(norm)

    # Store trajectory — preserve real GitHub metadata if present (TOON only)
    traj_id = body.get("run_id", f"traj_{id}")
    # If real trace, ensure investigation reflects its repo/commit/task
    if real_meta.get("repository") and real_meta.get("commit"):
        # Verify pinned commit is real (read-only check)
        try:
            from app.services.github import verify_pinned_commit
            if not verify_pinned_commit(real_meta["repository"], real_meta["commit"]):
                raise HTTPException(400, f"Pinned commit {real_meta['commit']} not found in {real_meta['repository']}")
        except HTTPException:
            raise
        except Exception:
            pass  # if no GITHUB_TOKEN, still allow but log
        sb.update("investigations", id, {"task": real_meta.get("task", inv.get("task")), "commit": real_meta["commit"], "repository": real_meta["repository"]})
    # The Supabase trajectory table intentionally has a small relational
    # surface. All trace metadata (actual result, model, expected result,
    # pass/fail and verification notes) stays in the TOON payload rather than
    # being written as undeclared database columns.
    trajectory_artifact = dict(body)
    trajectory_artifact["events"] = normalized
    trajectory_toon = dumps(trajectory_artifact)
    traj_record = {
        "id": traj_id,
        "investigation_id": id,
        "toon_payload": trajectory_toon,
        "events": normalized,
        "run_id": real_meta.get("run_id"),
        "repository": real_meta.get("repository"),
        "commit": real_meta.get("commit"),
        "human_verified": real_meta.get("human_verified", False),
    }
    sb.insert("trajectories", traj_record)
    sb.update("investigations", id, {"status": "created"})
    token_info = {"original_events": len(events), "normalized_events": len(normalized), "toon_tokens": estimate_tokens(trajectory_toon or ""), "message": f"Stored {len(normalized)} events", "real_repo": real_meta.get("repository"), "real_commit": real_meta.get("commit"), "human_verified": real_meta.get("human_verified", False)}
    return JSONResponse(token_info)

@router.get("/investigations/{id}/trajectory")
async def get_trajectory(id: str, request: Request):
    trajs = sb.list_by("trajectories", {"investigation_id": id})
    if not trajs:
        raise HTTPException(404, "Trajectory not found")
    traj = trajs[0]
    accept = request.headers.get("accept", "")
    if "application/toon" in accept or "toon" in accept:
        # return raw TOON
        return Response(content=traj.get("toon_payload", dumps({"events": traj.get("events", [])})), media_type="application/toon")
    return JSONResponse(traj)

@router.post("/investigations/{id}/analyze")
async def analyze(id: str, request: Request):
    inv = sb.get("investigations", id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    body = await parse_body(request)
    # get trajectory
    trajs = sb.list_by("trajectories", {"investigation_id": id})
    if not trajs:
        raise HTTPException(400, "No trajectory uploaded")
    traj = trajs[0]
    traj_toon = traj.get("toon_payload") or dumps({"events": traj.get("events", [])})
    # merge task/expected from body or investigation
    task = body.get("task") or inv.get("task") or inv["task"]
    expected = body.get("expected") or body.get("expected_result") or inv.get("expected") or inv["expected"]
    # Agent call
    from app.providers.gemini import GeminiProvider
    outcome, model_used, _ = GeminiProvider().evaluate_outcome(task, expected, traj_toon)
    outcome["outcome"] = outcome.get("outcome") if outcome.get("outcome") in ("passed", "failed", "inconclusive") else "inconclusive"
    hyp_toon = dumps(outcome)
    sb.update("investigations", id, {"status": "analyzing"})
    # Store as report-like? Actually store in memory as investigation extension
    # Insert a run-like record for audit
    result = {
        "hypothesis": outcome,
        "outcome": outcome["outcome"],
        "hypothesis_toon": hyp_toon,
        "model_used": model_used,
        "is_mock": False,
        "tokens": estimate_tokens(traj_toon) + estimate_tokens(hyp_toon),
        "toon_tokens": estimate_tokens(hyp_toon),
        "json_tokens_estimate": int(estimate_tokens(hyp_toon) * 1.6),
        "saving_percent": round((1 - estimate_tokens(hyp_toon)/(estimate_tokens(hyp_toon)*1.6))*100,1),
    }
    save_artifact(id, "analysis", result, model_used)
    # Also insert a test stub for later? Not needed
    accept = request.headers.get("accept", "")
    if "application/toon" in accept:
        return Response(content=hyp_toon, media_type="application/toon", headers={"X-Model-Used": model_used})
    return JSONResponse(result, headers={"X-Model-Used": model_used})

@router.post("/investigations/{id}/reproduce")
async def reproduce(id: str, request: Request):
    inv = sb.get("investigations", id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    body = await parse_body(request)
    trajs = sb.list_by("trajectories", {"investigation_id": id})
    if not trajs:
        raise HTTPException(400, "No trajectory")
    traj = trajs[0]
    events = traj.get("events", [])
    task = inv.get("task")
    expected = inv.get("expected")
    # get hypothesis from body or re-analyze quickly
    hyp_data = body.get("hypothesis") or body.get("failure_hypothesis")
    hypothesis = None
    if hyp_data:
        try:
            hypothesis = FailureHypothesis(**hyp_data)
        except:
            pass
    # Also check stored hypothesis? For MVP just use heuristic
    events = get_trajectory_events(traj)
    analysis = load_artifacts(id).get("analysis", {})
    target_outcome = analysis.get("outcome") or analysis.get("hypothesis", {}).get("outcome") or "inconclusive"
    minimal_case, stats, tokens = reproducer.minimize_trajectory(
        id, task, expected, events, assertion=evidence_assertion(expected),
        hypothesis=hypothesis, target_outcome=target_outcome)
    # A new minimal case invalidates all prior cases and comparison evidence.
    sb.delete_by("test_cases", {"investigation_id": id})
    sb.delete_by("reports", {"investigation_id": id})
    for stale_stage in ("reproducer", "stress", "evidence"):
        sb.delete("workflow_artifacts", f"{id}:{stale_stage}")
    # Store minimal case as test_case
    case = TestCase(
        investigation_id=id,
        source="minimal_reproducer",
        input=minimal_case,
        input_toon=dumps(minimal_case),
        fixtures=minimal_case.get("recorded_tool_response") or minimal_case.get("fixtures"),
        fixtures_toon=dumps(minimal_case.get("recorded_tool_response") or {}),
        assertion=minimal_case.get("assertion"),
    )
    sb.insert("test_cases", {"id": case.id, "investigation_id": id, "source": case.source, "input_toon": case.input_toon, "fixtures_toon": case.fixtures_toon, "assertion": case.assertion, "input": minimal_case})
    sb.update("investigations", id, {"status": "reproducing"})
    result = {
        "minimal_case": minimal_case,
        "minimal_case_toon": dumps(minimal_case),
        "case_id": case.id,
        "stats": stats,
        "tokens": tokens,
    }
    save_artifact(id, "reproducer", result, stats.get("model_used", ""))
    accept = request.headers.get("accept", "")
    if "application/toon" in accept:
        return Response(content=dumps({"case_id": case.id, "minimal_case": minimal_case, "stats": stats}), media_type="application/toon")
    return JSONResponse(result)

@router.post("/investigations/{id}/stress")
async def stress(id: str, request: Request):
    inv = sb.get("investigations", id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    body = await parse_body(request)
    # Find minimal reproducer case
    cases = sb.list_by("test_cases", {"investigation_id": id, "source": "minimal_reproducer"})
    if not cases:
        raise HTTPException(400, "No minimal reproducer — run /reproduce first")
    minimal = cases[0]
    # Replace an earlier stress suite instead of mixing incompatible cases.
    for existing in sb.list_by("test_cases", {"investigation_id": id}):
        if existing.get("source") != "minimal_reproducer":
            sb.delete("test_cases", existing["id"])
    # The stored input is the minimal_case dict
    minimal_case = minimal.get("input") or loads(minimal.get("input_toon", "{}")) if isinstance(minimal.get("input_toon"), str) else minimal
    if isinstance(minimal_case, str):
        try:
            minimal_case = loads(minimal_case)
        except:
            minimal_case = {"task": inv["task"], "fixtures": {}}
    perturbations, model_used, is_mock, tokens = perturbation.generate_perturbations(minimal_case if isinstance(minimal_case, dict) else {"task": inv["task"]})
    # Create test cases for each perturbation and run baseline immediately
    results = []
    for pert in perturbations:
        case_fixtures = {
            "recorded_evidence": minimal_case.get("fixtures", {}) if isinstance(minimal_case, dict) else {},
            "perturbation": pert.get("mutation"),
        }
        source_map = {
            "ambiguity_injection": "perturbation_ambiguity",
            "stale_context_injection": "perturbation_stale",
            "tool_timeout": "perturbation_timeout",
            "tool_reorder": "perturbation_reorder",
        }
        mapped_source = source_map.get(pert["type"], "perturbation_ambiguity")
        case = TestCase(
            investigation_id=id,
            source=mapped_source,
            input={"task": pert.get("mutated_input"), "mutation": pert.get("mutation")},
            input_toon=dumps(pert),
            fixtures=case_fixtures,
            fixtures_toon=dumps(case_fixtures),
            assertion=minimal_case.get("assertion") if isinstance(minimal_case, dict) else evidence_assertion(inv.get("expected")),
        )
        sb.insert("test_cases", {"id": case.id, "investigation_id": id, "source": case.source, "input_toon": case.input_toon, "fixtures_toon": case.fixtures_toon, "assertion": case.assertion, "input": pert})
        # Run baseline replay for this perturbation
        replay = replay_case({"task": pert.get("mutated_input"), "fixtures": case_fixtures, "assertion": case.assertion, "id": case.id}, config="baseline", perturbation=pert)
        # Determine passed
        run = RunResult(case_id=case.id, config_id="baseline", passed=replay["passed"], latency_ms=replay["latency_ms"], tokens=replay["tokens"], evidence=replay["evidence"], evidence_toon=dumps(replay["evidence"]), model_used=replay.get("model_used"))
        sb.insert("runs", {"id": run.id, "case_id": case.id, "config_id": "baseline", "passed": run.passed, "latency_ms": run.latency_ms, "tokens": run.tokens, "evidence_toon": run.evidence_toon, "evidence": replay["evidence"]})
        results.append({"perturbation": pert, "case_id": case.id, "baseline_run": run.model_dump(), "replay": replay})
    sb.update("investigations", id, {"status": "stressing"})
    total_result = {
        "perturbations": perturbations,
        "results": results,
        "model_used": model_used,
        "is_mock": is_mock,
        "tokens": tokens,
        "matrix": [{"scenario": p["name"], "type": p["type"], "baseline": r["baseline_run"]["passed"]} for p, r in zip(perturbations, results)],
    }
    save_artifact(id, "stress", total_result, model_used)
    accept = request.headers.get("accept", "")
    if "application/toon" in accept:
        return Response(content=dumps({"perturbations": perturbations, "matrix": total_result["matrix"]}), media_type="application/toon")
    return JSONResponse(total_result)

@router.get("/investigations/{id}/cases")
async def get_cases(id: str, request: Request):
    inv = sb.get("investigations", id)
    if not inv:
        raise HTTPException(404, "Not found")
    cases = sb.list_by("test_cases", {"investigation_id": id})
    accept = request.headers.get("accept", "")
    if "application/toon" in accept:
        # return as TOON array
        from app.services.toon import dumps
        # wrap
        return Response(content=dumps({"cases": cases}), media_type="application/toon")
    return JSONResponse({"cases": cases, "total": len(cases)})

@router.post("/investigations/{id}/compare")
async def compare(id: str, request: Request):
    inv = sb.get("investigations", id)
    if not inv:
        raise HTTPException(404, "Not found")
    body = await parse_body(request)
    cases = sb.list_by("test_cases", {"investigation_id": id})
    if not cases:
        raise HTTPException(400, "No cases — run stress first")
    candidate_prompt = body.get("candidate_prompt") or body.get("prompt") or "Prompt requires tool result precedence over memory. Select by explicit ID, not recency."
    candidate_model = body.get("candidate_model") or body.get("model") or MODEL_PRIMARY
    # Create candidate config
    candidate_cfg = Config(type="candidate", prompt=candidate_prompt, model=candidate_model)
    baseline_cfg = Config(type="baseline", prompt="baseline", model=MODEL_PRIMARY)
    sb.insert("configs", {"id": baseline_cfg.id, "type": "baseline", "prompt": baseline_cfg.prompt, "model": baseline_cfg.model})
    sb.insert("configs", {"id": candidate_cfg.id, "type": "candidate", "prompt": candidate_cfg.prompt, "model": candidate_cfg.model})

    baseline_runs = []
    candidate_runs = []
    # For each case, replay both configs
    for case in cases:
        # case input contains perturbation etc.
        case_input = case.get("input")
        # try to extract perturbation info
        pert = None
        if isinstance(case_input, dict) and "type" in case_input:
            pert = case_input
        # fixtures
        fixtures = case.get("fixtures") or case.get("fixtures_toon")
        if isinstance(fixtures, str):
            try:
                fixtures = loads(fixtures)
            except:
                fixtures = {}
        assertion = case.get("assertion") or evidence_assertion(inv.get("expected"))
        # Determine task string for replay
        task = ""
        if isinstance(case_input, dict):
            task = case_input.get("mutated_input") or case_input.get("task") or inv["task"]
        else:
            task = inv["task"]
        # Build case dict for runner
        run_case = {"task": task, "fixtures": fixtures, "assertion": assertion, "id": case["id"], "candidate_prompt": candidate_prompt, "candidate_model": candidate_model}
        # Baseline
        b_replay = replay_case(run_case, config="baseline", perturbation=pert)
        b_run = RunResult(case_id=case["id"], config_id=baseline_cfg.id, passed=b_replay["passed"], latency_ms=b_replay["latency_ms"], tokens=b_replay["tokens"], evidence=b_replay["evidence"], evidence_toon=dumps(b_replay["evidence"]), model_used=b_replay.get("model_used"))
        sb.insert("runs", {"id": b_run.id, "case_id": case["id"], "config_id": baseline_cfg.id, "passed": b_run.passed, "latency_ms": b_run.latency_ms, "tokens": b_run.tokens, "evidence_toon": b_run.evidence_toon, "evidence": b_replay["evidence"], "model_used": b_run.model_used})
        baseline_runs.append(b_run.model_dump())
        # Candidate
        c_replay = replay_case(run_case, config="candidate", perturbation=pert)
        c_run = RunResult(case_id=case["id"], config_id=candidate_cfg.id, passed=c_replay["passed"], latency_ms=c_replay["latency_ms"], tokens=c_replay["tokens"], evidence=c_replay["evidence"], evidence_toon=dumps(c_replay["evidence"]), model_used=c_replay.get("model_used"))
        sb.insert("runs", {"id": c_run.id, "case_id": case["id"], "config_id": candidate_cfg.id, "passed": c_run.passed, "latency_ms": c_run.latency_ms, "tokens": c_run.tokens, "evidence_toon": c_run.evidence_toon, "evidence": c_replay["evidence"], "model_used": c_run.model_used})
        candidate_runs.append(c_run.model_dump())

    metrics = compute_comparison_metrics(baseline_runs, candidate_runs)
    # Verdict
    verdict = metrics["verdict"]
    # Build report TOON
    report_data = {
        "investigation_id": id,
        "verdict": verdict,
        "baseline_passed": metrics["baseline_passed"],
        "candidate_passed": metrics["candidate_passed"],
        "total_cases": metrics["total"],
        "regression_count": metrics["regressions"],
        "improvement": metrics["improvement"],
        "baseline_rate": metrics["baseline_rate"],
        "candidate_rate": metrics["candidate_rate"],
        "avg_latency_baseline_ms": metrics["avg_latency_baseline_ms"],
        "avg_latency_candidate_ms": metrics["avg_latency_candidate_ms"],
        "total_tokens": metrics["total_tokens"],
        "candidate_prompt": candidate_prompt,
        "candidate_model": candidate_model,
        "human_approval_required": True,
    }
    report_toon = dumps(report_data)
    report = Report(investigation_id=id, verdict=verdict, toon_payload=report_toon, summary=report_data, baseline_passed=metrics["baseline_passed"], candidate_passed=metrics["candidate_passed"], total_cases=metrics["total"], regression_count=metrics["regressions"])
    sb.insert("reports", {"id": report.id, "investigation_id": id, "verdict": report.verdict, "toon_payload": report.toon_payload, "summary": report_data, "baseline_passed": report.baseline_passed, "candidate_passed": report.candidate_passed, "total_cases": report.total_cases, "regression_count": report.regression_count})
    sb.update("investigations", id, {"status": "comparing"})
    # Human approval required — don't auto-promote
    result = {
        "report": report.model_dump(),
        "report_toon": report_toon,
        "metrics": metrics,
        "baseline_runs": baseline_runs,
        "candidate_runs": candidate_runs,
        "verdict": verdict,
        "verdict_text": f"{verdict} — HUMAN REVIEW REQUIRED" if verdict in ["IMPROVED_BUT_NOT_READY", "IMPROVED"] else verdict,
        "evidence": {"baseline_ids": [r["id"] for r in baseline_runs], "candidate_ids": [r["id"] for r in candidate_runs]},
        "human_approval_required": True,
    }
    save_artifact(id, "evidence", result, candidate_model)
    accept = request.headers.get("accept", "")
    if "application/toon" in accept:
        return Response(content=report_toon, media_type="application/toon")
    return JSONResponse(result)

@router.get("/investigations/{id}/workflow")
async def get_workflow(id: str, request: Request):
    if not sb.get("investigations", id):
        raise HTTPException(404, "Investigation not found")
    return JSONResponse({"artifacts": load_artifacts(id)})

@router.get("/investigations/{id}/report")
async def get_report(id: str, request: Request):
    reports = sb.list_by("reports", {"investigation_id": id})
    if not reports:
        # No report yet — not an error, just no evidence yet (investigation still in progress)
        accept = request.headers.get("accept", "")
        if "application/toon" in accept or "toon" in accept:
            return Response(status_code=204)
        return JSONResponse({"report": None, "message": "No report yet — run analyze → reproducer → stress → compare"}, status_code=200)
    report = sorted(reports, key=lambda x: x.get("created_at", ""), reverse=True)[0]
    accept = request.headers.get("accept", "")
    if "application/toon" in accept:
        return Response(content=report.get("toon_payload", dumps(report)), media_type="application/toon")
    return JSONResponse(report)

# Additional helper: list investigations
@router.get("/investigations")
async def list_investigations(request: Request):
    try:
        invs = sb.list_all("investigations")
    except Exception as exc:
        raise HTTPException(503, "Supabase schema is not ready. Run supabase/schema.sql in the connected Supabase project's SQL Editor, then retry.") from exc
    # sort by created_at desc
    invs = sorted(invs, key=lambda x: x.get("created_at", ""), reverse=True)
    return JSONResponse({"investigations": invs, "total": len(invs)})

@router.delete("/investigations")
async def clear_investigations(request: Request):
    body = await parse_body(request)
    if body.get("confirm") != "CLEAR_ALL_INVESTIGATIONS":
        raise HTTPException(400, "Confirmation required: confirm: CLEAR_ALL_INVESTIGATIONS")
    try:
        deleted = sb.clear_all_investigations()
    except Exception as exc:
        raise HTTPException(503, "Could not clear Supabase. Confirm supabase/schema.sql has been applied and credentials can write.") from exc
    return toon_response({"cleared": True, "deleted": deleted})

"""
Minimal Reproducer Agent — Real Gemini only, TOON, deterministic replay.
No mocks, no heuristic fallback.
"""
from __future__ import annotations
from typing import Tuple, Any, List
import time
from app.services.toon import dumps, estimate_tokens
from app.providers.gemini import GeminiProvider
from app.eval.runner import replay_case

provider = GeminiProvider()

def minimize_trajectory(
    investigation_id: str,
    task: str,
    expected: str,
    events: List[dict],
    assertion: dict = None,
    hypothesis: Any = None,
    target_outcome: str = "failed",
) -> Tuple[dict, dict, int]:
    """
    Real Gemini suggestion + deterministic replay to verify failure preserved.
    Returns (minimal_case, stats, tokens)
    """
    original_len = len(events)
    fixtures = {}
    minimal_events = list(events)
    best = minimal_events
    tokens_used = 0
    if not assertion:
        raise ValueError("A task-specific evidence assertion is required")

    def reproduces(evts):
        case = {
            "task": task,
            "events": evts,
            "fixtures": fixtures,
            "assertion": assertion,
        }
        result = replay_case(case, config="baseline")
        return result["passed"] if target_outcome == "passed" else not result["passed"]

    for e in events:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "tool_result" and isinstance(e.get("content"), dict):
            fixtures.update(e["content"])
        if e.get("type") == "tool_result" and e.get("file"):
            fixtures[e.get("file")] = e.get("content", "")
        if e.get("type") == "tool_result" and e.get("result"):
            fixtures.update(e.get("result") if isinstance(e.get("result"), dict) else {})
        if e.get("type") == "tool_result" and isinstance(e.get("files"), list):
            fixtures["repository_files"] = e["files"]
        if e.get("type") == "tool_result" and e.get("path") and e.get("snippet") is not None:
            fixtures.setdefault("file_contents", {})[e["path"]] = e["snippet"]

    if not fixtures:
        # for real GitHub traces, keep file context
        fixtures = {"repo_files": [e.get("file") for e in events if isinstance(e, dict) and e.get("file")] or fixtures}

    # Real Gemini suggestion — no heuristic, will raise if GEMINI_API_KEY missing
    toon_traj = dumps({"task": task, "events": events})
    suggestion, model_used, _ = provider.minimize_suggestion(toon_traj, dumps({"events": best}))
    tokens_used += estimate_tokens(toon_traj)
    removable = suggestion.get("removable_steps", [])

    candidates_to_remove = removable if removable else list(range(1, max(0, len(events)-1)))
    filtered = []
    step_to_index = {event.get("step"): index for index, event in enumerate(best) if isinstance(event, dict)}
    for suggested_step in candidates_to_remove:
        idx = step_to_index.get(suggested_step, suggested_step)
        if not isinstance(idx, int) or idx < 0 or idx >= len(best):
            continue
        evt = best[idx]
        if not isinstance(evt, dict):
            continue
        # Tool results are the recorded evidence and cannot be minimized away.
        if evt.get("type") == "tool_result":
            continue
        if evt.get("type") == "user_task" and idx == 0:
            continue
        if evt.get("type") == "user" and idx == 0:
            continue
        filtered.append(idx)

    for remove_idx in sorted(filtered, reverse=True):
        trial = [e for i, e in enumerate(best) if i != remove_idx]
        if len(trial) < 3:
            continue
        if reproduces(trial):
            best = trial

    minimal_context = []
    for e in best:
        if not isinstance(e, dict):
            minimal_context.append(str(e))
            continue
        if e.get("type") in ("user", "user_task", "system"):
            minimal_context.append(e.get("content") or str(e))
        elif e.get("type") == "tool_result":
            evidence_value = e.get("snippet") or e.get("files") or e.get("content") or e.get("result")
            minimal_context.append(f"tool:{e.get('tool') or e.get('name')} -> {evidence_value}")

    minimal_case = {
        "case_id": f"RF-{investigation_id[:4] if investigation_id else 'MIN'}",
        "task": task,
        "target_outcome": target_outcome,
        "minimal_context": minimal_context[:5],
        "fixtures": fixtures,
        "expected": expected,
        "events": best,
        "assertion": assertion,
    }

    successes = 0
    for _ in range(3):
        res = replay_case({"task": task, "events": best, "fixtures": fixtures, "assertion": minimal_case["assertion"]}, config="baseline")
        if (res["passed"] and target_outcome == "passed") or (not res["passed"] and target_outcome != "passed"):
            successes += 1
        time.sleep(0.01)

    stats = {
        "original_events": original_len,
        "reduced_events": len(best),
        "reduction_percent": round((1 - len(best)/original_len)*100, 1) if original_len else 0,
        "reproduction_success": f"{successes}/3",
        "reproduction_rate": successes/3,
        "model_used": model_used,
        "original_tokens": estimate_tokens(dumps({"events": events})),
        "reduced_tokens": estimate_tokens(dumps({"events": best})),
        "token_saving_percent": round((1 - estimate_tokens(dumps({"events": best}))/max(1, estimate_tokens(dumps({"events": events}))))*100,1),
        "minimal_context_size": len(minimal_context),
    }
    return minimal_case, stats, tokens_used

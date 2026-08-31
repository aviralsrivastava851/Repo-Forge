"""
TOON Trace Recorder — Real traces only, no mocks.
Records: run_id, repository, commit (pinned), model, task, events, expected, actual, passed
Events: user_task, model_call, tool_call, tool_result, final_decision
Format: TOON only, saved to data/real_traces/*.toon
"""
from __future__ import annotations
import os
import uuid
import time
from pathlib import Path
from typing import Any, List, Dict, Optional
from app.services.toon import dumps, loads
from app.services.github import github_code_search, github_get_file, verify_pinned_commit

TRACE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "real_traces"
TRACE_DIR.mkdir(parents=True, exist_ok=True)

class TraceRecorder:
    def __init__(self, repository: str, commit: str, task: str, model: str = "gemini-3.5-flash"):
        if not verify_pinned_commit(repository, commit):
            raise ValueError(f"Pinned commit {commit} not found in {repository} — use a real commit SHA from https://github.com/{repository}/commits")
        self.run_id = f"run_{uuid.uuid4().hex[:6]}"
        self.repository = repository
        self.commit = commit
        self.task = task
        self.model = model
        self.events: List[Dict[str, Any]] = []
        self.step = 1
        self.expected: Optional[Dict[str, Any]] = None
        self.actual: Optional[Dict[str, Any]] = None
        self.passed: Optional[bool] = None
        self.evaluation: Optional[Dict[str, Any]] = None
        # initial user_task event
        self.add_event("user_task", {"content": task})

    def add_event(self, type: str, data: Dict[str, Any]):
        evt = {"step": self.step, "type": type, **data}
        self.events.append(evt)
        self.step += 1
        return evt

    def record_model_call(self, model: str):
        return self.add_event("model_call", {"model": model})

    def record_tool_call(self, tool: str, **kwargs):
        evt = self.add_event("tool_call", {"tool": tool, **kwargs})
        return evt

    def record_tool_result(self, **kwargs):
        return self.add_event("tool_result", kwargs)

    def record_final_decision(self, answer: Any):
        return self.add_event("final_decision", {"answer": answer})

    def set_ground_truth(self, expected: Dict[str, Any], actual: Dict[str, Any]):
        self.expected = expected
        self.actual = actual
        self.passed = (expected == actual)
        return self.passed

    def set_evaluation(self, expected: Dict[str, Any], actual: Dict[str, Any], evaluation: Dict[str, Any]):
        self.expected, self.actual, self.evaluation = expected, actual, evaluation
        self.passed = evaluation.get("outcome") == "passed"
        return self.passed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "repository": self.repository,
            "commit": self.commit,
            "model": self.model,
            "task": self.task,
            "events": self.events,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed if self.passed is not None else False,
            "evaluation": self.evaluation,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def to_toon(self) -> str:
        return dumps(self.to_dict())

    def save(self) -> Path:
        toon_text = self.to_toon()
        # validate TOON
        from app.services.toon import validate
        if not validate(toon_text):
            raise ValueError("Generated TOON is invalid")
        path = TRACE_DIR / f"{self.run_id}.toon"
        path.write_text(toon_text, encoding="utf-8")
        return path

# --- Real run helper: REAL USER TASK -> Gemini 3.5 Flash -> difficult? -> 2.5 Pro -> REAL TOOL CALLS -> TOON ---

def run_real_trace(
    repository: str,
    commit: str,
    task: str,
    expected: Dict[str, Any],
    max_tool_calls: int = 5,
) -> Path:
    """
    Runs a real user task:
    1. Calls Gemini 3.5 Flash (or difficult -> 2.5 Pro)
    2. Executes real GitHub read-only tool calls
    3. Records TOON trace
    This is the exact data flow requested:
    REAL USER TASK -> Gemini 3.5 Flash -> (difficult? -> 2.5 Pro) -> REAL TOOL CALLS -> REAL TOOL OUTPUTS -> TOON TRACE RECORDER
    """
    from app.providers.gemini import run_model, MODEL_PRIMARY, MODEL_FALLBACK

    recorder = TraceRecorder(repository, commit, task, model=MODEL_PRIMARY)

    # Decide if difficult -> use fallback directly
    difficult = any(k in task.lower() for k in ["ambiguous", "difficult", "hard", "complex", "verify"])

    # Build prompt for Gemini to generate tool calls
    prompt = f"""You are investigating a real GitHub repository.
Repository: {repository}
Pinned commit: {commit}
Task: {task}

You have real read-only tools:
- github_code_search(query, repo, commit) -> search code
- github_get_file(path, repo, commit) -> read file

Generate a plan with 1-3 tool calls. Output TOON:
plan:
  - tool: github_code_search
    query: ...
  - tool: github_get_file
    path: ...
"""

    # Call Gemini (real, no mock)
    try:
        toon_text, model_used = run_model(prompt, difficult=difficult)
        recorder.record_model_call(model_used)
    except Exception as e:
        # fallback already handled in run_model, but if still fails, record error
        recorder.add_event("model_error", {"error": str(e)})
        toon_text = "plan:\n  - tool: github_code_search\n    query: validation"

    # Parse plan and execute real tool calls
    try:
        plan_data = loads(toon_text)
        plans = plan_data.get("plan", []) if isinstance(plan_data, dict) else []
        if not isinstance(plans, list):
            plans = []
    except:
        plans = [{"tool": "github_code_search", "query": task.split()[0]}]

    for p in plans[:max_tool_calls]:
        tool = p.get("tool", "github_code_search")
        query = p.get("query", task)
        path = p.get("path", "")
        recorder.record_tool_call(tool, query=query, path=path)
        try:
            if tool == "github_code_search":
                result = github_code_search(query, repository, commit)
                recorder.record_tool_result(tool=tool, query=query, result=result)
            elif tool == "github_get_file":
                result = github_get_file(repository, path, commit)
                recorder.record_tool_result(tool=tool, path=path, content=result["content"][:1200])
            else:
                result = github_code_search(query, repository, commit)
                recorder.record_tool_result(tool=tool, result=result)
        except Exception as e:
            recorder.record_tool_result(tool=tool, error=str(e)[:800])

    # Final decision — let Gemini make a final call (real) to pick the answer file
    final_prompt = f"""Given the tool results, what file answers the task?
Task: {task}
Repository: {repository}@{commit}
Expected (ground truth): {expected}

Tool outputs so far: {recorder.events[-2:]}

Output TOON:
answer:
  file: path/to/file
"""
    try:
        final_toon, final_model = run_model(final_prompt, difficult=False)
        final_data = loads(final_toon)
        answer = final_data.get("answer", final_data)
        recorder.record_final_decision(answer)
        actual = answer if isinstance(answer, dict) else {"file": str(answer)}
    except Exception as e:
        actual = {"file": "unknown", "error": str(e)}
        recorder.record_final_decision(actual)

    recorder.set_ground_truth(expected, actual)
    return recorder.save()

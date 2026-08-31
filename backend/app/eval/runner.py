"""Real Gemini replay over recorded repository evidence; no synthetic fallback."""
from __future__ import annotations
import time
from typing import Dict, Any

def replay_case(case: Dict[str, Any], config: str = "baseline", perturbation: Dict[str, Any] = None) -> Dict[str, Any]:
    """Execute one recorded case and evaluate it against its evidence contract."""
    # Production replay is a real Gemini execution over the recorded case.
    # Expected values are intentionally excluded from the prompt and used only
    # by the deterministic assertion after the model returns.
    start = time.time()
    from app.providers.gemini import MODEL_PRIMARY, run_model_named
    from app.services.toon import dumps, loads, estimate_tokens
    from app.eval.assertions import check_assertion

    task = case.get("task", "")
    fixtures = case.get("fixtures") or case.get("recorded_tool_response") or {}
    if isinstance(fixtures, str):
        try: fixtures = loads(fixtures)
        except Exception: fixtures = {"raw": fixtures}
    assertion = case.get("assertion") or {}
    candidate_instruction = case.get("candidate_prompt", "") if config == "candidate" else ""
    selected_model = case.get("candidate_model") if config == "candidate" else MODEL_PRIMARY
    prompt = f"""Execute this recorded evaluation case.
Task: {task}
Recorded tool evidence (TOON):
{dumps(fixtures if isinstance(fixtures, dict) else {"fixtures": fixtures})}
Perturbation (TOON):
{dumps(perturbation or {})}
Additional candidate instruction: {candidate_instruction}

Return only the task answer as TOON using keys appropriate to the task. Do not
invent unavailable evidence.
"""
    answer_text, model_used = run_model_named(prompt, selected_model or MODEL_PRIMARY)
    answer = loads(answer_text)
    if isinstance(answer, dict) and isinstance(answer.get("answer"), dict):
        answer = answer["answer"]
    if not isinstance(answer, dict):
        answer = {"answer": answer}
    if assertion.get("type") == "gemini_evidence":
        from app.providers.gemini import GeminiProvider
        evaluation, evaluator_model, _ = GeminiProvider().evaluate_outcome(
            str(task), dumps(assertion.get("expected", {})), dumps({"answer": answer}))
        passed = evaluation.get("outcome") == "passed"
        answer["evaluation"] = evaluation
        model_used = f"{model_used}+{evaluator_model}"
    else:
        passed = check_assertion(answer, assertion) if assertion else False
    return {
        "passed": passed,
        "evidence": answer,
        "latency_ms": max(1, int((time.time() - start) * 1000)),
        "tokens": estimate_tokens(prompt) + estimate_tokens(answer_text),
        "model_used": model_used,
    }

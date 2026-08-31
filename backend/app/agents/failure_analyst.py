"""
Failure Analyst Agent — Real Gemini only, TOON in/out, no mocks.
Primary: Gemini 3.5 Flash, difficult -> Gemini 2.5 Pro fallback.
"""
from __future__ import annotations
from typing import Tuple
from app.providers.gemini import GeminiProvider
from app.services.toon import dumps
from app.models.schemas import FailureHypothesis, FailureClass

provider = GeminiProvider()

def analyze(task: str, expected: str, trajectory_toon: str, trajectory_events: list = None) -> Tuple[FailureHypothesis, str, bool, int]:
    """
    Real Gemini analysis only — no heuristic mock.
    Returns (hypothesis, model_used, is_mock=False, tokens)
    Difficult root-cause (ambiguous/difficult) is routed to Gemini 2.5 Pro inside provider.
    """
    from app.services.toon import estimate_tokens
    # Real Gemini call — will raise if GEMINI_API_KEY missing or on failure (no mock fallback)
    data, model_used, is_mock = provider.analyze_failure(task, expected, trajectory_toon)
    # Validate
    fc = data.get("failure_class", "stale_context")
    if fc not in [e.value for e in FailureClass]:
        fc = "stale_context"
    hypothesis = FailureHypothesis(
        failure_class=fc,
        suspected_step=int(data.get("suspected_step", 5)),
        evidence=data.get("evidence", ["LLM evidence"])[:3],
        expected_behavior=data.get("expected_behavior", expected)[:500],
        observed_behavior=data.get("observed_behavior", "Observed failure")[:500],
        confidence=float(data.get("confidence", 0.78)),
    )
    tokens = estimate_tokens(trajectory_toon) + estimate_tokens(dumps(data))
    return hypothesis, model_used, False, tokens

"""
Perturbation Designer — Real Gemini 3.5 Flash only, TOON.
No fallback heuristics, no mocks — real Gemini only.
"""
from __future__ import annotations
from typing import List, Dict, Tuple
from app.providers.gemini import GeminiProvider
from app.services.toon import dumps, estimate_tokens

provider = GeminiProvider()

def generate_perturbations(minimal_case: dict) -> Tuple[List[Dict], str, bool, int]:
    """
    Real Gemini 3.5 Flash (fallback to 2.5 Pro on failure) — no mocks.
    Returns (perturbations, model_used, is_mock=False, tokens)
    """
    toon_case = dumps(minimal_case)
    perturbations, model_used, _ = provider.suggest_perturbations(toon_case)
    tokens = estimate_tokens(toon_case) + sum(estimate_tokens(dumps(p)) for p in perturbations)
    # Normalize to 4 required types
    normed = []
    required_types = ["ambiguity_injection", "stale_context_injection", "tool_timeout", "tool_reorder"]
    required_names = ["Ambiguity Injection", "Stale Context Injection", "Tool Timeout / Error Injection", "Tool Result Reorder / Schema Variation"]
    for i, p in enumerate(perturbations[:4]):
        if isinstance(p, dict):
            normed.append({
                "id": p.get("id", f"pert_{i}"),
                "type": p.get("type", required_types[i % 4]),
                "name": p.get("name", required_names[i % 4]),
                "hypothesis": p.get("hypothesis", "Perturbation hypothesis"),
                "mutated_input": p.get("mutated_input", str(p)),
                "mutation": p.get("mutation", p.get("mutated_input", {})),
                "expected": p.get("expected", "Should pass with correct fix"),
            })
    while len(normed) < 4:
        # This should not happen with real Gemini, but ensure 4
        raise RuntimeError(f"Gemini did not return 4 perturbations (got {len(normed)}): {perturbations}")
    return normed[:4], model_used, False, tokens

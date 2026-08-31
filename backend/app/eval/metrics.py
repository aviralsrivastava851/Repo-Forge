"""
Metrics — FRIR and secondary metrics
"""
from __future__ import annotations
from typing import List, Dict

def compute_frir(cases: List[Dict], hypotheses: List[Dict]) -> Dict:
    total = len(cases)
    if total == 0:
        return {"frir": 0, "reproduced": 0, "isolated": 0, "total": 0}
    reproduced = sum(1 for c in cases if c.get("reproduction_rate", 0) >= 0.66)
    isolated = sum(1 for h in hypotheses if h.get("confidence", 0) >= 0.7)
    # FRIR = cases with reproducible + correct isolation / total
    frir = reproduced / total if total else 0
    return {
        "frir": round(frir, 3),
        "reproduced": reproduced,
        "isolated": isolated,
        "total": total,
        "details": f"{reproduced}/{total} reproduced, {isolated}/{total} isolated"
    }

def compute_comparison_metrics(baseline_runs: List[Dict], candidate_runs: List[Dict]) -> Dict:
    total = len(baseline_runs)
    base_pass = sum(1 for r in baseline_runs if r.get("passed"))
    cand_pass = sum(1 for r in candidate_runs if r.get("passed"))
    regressions = sum(1 for b, c in zip(baseline_runs, candidate_runs) if b.get("passed") and not c.get("passed"))
    improvement = cand_pass - base_pass
    avg_lat_base = sum(r.get("latency_ms", 0) for r in baseline_runs) / max(1, len(baseline_runs))
    avg_lat_cand = sum(r.get("latency_ms", 0) for r in candidate_runs) / max(1, len(candidate_runs))
    total_tokens = sum(r.get("tokens", 0) for r in baseline_runs) + sum(r.get("tokens", 0) for r in candidate_runs)
    verdict = "INCONCLUSIVE"
    if cand_pass > base_pass and cand_pass == total:
        verdict = "IMPROVED"
    elif cand_pass > base_pass:
        verdict = "IMPROVED_BUT_NOT_READY" if regressions > 0 else "IMPROVED"
    elif regressions > 0:
        verdict = "REGRESSION"
    elif cand_pass == base_pass:
        verdict = "NO_IMPROVEMENT"
    return {
        "total": total,
        "baseline_passed": base_pass,
        "candidate_passed": cand_pass,
        "baseline_rate": round(base_pass/total, 3) if total else 0,
        "candidate_rate": round(cand_pass/total, 3) if total else 0,
        "improvement": improvement,
        "regressions": regressions,
        "avg_latency_baseline_ms": round(avg_lat_base),
        "avg_latency_candidate_ms": round(avg_lat_cand),
        "total_tokens": total_tokens,
        "verdict": verdict,
    }

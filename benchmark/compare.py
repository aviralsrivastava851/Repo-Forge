#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.services.toon import dumps as toon_dumps, loads as toon_loads, validate

BASE = os.path.dirname(__file__)
RESULTS_DIR = os.path.join(BASE, "..", "results")

def load(name):
    # TOON only — no JSON
    path = os.path.join(RESULTS_DIR, f"{name}.toon")
    if not os.path.exists(path):
        print(f"Missing {path} — run evaluate.py --config {name} first (TOON only)")
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not validate(text):
        print(f"Invalid TOON {path}")
        return None
    return toon_loads(text)

def main():
    baseline = load("baseline")
    candidate = load("candidate")
    if not baseline or not candidate:
        return
    b_cases = {c["case_id"]: c for c in baseline["cases"]}
    c_cases = {c["case_id"]: c for c in candidate["cases"]}
    print("\nReproForge Comparison -- TOON + Gemini 3.5 Flash -> 2.5 Pro (real)")
    print("="*70)
    total = len(b_cases)
    b_pass = sum(1 for c in baseline["cases"] if c["replay_passed"])
    c_pass = sum(1 for c in candidate["cases"] if c["replay_passed"])
    regressions = sum(1 for cid in b_cases if b_cases[cid]["replay_passed"] and not c_cases[cid]["replay_passed"])
    print(f"Baseline: {b_pass}/{total} passed")
    print(f"Candidate: {c_pass}/{total} passed")
    print(f"Regressions: {regressions}")
    print(f"Baseline FRIR: {baseline['frir']:.2%}")
    print(f"Candidate FRIR: {candidate['frir']:.2%}")
    print(f"Token totals (TOON only): baseline {baseline['total_tokens']} vs candidate {candidate['total_tokens']}")
    verdict = "IMPROVED" if c_pass > b_pass and regressions==0 else "IMPROVED_BUT_NOT_READY" if c_pass > b_pass else "REGRESSION" if regressions>0 else "NO_IMPROVEMENT"
    print(f"\nVerdict: {verdict} -- HUMAN REVIEW REQUIRED" if verdict.startswith("IMPROVED") else f"\nVerdict: {verdict}")
    print("\nPer-case (real traces: pinned SHAs, human-verified):")
    print(f"{'Case':<12} {'Repo':<20} {'Baseline':<10} {'Candidate':<10} {'FRIR'}")
    for cid in sorted(b_cases):
        bc = b_cases[cid]
        cc = c_cases[cid]
        repo = bc.get("repository", bc.get("expected_class",""))[:20]
        print(f"{cid:<12} {repo:<20} {str(bc['replay_passed']):<10} {str(cc['replay_passed']):<10} {bc['reproduced'] and bc['isolated_correct']}")

    comp = {
        "baseline_passed": b_pass,
        "candidate_passed": c_pass,
        "total": total,
        "regressions": regressions,
        "verdict": verdict,
        "baseline_frir": baseline["frir"],
        "candidate_frir": candidate["frir"],
        "model_primary": baseline.get("model_primary", "gemini-3.5-flash"),
        "model_fallback": baseline.get("model_fallback", "gemini-2.5-pro"),
    }
    with open(os.path.join(RESULTS_DIR, "comparison.toon"), "w", encoding="utf-8") as f:
        f.write(toon_dumps(comp))
    print(f"\nSaved {RESULTS_DIR}/comparison.toon (TOON only, no JSON)")

    report = f"""REPROFORGE RELIABILITY REPORT (REAL TRACES)
--------------------------------
Baseline: {b_pass}/{total} passed (real GitHub, pinned SHAs)
Candidate: {c_pass}/{total} passed
Regressions: {regressions}
Verdict: {verdict} -- HUMAN REVIEW REQUIRED
Evidence: data/real_traces/*.toon + results/*.toon (TOON only, no JSON)
Models: {baseline.get('model_primary','gemini-3.5-flash')} -> {baseline.get('model_fallback','gemini-2.5-pro')}
TOON tokens: baseline {baseline['total_tokens']} candidate {candidate['total_tokens']}
Real repos: vercel/next.js, facebook/react, auth0/node-jsonwebtoken, supabase/supabase (pinned SHAs, human-verified)
"""
    print("\n" + report)
    with open(os.path.join(RESULTS_DIR, "report.txt"), "w", encoding="utf-8") as f:
        f.write(report)

if __name__ == "__main__":
    main()

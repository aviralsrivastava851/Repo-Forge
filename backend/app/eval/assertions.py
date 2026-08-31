"""
Deterministic assertions — code decides pass/fail, not LLM
"""
from __future__ import annotations
from typing import Any, Dict

def get_by_path(obj: Any, path: str) -> Any:
    """Support dot notation: selected_order or orders[0].id"""
    # handle simple path
    if not path:
        return obj
    parts = path.replace("[", ".").replace("]", "").split(".")
    cur = obj
    for p in parts:
        if p == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list):
            try:
                idx = int(p)
                cur = cur[idx] if 0 <= idx < len(cur) else None
            except:
                return None
        else:
            return None
        if cur is None:
            return None
    return cur

def check_assertion(evidence: Any, assertion: Dict) -> bool:
    """
    assertion examples:
    {"path": "selected_order", "equals": 102}
    {"path": "orders[0].id", "equals": 102}
    {"path": "status", "equals": "refunded"}
    {"contains": "ask"}
    """
    if not assertion:
        return False
    if "equals" in assertion and "path" in assertion:
        val = get_by_path(evidence, assertion["path"])
        return val == assertion["equals"]
    if "not_equals" in assertion and "path" in assertion:
        val = get_by_path(evidence, assertion["path"])
        return val != assertion["not_equals"]
    if "contains" in assertion:
        # check if evidence string contains
        ev_str = str(evidence).lower()
        return assertion["contains"].lower() in ev_str
    if "exists" in assertion:
        val = get_by_path(evidence, assertion["exists"])
        return val is not None
    return False

def evaluate_candidate_improvement(baseline_pass: int, candidate_pass: int, total: int) -> str:
    if candidate_pass > baseline_pass and candidate_pass == total:
        return "IMPROVED"
    if candidate_pass > baseline_pass:
        return "IMPROVED_BUT_NOT_READY"
    if candidate_pass < baseline_pass:
        return "REGRESSION"
    if candidate_pass == baseline_pass:
        return "NO_IMPROVEMENT"
    return "INCONCLUSIVE"

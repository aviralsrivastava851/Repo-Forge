"""
Pydantic schemas — TOON-validated, stored in Supabase
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Optional, List, Literal
from enum import Enum
import time
import uuid

def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"

class FailureClass(str, Enum):
    wrong_tool_selection = "wrong_tool_selection"
    wrong_tool_arguments = "wrong_tool_arguments"
    stale_context = "stale_context"
    misleading_context = "misleading_context"
    ignored_constraint = "ignored_constraint"
    ambiguous_instruction = "ambiguous_instruction"
    tool_error_recovery = "tool_error_recovery"
    incomplete_task = "incomplete_task"
    wrong_final_answer = "wrong_final_answer"

class TraceEvent(BaseModel):
    step: int
    type: Literal["system", "user", "assistant", "tool_call", "tool_result", "tool_error"]
    name: Optional[str] = None
    content: Any = None
    timestamp: Optional[str] = None
    model: Optional[str] = None
    tokens: Optional[int] = None

class Trajectory(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("traj"))
    investigation_id: str
    events: List[TraceEvent]
    toon_payload: Optional[str] = None
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

class FailureHypothesis(BaseModel):
    failure_class: FailureClass
    suspected_step: int
    evidence: List[str]
    expected_behavior: str
    observed_behavior: str
    confidence: float = Field(ge=0, le=1)

class InvestigationCreate(BaseModel):
    name: str
    task: str
    expected: str
    toon_payload: Optional[str] = None

class Investigation(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("inv"))
    name: str
    task: str
    expected: str
    status: Literal["created", "analyzing", "reproducing", "stressing", "comparing", "completed", "failed"] = "created"
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

class TestCase(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("case"))
    investigation_id: str
    source: Literal["minimal_reproducer", "perturbation_ambiguity", "perturbation_stale", "perturbation_timeout", "perturbation_reorder"]
    input_toon: Optional[str] = None
    input: Any = None
    fixtures: Any = None
    fixtures_toon: Optional[str] = None
    assertion: Any = None
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

class RunResult(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("run"))
    case_id: str
    config_id: str
    passed: bool
    latency_ms: int
    tokens: int = 0
    cost: float = 0.0
    evidence: Any = None
    evidence_toon: Optional[str] = None
    model_used: Optional[str] = None
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

class Config(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("cfg"))
    type: Literal["baseline", "candidate"]
    prompt: Optional[str] = None
    model: str = "gemini-3.5-flash"
    params: Any = None

class Report(BaseModel):
    id: str = Field(default_factory=lambda: gen_id("rep"))
    investigation_id: str
    verdict: Literal["IMPROVED", "IMPROVED_BUT_NOT_READY", "NO_IMPROVEMENT", "REGRESSION", "INCONCLUSIVE"]
    toon_payload: Optional[str] = None
    summary: Any = None
    baseline_passed: int = 0
    candidate_passed: int = 0
    total_cases: int = 0
    regression_count: int = 0
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

class AnalyzeRequest(BaseModel):
    trajectory_toon: Optional[str] = None
    trajectory: Optional[Any] = None  # accept JSON too for compat

class ReproduceRequest(BaseModel):
    hypothesis: Optional[FailureHypothesis] = None

class StressRequest(BaseModel):
    reproducer_case_id: Optional[str] = None

class CompareRequest(BaseModel):
    candidate_config: Optional[Config] = None
    candidate_prompt: Optional[str] = None
    candidate_model: Optional[str] = None

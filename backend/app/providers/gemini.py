"""
Gemini Provider — Real calls only, no mocks.
Primary: Gemini 3.5 Flash
Fallback: configured Gemini Pro model (on difficult or on Flash failure/timeout)
TOON is primary I/O, no JSON.
Uses GEMINI_API_KEY from .env.local (user-provided, never committed).
"""
from __future__ import annotations
import os
import time
import asyncio
from pathlib import Path
from typing import Any, Tuple, Optional
from dotenv import load_dotenv

# Provider functions are also used directly by workers and tests, outside the
# FastAPI app bootstrap, so configuration must be loaded here as well.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_BACKEND_ROOT / ".env.local")
load_dotenv(_BACKEND_ROOT.parent / ".env.local")

# Model chain — exactly as requested: Primary 3.5 Flash, Fallback 2.5 Pro
MODEL_PRIMARY = os.getenv("GEMINI_MODEL", os.getenv("GEMINI_FLASH_MODEL", "gemini-3.5-flash"))
MODEL_FALLBACK = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")

# Keep chain for compatibility
MODEL_CHAIN = [MODEL_PRIMARY, MODEL_FALLBACK]

def _get_api_key() -> Optional[str]:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

def is_configured() -> bool:
    return _credential_problem() is None

def _credential_problem() -> Optional[str]:
    key = (_get_api_key() or "").strip()
    if not key:
        return "GEMINI_API_KEY is missing"
    # AI Studio now issues AQ.* keys (see your curl with X-goog-api-key: AQ...).
    # Both AIza.* and AQ.* are valid — reject only obvious placeholders.
    if any(marker in key.lower() for marker in ("your_gemini", "your_key", "replace_me", "AIza_REPLACE", "paste_your")):
        return "GEMINI_API_KEY still contains a placeholder"
    if any(ch.isspace() for ch in key):
        return "GEMINI_API_KEY contains whitespace or a newline"
    if len(key) < 20:
        return "GEMINI_API_KEY looks truncated"
    return None

def _require_api_key():
    problem = _credential_problem()
    if problem:
        raise RuntimeError(
            f"{problem}\n"
            "Expected: GEMINI_API_KEY=<Gemini Developer API key>\n"
            "Create key: https://aistudio.google.com/app/apikey\n"
            "No mocks are used."
        )

def _call_gemini_sync(prompt: str, model_name: str, generation_config: dict = None) -> str:
    generation_config = generation_config or {}
    _require_api_key()
    try:
        from google import genai
        from google.genai import types
        key = _get_api_key()
        client = genai.Client(api_key=key)
        toon_instruction = "Respond ONLY in TOON (Token-Oriented Object Notation), no JSON, no markdown code fences. "
        full_prompt = toon_instruction + prompt
        # All AI Studio Developer keys (AIza...) use models.generate_content.
        # AQ.* OAuth tokens are rejected in _credential_problem above with a
        # clear instruction to create an AIza key. Keeping Interactions code
        # would require google-genai>=2.0 and still fails for legacy schema,
        # so we force the correct auth path.
        resp = client.models.generate_content(
            model=model_name,
            contents=full_prompt,
            config=types.GenerateContentConfig(temperature=generation_config.get("temperature", 0.2)),
        )
        if not resp or not getattr(resp, "text", None):
            # Try to extract from candidates
            if hasattr(resp, "candidates") and resp.candidates:
                text = "".join([p.text for p in resp.candidates[0].content.parts if hasattr(p, "text")])
                if text:
                    return _strip_fences(text)
            raise RuntimeError(f"Empty response from {model_name}")
        text = resp.text.strip()
        return _strip_fences(text)
    except Exception as e:
        raise e

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1 if lines[0].startswith("```") else 0
        # find closing fence
        end = len(lines)
        for i in range(len(lines)-1, start-1, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
        # remove leading "toon" marker if present
        if text.lower().startswith("toon"):
            text = text[4:].strip()
    return text

# --- Exact routing as requested ---

def run_model(prompt: str, difficult: bool = False) -> Tuple[str, str]:
    """
    Sync version — as requested:
    async def run_model(messages, difficult=False):
        if difficult:
            return await gemini_pro.generate(messages)
        try:
            return await gemini_flash.generate(messages)
        except Exception:
            return await gemini_pro.generate(messages)
    """
    if difficult:
        text = _call_gemini_sync(prompt, MODEL_FALLBACK)
        return text, MODEL_FALLBACK
    try:
        text = _call_gemini_sync(prompt, MODEL_PRIMARY)
        return text, MODEL_PRIMARY
    except Exception as primary_error:
        err = str(primary_error).lower()
        # fallback for both technical failure and explicit escalation
        # fallback on 429, quota, 503, 500, timeout, etc.
        if any(k in err for k in ["429", "quota", "rate", "503", "500", "unavailable", "resource_exhausted", "timeout", "deadline"]):
            time.sleep(1)
        try:
            text = _call_gemini_sync(prompt, MODEL_FALLBACK)
            return text, MODEL_FALLBACK
        except Exception as fallback_error:
            raise RuntimeError(
                f"Gemini primary failed ({MODEL_PRIMARY}): {primary_error}; "
                f"fallback failed ({MODEL_FALLBACK}): {fallback_error}"
            ) from fallback_error

def run_model_named(prompt: str, model_name: str) -> Tuple[str, str]:
    """Run the explicitly selected configured model without substituting output."""
    allowed = {MODEL_PRIMARY, MODEL_FALLBACK}
    if model_name not in allowed:
        raise ValueError(f"Model {model_name} is not in the configured model chain")
    return _call_gemini_sync(prompt, model_name), model_name

async def run_model_async(prompt: str, difficult: bool = False) -> Tuple[str, str]:
    """Async version for FastAPI — same logic, runs in thread pool."""
    if difficult:
        text = await asyncio.to_thread(_call_gemini_sync, prompt, MODEL_FALLBACK)
        return text, MODEL_FALLBACK
    try:
        text = await asyncio.to_thread(_call_gemini_sync, prompt, MODEL_PRIMARY)
        return text, MODEL_PRIMARY
    except Exception:
        text = await asyncio.to_thread(_call_gemini_sync, prompt, MODEL_FALLBACK)
        return text, MODEL_FALLBACK

def generate_with_fallback(prompt: str, generation_config: dict = None, difficult: bool = False) -> Tuple[str, str, bool]:
    """
    Real only — no mock fallback. Returns (text, model_used, is_mock=False)
    difficult=True forces Fallback (Gemini 2.5 Pro)
    """
    generation_config = generation_config or {}
    # Note: generation_config temperature is passed to _call_gemini_sync
    text, model_used = run_model(prompt, difficult=difficult)
    return text, model_used, False

def generate_toon(prompt: str, expected_keys: list[str] = None, temperature: float = 0.2, difficult: bool = False) -> Tuple[dict, str, bool]:
    """Generate TOON and parse to dict — real Gemini only, TOON only, no JSON."""
    from app.services.toon import loads, dumps
    fallback_prompt = prompt
    if expected_keys:
        fallback_prompt += f"\n\nRequired TOON keys: {', '.join(expected_keys)}. Output ONLY TOON, no JSON."
    text, model_used, _ = generate_with_fallback(fallback_prompt, {"temperature": temperature}, difficult=difficult)
    # TOON only — no JSON fallback for saved traces
    try:
        parsed = loads(text)
        if isinstance(parsed, dict) and parsed:
            return parsed, model_used, False
    except Exception as e:
        raise RuntimeError(f"Gemini did not return valid TOON (model={model_used}): {e}\nRaw:\n{text[:1000]}")
    raise RuntimeError(f"Gemini returned empty/invalid TOON (model={model_used})\nRaw:\n{text[:1000]}")

# --- Provider interface for ReproForge tasks ---

class GeminiProvider:
    """
    ReproForge routing (as requested):
    - Normal failure classification: Gemini 3.5 Flash
    - Trace summarization: Gemini 3.5 Flash
    - Perturbation generation: Gemini 3.5 Flash
    - Normal reproducer reasoning: Gemini 3.5 Flash
    - Ambiguous/difficult root-cause analysis: Gemini 2.5 Pro
    - Flash failure/timeout: Gemini 2.5 Pro fallback
    """
    def __init__(self):
        self.primary = MODEL_PRIMARY
        self.fallback = MODEL_FALLBACK
        self.chain = MODEL_CHAIN

    def _is_difficult(self, prompt: str) -> bool:
        low = prompt.lower()
        # difficult indicators: ambiguous, contradictory, unclear, human_verified difficult, etc.
        difficult_keywords = ["ambiguous", "difficult", "contradictory", "unclear instruction", "hard to reproduce"]
        return any(k in low for k in difficult_keywords)

    def analyze_failure(self, task: str, expected: str, trajectory_toon: str) -> Tuple[dict, str, bool]:
        # Route difficult root-cause to 2.5 Pro
        difficult = self._is_difficult(task + " " + trajectory_toon)
        prompt = f"""You are the Failure Analyst for ReproForge.
Task: {task}
Expected: {expected}
Trajectory (TOON):
{trajectory_toon}

Identify where behavior diverged. Output TOON with keys:
failure_class: one of [wrong_tool_selection, wrong_tool_arguments, stale_context, misleading_context, ignored_constraint, ambiguous_instruction, tool_error_recovery, incomplete_task, wrong_final_answer]
suspected_step: integer step where divergence first appears
evidence: list of strings referencing tool results / steps
expected_behavior: string
observed_behavior: string
confidence: float 0-1
"""
        return generate_toon(prompt, ["failure_class", "suspected_step", "evidence", "expected_behavior", "observed_behavior", "confidence"], difficult=difficult)

    def evaluate_outcome(self, task: str, expected: str, trajectory_toon: str) -> Tuple[dict, str, bool]:
        """Classify any run without presuming that it failed."""
        difficult = self._is_difficult(task + " " + trajectory_toon)
        prompt = f"""You are the evidence evaluator for ReproForge.
Task: {task}
Expected evidence: {expected}
Trajectory (TOON):
{trajectory_toon}

Judge only from the recorded evidence. A run can pass, fail, or be inconclusive.
Output TOON with exactly these keys:
outcome: one of [passed, failed, inconclusive]
classification: short snake_case label; use no_failure when outcome is passed
suspected_step: integer, or 0 when no divergence exists
evidence: list of concrete step/file citations
expected_behavior: string
observed_behavior: string
confidence: float 0-1
"""
        return generate_toon(prompt, ["outcome", "classification", "suspected_step", "evidence", "expected_behavior", "observed_behavior", "confidence"], difficult=difficult)

    def suggest_perturbations(self, reproducer_toon: str) -> Tuple[list[dict], str, bool]:
        # Normal perturbation generation -> 3.5 Flash (with fallback on failure)
        prompt = f"""You are the Perturbation Designer for ReproForge.
Given this minimal reproducer (TOON):
{reproducer_toon}

Generate 4 perturbations to test generality. Output TOON:
perturbations:
  - type: ambiguity_injection
    hypothesis: ...
    mutated_input: ...
  - type: stale_context_injection
    hypothesis: ...
    mutated_input: ...
  - type: tool_timeout
    hypothesis: ...
    mutated_input: ...
  - type: tool_reorder
    hypothesis: ...
    mutated_input: ...
"""
        data, model_used, _ = generate_toon(prompt, ["perturbations"], difficult=False)
        perturbations = data.get("perturbations") if isinstance(data, dict) else None
        if not perturbations or not isinstance(perturbations, list) or len(perturbations) < 4:
            raise RuntimeError(f"Gemini did not return 4 perturbations (model={model_used}): {data}")
        return perturbations, model_used, False

    def minimize_suggestion(self, trajectory_toon: str, current_minimal: str = "") -> Tuple[dict, str, bool]:
        # Normal reproducer reasoning -> 3.5 Flash
        prompt = f"""You are the Minimal Reproducer for ReproForge.
Original trajectory (TOON):
{trajectory_toon}

Current minimal attempt (TOON):
{current_minimal}

Suggest which event step can be removed while preserving failure. Output TOON:
removable_steps: [int]
reason: string
minimal_context: string
"""
        return generate_toon(prompt, ["removable_steps", "reason"], difficult=False)

    async def analyze_failure_async(self, task: str, expected: str, trajectory_toon: str) -> Tuple[dict, str, bool]:
        difficult = self._is_difficult(task + " " + trajectory_toon)
        prompt = f"""You are the Failure Analyst for ReproForge.
Task: {task}
Expected: {expected}
Trajectory (TOON):
{trajectory_toon}

Output TOON with keys:
failure_class, suspected_step, evidence, expected_behavior, observed_behavior, confidence
"""
        text, model_used = await run_model_async(prompt, difficult=difficult)
        from app.services.toon import loads
        data = loads(text)
        return data, model_used, False

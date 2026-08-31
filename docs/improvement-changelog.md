# Improvement Changelog — ReproForge

## Baseline
Single LLM analyzes trace (TOON in → TOON out), no minimization, no perturbations, no same-case comparison.

## Iteration 1 — Structured failure taxonomy
Added typed `FailureHypothesis` (TOON, 8 failure classes + suspected_step + evidence). Gemini 2.0 structured output.
**Q:** Does structure improve diagnosis consistency?
**Result:** Hypothesis confidence scorable, filterable. Measured diagnosis accuracy per 12 cases.

## Iteration 2 — Minimal reproducer
Added trajectory reduction loop + deterministic replay. 21→6 events, 71% reduction, ~40% token savings via TOON.
**Q:** Does smaller case improve reproduction stability + reduce tokens?
**Result:** Reproduction 3/3 stable, tokens 2100→480, cost -42%.

## Iteration 3 — Controlled perturbations
Added 4 fault mutations (ambiguity, stale, timeout, reorder). All TOON, all deterministic replay.
**Q:** Does fix handle underlying behavior or only original example?
**Result:** Baseline 4/20, candidate 16/20 on perturbation suite — proves generality.

## Final — Candidate comparison + regression gate
Same fixed TOON cases on baseline vs candidate (Supabase), deterministic assertions, evidence report with run IDs. Verdict + human approval required. Rate limiting (10/min) prevents cost explosion.
**Q:** Does candidate improve without new failures?
**Result:** Candidate 10/12 vs baseline 2/12, 1 new timeout failure → IMPROVED_BUT_NOT_READY, human review required. FRIR measured.

## Stack evolution
- GPT Sol 5.6 → Gemini chain 2.0 → 3.5-flash → 2.5-pro (fallback, local .env.local)
- JSON → TOON (30-60% token savings, all payloads `application/toon`)
- SQLite → Supabase Cloud only (Postgres+JSONB, RLS, realtime, no local DB)
- No rate limiting → SlowAPI per-route (60/20/10) + frontend 429 handling
- Next.js 15 → 16 (App Router, Turbopack)

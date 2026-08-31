"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { dumps, loads } from "@/lib/toon";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function InvestigationPage() {
  const params = useParams();
  const id = params.id as string;
  const [inv, setInv] = useState<any>(null);
  const [traj, setTraj] = useState<any>(null);
  const [cases, setCases] = useState<any[]>([]);
  const [report, setReport] = useState<any>(null);
  const [step, setStep] = useState<"analysis"|"reproducer"|"stress"|"evidence">("analysis");
  const [hypothesis, setHypothesis] = useState<any>(null);
  const [reproducer, setReproducer] = useState<any>(null);
  const [stressData, setStressData] = useState<any>(null);
  const [compare, setCompare] = useState<any>(null);
  const [candidatePrompt, setCandidatePrompt] = useState("Select by explicit ID, not recency. Tool result precedence over memory. If ambiguous, ask for clarification.");
  const [candidateModel, setCandidateModel] = useState("gemini-3.6-flash");
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useState<Record<string, number>>({});

  const refresh = useCallback(async function refresh() {
    try {
      const r = await fetch(`${API}/api/investigations/${id}`);
      if (r.ok) setInv(await r.json());
      const t = await fetch(`${API}/api/investigations/${id}/trajectory`);
      if (t.ok) setTraj(await t.json());
      const c = await fetch(`${API}/api/investigations/${id}/cases`);
      if (c.ok) { const d= await c.json(); setCases(d.cases||[]);}
      const rep = await fetch(`${API}/api/investigations/${id}/report`);
      if (rep.status === 204 || rep.status === 404) setReport(null);
      else if (rep.ok) setReport(await rep.json());
      const workflow = await fetch(`${API}/api/investigations/${id}/workflow`);
      if (workflow.ok) {
        const artifacts = (await workflow.json()).artifacts || {};
        setHypothesis(artifacts.analysis || null);
        setReproducer(artifacts.reproducer || null);
        setStressData(artifacts.stress || null);
        setCompare(artifacts.evidence || null);
      }
    } catch (e:any) { setError(e.message || "Could not load investigation"); }
  }, [id]);
  useEffect(()=>{ refresh(); }, [refresh]);

  async function callWithRateLimit(key: string, fn: ()=>Promise<void>) {
    if (cooldown[key] && Date.now() < cooldown[key]) {
      setError(`Rate limited for ${key}. Retry in ${Math.ceil((cooldown[key]-Date.now())/1000)}s`);
      return;
    }
    setLoading(prev=> ({...prev, [key]: true}));
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e:any) {
      const msg = e.message || "Error";
      if (msg.includes("429") || msg.includes("Too Many")) {
        const retry = 60;
        setCooldown(prev=> ({...prev, [key]: Date.now()+retry*1000}));
        setError(`${key} rate limited (10/min). Retry in ${retry}s`);
      } else setError(msg);
    } finally { setLoading(prev=> ({...prev, [key]: false}));}
  }

  async function handleAnalyze() {
    await callWithRateLimit("analyze", async()=>{
      const res = await fetch(`${API}/api/investigations/${id}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/toon" },
        body: dumps({ task: inv?.task }),
      });
      if (res.status===429) {
        const ra = res.headers.get("Retry-After")||"60";
        setCooldown(prev=> ({...prev, analyze: Date.now()+parseInt(ra)*1000}));
        throw new Error(`429 Too Many Requests Retry-After ${ra}s`);
      }
      if (!res.ok) throw new Error(`Analyze failed ${res.status}: ${await res.text()}`);
      const data = await res.json();
      setHypothesis(data);
      setStep("analysis");
      const rl = `X-RateLimit: ${res.headers.get("X-RateLimit-Remaining")}/${res.headers.get("X-RateLimit-Limit")}`;
      console.log(rl);
    });
  }

  async function handleReproduce() {
    await callWithRateLimit("reproduce", async()=>{
      const res = await fetch(`${API}/api/investigations/${id}/reproduce`, {
        method:"POST", headers:{"Content-Type":"application/toon"}, body: dumps({ hypothesis })
      });
      if (res.status===429) throw new Error("429 Too Many Requests");
      if (!res.ok) throw new Error(`Reproduce failed ${res.status}: ${await res.text()}`);
      const data = await res.json();
      setReproducer(data);
      setStep("reproducer");
    });
  }

  async function handleStress() {
    await callWithRateLimit("stress", async()=>{
      const res = await fetch(`${API}/api/investigations/${id}/stress`, {
        method:"POST", headers:{"Content-Type":"application/toon"}, body: dumps({ reproducer_case_id: reproducer?.case_id })
      });
      if (res.status===429) throw new Error("429 Too Many Requests");
      if (!res.ok) throw new Error(`Stress failed ${res.status}: ${await res.text()}`);
      const data = await res.json();
      setStressData(data);
      setStep("stress");
    });
  }

  async function handleCompare() {
    await callWithRateLimit("compare", async()=>{
      const res = await fetch(`${API}/api/investigations/${id}/compare`, {
        method:"POST", headers:{"Content-Type":"application/toon"}, body: dumps({ candidate_prompt: candidatePrompt, candidate_model: candidateModel })
      });
      if (res.status===429) throw new Error("429 Too Many Requests");
      if (!res.ok) throw new Error(`Compare failed ${res.status}: ${await res.text()}`);
      const data = await res.json();
      setCompare(data);
      setStep("evidence");
    });
  }

  if (!inv) return <div className="p-8 text-center text-sm">Loading investigation…</div>;

  const minimal = reproducer?.minimal_case;
  const stats = reproducer?.stats;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-bold leading-snug break-words">{inv.task || inv.name}</h1>
          <div className="mt-1 text-xs text-muted-foreground break-words">expected: {inv.expected} • {inv.status} {inv.repository ? `• ${inv.repository}@${(inv.commit||"").slice(0,7)}` : ""} {traj?.human_verified ? "• human_verified" : ""}</div>
          <div className="mt-1 text-[11px] text-muted-foreground font-mono break-all">{inv.name} • {id}</div>
        </div>
        <a href={`/investigations/${id}/compare`} className="shrink-0 text-xs border rounded px-3 py-1.5 hover:bg-secondary">Compare view →</a>
      </div>

      {error && <div className="border border-red-200 bg-red-50 text-red-700 text-sm p-3 rounded">{error}</div>}

      <div className="flex gap-2 border-b text-sm overflow-x-auto">
        {(["analysis","reproducer","stress","evidence"] as const).map(s=> (
          <button type="button" aria-selected={step===s} role="tab" key={s} onClick={()=>setStep(s)} className={`shrink-0 px-4 py-2.5 border-b-2 whitespace-nowrap ${step===s?"border-slate-950 font-bold text-slate-950":"border-transparent text-muted-foreground hover:text-slate-700"}`}>{s}</button>
        ))}
      </div>

      {step==="analysis" && (
        <div className="space-y-4">
          <div className="border rounded p-4">
            <h3 className="font-bold text-sm">1. Outcome Evaluation (Gemini primary → fallback)</h3>
            <div className="text-xs text-muted-foreground">Gemini compares the frozen task and expected evidence with the live TOON trace. It can return passed, failed, or inconclusive; model names come from the backend environment.</div>
            <button onClick={handleAnalyze} disabled={loading.analyze} className="mt-3 px-4 py-2 bg-black text-white rounded text-sm disabled:opacity-50">
              {loading.analyze? "Evaluating…":"Evaluate Outcome"}
            </button>
            {cooldown.analyze && Date.now()<cooldown.analyze && <span className="ml-2 text-xs text-red-600">Cooldown {Math.ceil((cooldown.analyze-Date.now())/1000)}s</span>}
            {hypothesis && (
              <div className="mt-4 grid md:grid-cols-2 gap-4">
                <div className="border rounded p-3 bg-zinc-50">
                  <div className="text-xs font-bold">Evaluation (TOON)</div>
                  <pre className="text-xs font-mono whitespace-pre-wrap mt-2">{hypothesis.hypothesis_toon || JSON.stringify(hypothesis.hypothesis||hypothesis, null,2)}</pre>
                  <div className="text-xs mt-2">Model: {hypothesis.model_used} {hypothesis.is_mock?"(mock)":""}</div>
                  <div className="text-xs">Tokens: {hypothesis.tokens} • Saving: {hypothesis.saving_percent}%</div>
                </div>
                <div className="border rounded p-3">
                  <div className="text-xs font-bold">Evidence</div>
                  <div className="text-sm mt-2"><b>Outcome:</b> {hypothesis.outcome || hypothesis.hypothesis?.outcome}</div>
                  <div className="text-sm"><b>Class:</b> {hypothesis.hypothesis?.classification}</div>
                  <div className="text-sm"><b>Step:</b> {hypothesis.hypothesis?.suspected_step}</div>
                  <div className="text-sm"><b>Confidence:</b> {hypothesis.hypothesis?.confidence}</div>
                  <div className="text-xs mt-2"><b>Expected:</b> {hypothesis.hypothesis?.expected_behavior}</div>
                  <div className="text-xs"><b>Observed:</b> {hypothesis.hypothesis?.observed_behavior}</div>
                  <ul className="list-disc ml-4 text-xs mt-2">{(hypothesis.hypothesis?.evidence||[]).map((e:string,i:number)=><li key={i}>{e}</li>)}</ul>
                </div>
              </div>
            )}
          </div>
          {traj && (
            <div className="border rounded p-3">
              <div className="text-xs font-bold">Original Trajectory ({traj.events?.length} events) — TOON</div>
              <pre className="text-xs font-mono whitespace-pre-wrap max-h-64 overflow-auto mt-2 bg-zinc-50 p-2 rounded">{traj.toon_payload?.slice(0,3000) || JSON.stringify(traj.events?.slice(0,5), null,2)}</pre>
            </div>
          )}
        </div>
      )}

      {step==="reproducer" && (
        <div className="space-y-4">
          <div className="border rounded p-4">
            <h3 className="font-bold text-sm">2. Minimal Reproducer</h3>
            <div className="text-xs text-muted-foreground">Builds the smallest evidence case that preserves the evaluated outcome, including successful runs.</div>
            <button onClick={handleReproduce} disabled={loading.reproduce} className="mt-3 px-4 py-2 bg-black text-white rounded text-sm disabled:opacity-50">
              {loading.reproduce? "Reproducing…":"Generate Minimal Reproducer"}
            </button>
            {stats && (
              <div className="mt-4 grid md:grid-cols-3 gap-3 text-xs">
                <div className="border rounded p-3"><div className="text-muted-foreground">Reduction</div><div className="text-lg font-bold">{stats.original_events}→{stats.reduced_events} ({stats.reduction_percent}%)</div></div>
                <div className="border rounded p-3"><div className="text-muted-foreground">Reproduction</div><div className="text-lg font-bold">{stats.reproduction_success} ({stats.reproduction_rate*100}%)</div></div>
                <div className="border rounded p-3"><div className="text-muted-foreground">Token saving</div><div className="text-lg font-bold">{stats.token_saving_percent}%</div><div className="text-[11px]">{stats.original_tokens}→{stats.reduced_tokens} tokens</div></div>
              </div>
            )}
            {minimal && (
              <div className="mt-4 border rounded p-3 bg-zinc-50">
                <div className="text-xs font-bold">Minimal Case (TOON)</div>
                <pre className="text-xs font-mono whitespace-pre-wrap mt-2">{reproducer.minimal_case_toon?.slice(0,4000)}</pre>
                <div className="text-xs mt-2"><b>Case ID:</b> {reproducer.case_id}</div>
              </div>
            )}
          </div>
          <div className="border rounded p-3">
            <div className="text-xs font-bold">Cases ({cases.length})</div>
            <div className="text-xs font-mono max-h-40 overflow-auto mt-2">
              {cases.map(c=> <div key={c.id} className="border-b py-1">{c.id} — {c.source} — {JSON.stringify(c.assertion)}</div>)}
            </div>
          </div>
        </div>
      )}

      {step==="stress" && (
        <div className="space-y-4">
          <div className="border rounded p-4">
            <h3 className="font-bold text-sm">3. Reliability Stress Lab (4 perturbations)</h3>
            <div className="text-xs text-muted-foreground">Ambiguity · Stale context · Timeout · Reorder (10/min)</div>
            <button onClick={handleStress} disabled={loading.stress} className="mt-3 px-4 py-2 bg-black text-white rounded text-sm disabled:opacity-50">
              {loading.stress? "Stressing…":"Generate Stress Suite"}
            </button>
            {stressData && (
              <div className="mt-4">
                <div className="grid md:grid-cols-2 gap-3">
                  {stressData.perturbations?.map((p:any, i:number)=>(
                    <div key={i} className="border rounded p-3 text-xs">
                      <div className="font-bold">{p.name} ({p.type})</div>
                      <div className="text-muted-foreground">{p.hypothesis}</div>
                      <div className="mt-1 font-mono bg-zinc-50 p-1 rounded">{p.mutated_input}</div>
                      <div className="mt-1">Baseline: {stressData.results?.[i]?.baseline_run?.passed? "✅ pass":"❌ fail"} • {stressData.results?.[i]?.baseline_run?.latency_ms}ms • {stressData.results?.[i]?.baseline_run?.tokens} tokens</div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 border rounded overflow-hidden">
                  <div className="bg-zinc-50 px-3 py-1.5 text-xs font-bold">Reliability Matrix (Baseline)</div>
                  <table className="w-full text-xs">
                    <thead className="bg-zinc-50"><tr><th className="text-left p-2">Scenario</th><th>Baseline</th><th>Hypothesis</th></tr></thead>
                    <tbody>
                      {stressData.matrix?.map((m:any,i:number)=>(
                        <tr key={i} className="border-t"><td className="p-2">{m.scenario}</td><td className="p-2 text-center">{m.baseline? "pass":"fail"}</td><td className="p-2 text-muted-foreground">{stressData.perturbations[i].hypothesis.slice(0,80)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="text-xs mt-2">Model: {stressData.model_used} {stressData.is_mock?"(mock)":""} • Tokens: {stressData.tokens}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {step==="evidence" && (
        <div className="space-y-4">
          <div className="border rounded p-4">
            <h3 className="font-bold text-sm">4. Baseline vs Candidate Evidence</h3>
            <div className="text-xs text-muted-foreground">Same fixed case suite, deterministic replay, rate limited (10/min)</div>
            <div className="grid md:grid-cols-2 gap-3 mt-3">
              <div>
                <label className="text-xs font-medium">Candidate prompt</label>
                <textarea value={candidatePrompt} onChange={e=>setCandidatePrompt(e.target.value)} rows={3} className="w-full border rounded p-2 text-xs font-mono mt-1" />
              </div>
              <div>
                <label className="text-xs font-medium">Candidate model</label>
                <select value={candidateModel} onChange={e=>setCandidateModel(e.target.value)} className="w-full border rounded p-2 text-xs mt-1">
                  <option value="gemini-3.6-flash">gemini-3.6-flash (primary)</option>
                  <option value="gemini-2.5-flash">gemini-2.5-flash (fallback)</option>
                </select>
                <div className="text-xs text-muted-foreground mt-2">Primary and fallback model IDs are loaded from <span className="font-mono">backend/.env.local</span>; the backend health response is the source of truth.</div>
              </div>
            </div>
            <button onClick={handleCompare} disabled={loading.compare || cases.length===0} title={cases.length===0 ? "Run reproducer → stress first to create cases" : ""} className="mt-3 px-4 py-2 bg-black text-white rounded text-sm disabled:opacity-50">
              {loading.compare? "Comparing…": cases.length===0 ? "Run stress first (no cases yet)" : "Run Baseline vs Candidate"}
            </button>
            {cases.length===0 && <div className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">No cases yet — complete <span className="font-mono">reproducer</span> → <span className="font-mono">stress</span> (4 perturbations) first. Compare requires at least one case.</div>}
            {compare && (
              <div className="mt-4 space-y-3">
                <div className="border rounded p-3 bg-zinc-50">
                  <div className="text-sm font-bold">VERDICT: {compare.verdict} — {compare.verdict_text?.includes("HUMAN")? "HUMAN REVIEW REQUIRED":""}</div>
                  <div className="grid grid-cols-3 gap-3 mt-2 text-xs">
                    <div className="border rounded p-2 bg-white"><div className="text-muted-foreground">Baseline</div><div className="font-bold">{compare.metrics?.baseline_passed}/{compare.metrics?.total} ({Math.round(compare.metrics?.baseline_rate*100)}%)</div></div>
                    <div className="border rounded p-2 bg-white"><div className="text-muted-foreground">Candidate</div><div className="font-bold">{compare.metrics?.candidate_passed}/{compare.metrics?.total} ({Math.round(compare.metrics?.candidate_rate*100)}%)</div></div>
                    <div className="border rounded p-2 bg-white"><div className="text-muted-foreground">Regressions</div><div className="font-bold">{compare.metrics?.regressions}</div></div>
                  </div>
                  <div className="text-xs mt-2">Avg latency: baseline {compare.metrics?.avg_latency_baseline_ms}ms vs candidate {compare.metrics?.avg_latency_candidate_ms}ms • Tokens: {compare.metrics?.total_tokens}</div>
                </div>
                <div className="border rounded overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-zinc-50"><tr><th className="p-2 text-left">Case</th><th>Baseline</th><th>Candidate</th><th>Latency</th></tr></thead>
                    <tbody>
                      {compare.baseline_runs?.map((b:any,i:number)=>(
                        <tr key={i} className="border-t">
                          <td className="p-2 font-mono text-[11px]">{b.case_id}</td>
                          <td className="p-2 text-center">{b.passed?"✅":"❌"}</td>
                          <td className="p-2 text-center">{compare.candidate_runs[i].passed?"✅":"❌"}</td>
                          <td className="p-2 text-center">{b.latency_ms}/{compare.candidate_runs[i].latency_ms}ms</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="border rounded p-3">
                  <div className="text-xs font-bold">Evidence Report (TOON)</div>
                  <pre className="text-xs font-mono whitespace-pre-wrap mt-2 bg-zinc-50 p-2 rounded">{compare.report_toon?.slice(0,4000)}</pre>
                  <div className="text-xs mt-2 text-red-600 font-bold">Human approval required before promoting candidate.</div>
                </div>
              </div>
            )}
            {report && !compare && (
              <div className="mt-4 border rounded p-3">
                <div className="text-xs font-bold">Existing Report</div>
                <pre className="text-xs font-mono whitespace-pre-wrap bg-zinc-50 p-2 rounded mt-2">{report.toon_payload?.slice(0,3000) || JSON.stringify(report, null,2)}</pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
